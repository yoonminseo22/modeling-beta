import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from googleapiclient.discovery import build as yt_build
import re

YOUTUBE_API_KEY = st.secrets["youtube"]["api_key"]

st.set_page_config(page_title="📈 유튜브 조회수 분석기", layout="centered")
st.title("📈 유튜브 조회수 분석기")
st.subheader("Google 계정으로 로그인하고, 조회수를 분석하세요!")

# OAuth2 설정
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

# ─── Flow를 세션에 딱 한 번만 생성 ───
if "flow" not in st.session_state:
    st.session_state.flow = Flow.from_client_config(
        flow_config, scopes=SCOPES, redirect_uri=redirect_uri
    )
flow = st.session_state.flow

# ─── 인증 상태 체크 ───
if "credentials" not in st.session_state:
    # 1) 승인을 위한 URL 링크
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent"
    )
    st.markdown(f"[🔐 Google 계정으로 로그인하기]({auth_url})")

    # 2) 리디렉션 후 code 처리
    # st.query_params 는 { key: [list_of_values], ... } 형태
    params = st.query_params
    if "code" in params:
        code = params["code"][0]
        try:
            flow.fetch_token(code=code)
            st.session_state.credentials = flow.credentials

            # URL에서 code 파라미터 지우기
            st.query_params = {}

            # JS로 강제 리다이렉트하여 세션 유지된 채로 페이지 재로딩
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
    # ─── 인증된 상태 ───
    creds   = st.session_state.credentials
    request = Request()
    idinfo  = id_token.verify_oauth2_token(creds.id_token, request, client_id)

    # idinfo.get 으로 안전하게 꺼내되, 없으면 이메일 앞 부분을 이름처럼 사용
    display_name = idinfo.get("name") or idinfo.get("email", "").split("@")[0]
    st.success(f"👋 안녕하세요, {display_name} 님!")
    st.write("📧 이메일:", idinfo["email"])

        # 1) YouTube Data API 클라이언트
    yt = yt_build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    # 2) 입력 UI: 유튜브 영상 URL
    st.subheader("▶ 유튜브 영상 등록")
    video_url = st.text_input("유튜브 URL을 붙여넣으세요")

    if st.button("영상 등록"):
        # 3) URL에서 Video ID 추출 (표준 https://youtu.be/ID 또는 www.youtube.com/watch?v=ID)
        match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", video_url)
        if not match:
            st.error("❌ 올바른 YouTube URL이 아닙니다.")
        else:
            video_id = match.group(1)
            try:
                # 4) 조회수 가져오기
                resp = yt.videos().list(
                    part="statistics",
                    id=video_id
                ).execute()

                stats = resp["items"][0]["statistics"]
                view_count = int(stats.get("viewCount", 0))

                st.success(f"✅ 현재 조회수: {view_count:,}회")

                # 5) 스프레드시트에 기록
                from datetime import datetime
                timestamp = datetime.utcnow().isoformat()

                service = build("sheets", "v4", credentials=creds)
                service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{SHEET_NAME}!A:D",
                    valueInputOption="RAW",
                    body={"values": [[
                        idinfo["email"],   # 로그인한 유저 이메일
                        video_id,
                        timestamp,
                        view_count
                    ]]}
                ).execute()

                st.success("✅ 스프레드시트에 저장되었습니다!")

            except Exception as e:
                st.error(f"❌ YouTube API 호출 실패: {e}")

    # 스프레드시트 저장 UI
    SPREADSHEET_ID = "11WkROAZtU8bKo1ezzuXiNigbdFyB5rqYPr5Lyd1ve24"
    SHEET_NAME     = "Sheet1"
    service        = build("sheets", "v4", credentials=creds)

    st.subheader("✅ 유튜브 링크를 입력하세요")
    link  = st.text_input("🔗 유튜브 링크")
    views = st.number_input("👁 조회수", min_value=0, step=1)

    if st.button("📩 시트에 저장"):
        try:
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A1",
                valueInputOption="RAW",
                body={"values": [[idinfo["email"], link, views]]}
            ).execute()
            st.success("✅ 저장 완료!")
        except Exception as e:
            st.error(f"❌ 저장 실패: {e}")
