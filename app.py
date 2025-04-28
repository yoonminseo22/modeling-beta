import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from googleapiclient.discovery import build
from googleapiclient.discovery import build as yt_build
import re
from datetime import datetime
import urllib.parse

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
redirect_uri  = "https://modeling-beta-1.streamlit.app/"  # GCP에 정확히 등록된 URI
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

# Flow 객체를 세션에서 딱 한 번만 생성
if "flow" not in st.session_state:
    st.session_state.flow = Flow.from_client_config(
        flow_config, scopes=SCOPES, redirect_uri=redirect_uri
    )
flow = st.session_state.flow

# ── 인증 상태 체크 ──
if "credentials" not in st.session_state:
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent"
    )
    st.markdown(f"[🔐 Google 계정으로 로그인하기]({auth_url})")

    # 사용자가 돌아온 후 query_params 에 code, state 등이 담겨 있습니다.
    if "code" in st.query_params:
        # 1) 쿼리 파라미터를 평탄화
        flat = {k: v[0] for k, v in st.query_params.items()}
        # 2) redirect_uri + ? + urlencode 로 전체 URL 재구성
        auth_response = redirect_uri + "?" + urllib.parse.urlencode(flat)
        try:
            # 전체 리디렉션 URL을 통째로 넘겨줍니다.
            flow.fetch_token(authorization_response=auth_response)
            # 토큰 저장
            st.session_state["credentials"] = flow.credentials
            # URL 파라미터 지우고 새로고침
            st.query_params = {}
            st.markdown(
                """<script>
                     window.location.href = window.location.origin + window.location.pathname;
                   </script>""",
                unsafe_allow_html=True
            )
            st.stop()
        except Exception as e:
            st.error(f"❌ 인증 실패: {e}")

else:
    creds = st.session_state["credentials"]
    request = Request()
    try:
        idinfo = id_token.verify_oauth2_token(creds.id_token, request, client_id)
    except Exception as e:
        st.error(f"❌ 토큰 검증 실패: {e}")
        st.stop()

    # ── API 클라이언트 생성 ──
    service = build("sheets", "v4", credentials=creds)
    yt      = yt_build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    # ── 로그인 완료 UI ──
    display_name = idinfo.get("name") or idinfo["email"].split("@")[0]
    st.success(f"👋 안녕하세요, {display_name} 님!")
    st.write("📧 이메일:", idinfo["email"])

    # ── 기존 유튜브 등록 & 회귀분석 로직 그대로 ──
    st.subheader("▶ 유튜브 영상 등록")
    video_url = st.text_input("유튜브 URL을 붙여넣으세요")
    if st.button("영상 등록"):
        match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", video_url)
        if not match:
            st.error("❌ 올바른 YouTube URL이 아닙니다.")
        else:
            video_id = match.group(1)
            try:
                resp = yt.videos().list(part="statistics", id=video_id).execute()
                view_count = int(resp["items"][0]["statistics"].get("viewCount", 0))
            except Exception as e:
                st.error(f"❌ YouTube API 호출 실패: {e}")
                st.stop()

            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            today     = timestamp.split(" ")[0]
            existing = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!B:C"
            ).execute().get("values", [])
            if any(vid==video_id and ts.startswith(today) for vid,ts in existing):
                st.info("ℹ️ 오늘 이미 등록된 영상입니다.")
                st.stop()

            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A:D",
                valueInputOption="RAW",
                body={"values":[[
                    idinfo["email"], video_id, timestamp, view_count
                ]]}
            ).execute()
            st.success(f"✅ 조회수: {view_count:,}회")
            st.success("✅ 스프레드시트에 저장되었습니다!")


    import numpy as np
    import matplotlib.pyplot as plt
    from datetime import datetime, timedelta

    # ─── 3) 데이터 불러와서 회귀분석 UI ───
    st.subheader("📊 회귀분석 및 예측")

    # 1) 분석할 비디오 선택용 콤보박스
    all_rows = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!B2:B"
    ).execute().get("values", [])
    video_ids = sorted({ row[0] for row in all_rows if row })

    if video_ids:
        sel_video = st.selectbox("분석할 비디오 ID를 선택하세요", video_ids)

        if st.button("분석 시작"):
            full = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A2:D"
            ).execute().get("values", [])
            pts = []
            for email, vid, ts, vc in full:
                if vid == sel_video:
                    dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                    pts.append((dt, int(vc)))
            if len(pts) < 3:
                st.error("데이터가 3개 미만이어서 2차회귀분석을 할 수 없습니다.")
            else:
                pts.sort(key=lambda x: x[0])
                t0 = pts[0][0]
                x = np.array([ (dt - t0).total_seconds()/3600 for dt,_ in pts ])
                y = np.array([ vc for _,vc in pts ])

                a, b, c = np.polyfit(x, y, 2)
                st.latex(rf"조회수 = {a:.3f} x^2 + {b:.3f} x + {c:.3f}")

                roots = np.roots([a, b, c - 1_000_000])
                real_pos = [ r for r in roots if np.isreal(r) and r>0 ]
                if real_pos:
                    hours = real_pos[0].real
                    predict_dt = t0 + timedelta(hours=hours)
                    st.write(f"🎯 조회수 1,000,000회 예상 시점: **{predict_dt}**")
                else:
                    st.write("⚠️ 1,000,000회 달성 예측값이 없습니다.")

                fig, ax = plt.subplots()
                ax.scatter(x, y, label="실제 값")
                xs = np.linspace(0, x.max()*1.1, 200)
                ys = a*xs**2 + b*xs + c
                ax.plot(xs, ys, label="2차 회귀곡선")
                ax.set_xlabel("시간 경과 (시간)")
                ax.set_ylabel("조회수")
                ax.legend()
                st.pyplot(fig)
    else:
        st.info("아직 등록된 영상이 없습니다.")
