import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from googleapiclient.discovery import build
from googleapiclient.discovery import build as yt_build
import re
from datetime import datetime

# ── 시크릿 불러오기 ──
YOUTUBE_API_KEY = st.secrets["youtube"]["api_key"]
SPREADSHEET_ID  = st.secrets["sheets"]["spreadsheet_id"]
SHEET_NAME      = st.secrets["sheets"]["sheet_name"]

# ── 페이지 설정 ──
st.set_page_config(page_title="📈 유튜브 조회수 분석기", layout="centered")
st.title("📈 유튜브 조회수 분석기")
st.subheader("Google 계정으로 로그인하고, 조회수를 분석하세요!")

# ── OAuth2 설정 ──
client_id     = st.secrets["google_oauth"]["client_id"]
client_secret = st.secrets["google_oauth"]["client_secret"]
redirect_uri  = "https://modeling-beta-1.streamlit.app"
SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/spreadsheets",
    "openid",
]
flow_config = {
    "web": {
        "client_id":     client_id,
        "client_secret": client_secret,
        "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
        "token_uri":     "https://oauth2.googleapis.com/token",
        "redirect_uris": [redirect_uri],
    }
}

# Flow 객체를 세션에 딱 한 번만 생성
if "flow" not in st.session_state:
    st.session_state.flow = Flow.from_client_config(
        flow_config, scopes=SCOPES, redirect_uri=redirect_uri
    )
flow = st.session_state.flow

# ── 인증 상태 체크 ──
if "credentials" not in st.session_state:
    # 1) 승인 URL 생성
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent"
    )
    st.markdown(f"[🔐 Google 계정으로 로그인하기]({auth_url})")

    # 2) 리디렉트 후 코드 처리
    params = st.query_params
    if "code" in params:
        code = params["code"][0]
        try:
            flow.fetch_token(code=code)
            # 세션에 자격 저장
            st.session_state["credentials"] = flow.credentials
            # URL에서 ?code 제거
            st.query_params = {}
            # JS 리다이렉트로 페이지 새로고침
            st.markdown(
                """
                <script>
                  window.location.href = window.location.origin + window.location.pathname;
                </script>
                """,
                unsafe_allow_html=True
            )
            st.stop()
        except Exception as e:
            st.error(f"❌ 인증 실패: {e}")

else:
    # ── 인증된 상태 ──
    creds   = st.session_state["credentials"]
    request = Request()
    idinfo  = id_token.verify_oauth2_token(
        creds.id_token, request, client_id
    )

    # YouTube 및 Sheets 클라이언트 생성
    service = build("sheets", "v4", credentials=creds)
    yt      = yt_build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    # 사용자 인사
    display_name = idinfo.get("name") or idinfo.get("email", "").split("@")[0]
    st.success(f"👋 안녕하세요, {display_name} 님!")
    st.write("📧 이메일:", idinfo["email"])

    # ── 유튜브 영상 등록 UI ──
    st.subheader("▶ 유튜브 영상 등록")
    video_url = st.text_input("유튜브 URL을 붙여넣으세요")

    if st.button("영상 등록"):
        # 1) video_id 추출
        match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", video_url)
        if not match:
            st.error("❌ 올바른 YouTube URL이 아닙니다.")
        else:
            video_id = match.group(1)
            # 2) 조회수 API 호출
            try:
                resp = yt.videos().list(part="statistics", id=video_id).execute()
                view_count = int(resp["items"][0]["statistics"].get("viewCount", 0))
            except Exception as e:
                st.error(f"❌ YouTube API 호출 실패: {e}")
                st.stop()

            # 3) 타임스탬프 생성
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            today     = timestamp.split(" ")[0]

            # ── 중복 체크 ──
            existing = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!B:C"
            ).execute().get("values", [])
            already = any(
                vid == video_id and ts.startswith(today)
                for vid, ts in existing
            )
            if already:
                st.info("ℹ️ 오늘 이 영상은 이미 등록되었습니다.")
                st.stop()

            # 4) 시트에 기록
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A:D",
                valueInputOption="RAW",
                body={"values": [[
                    idinfo["email"],
                    video_id,
                    timestamp,
                    view_count
                ]]}
            ).execute()

            # 결과 표시
            st.success(f"✅ 현재 조회수: {view_count:,}회")
            st.success("✅ 스프레드시트에 저장되었습니다!")
