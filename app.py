import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from googleapiclient.discovery import build
from googleapiclient.discovery import build as yt_build
import re
from datetime import datetime, timedelta
import numpy as np
import matplotlib.pyplot as plt
import urllib.parse

# ── Secrets ──
YOUTUBE_API_KEY = st.secrets["youtube"]["api_key"]
SPREADSHEET_ID  = st.secrets["sheets"]["spreadsheet_id"]
SHEET_NAME      = st.secrets["sheets"]["sheet_name"]

# ── Page setup ──
st.set_page_config(page_title="📈 유튜브 조회수 분석기", layout="centered")
st.title("📈 유튜브 조회수 분석기")
st.subheader("Google 계정으로 로그인하고, 조회수를 분석하세요!")

# ── OAuth2 설정 ──
client_id     = st.secrets["google_oauth"]["client_id"]
client_secret = st.secrets["google_oauth"]["client_secret"]
redirect_uri  = "https://modeling-beta-1.streamlit.app/"
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

# Flow 객체를 세션에 한 번만 생성
if "flow" not in st.session_state:
    st.session_state.flow = Flow.from_client_config(
        flow_config, scopes=SCOPES, redirect_uri=redirect_uri
    )
flow = st.session_state.flow

# ── 인증 상태 체크 ──
if "credentials" not in st.session_state:
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")
    st.markdown(f"[🔐 Google 로그인]({auth_url})")

    if "code" in st.query_params:
        st.error("자동 파싱이 실패했습니다. 아래 textarea에서 전체 URL을 복사→붙여넣기 해주세요.")
        st.markdown(
            """
            <script>
              const ta = document.createElement('textarea');
              ta.value = window.location.href;
              ta.style = 'width:100%;height:120px;font-size:12px;';
              document.body.appendChild(ta);
            </script>
            """,
            unsafe_allow_html=True,
        )
        auth_response = st.text_input(
            "🔑 전체 URL을 여기에 붙여넣으세요",
            placeholder="전체 리디렉션 URL"
        )
        if auth_response:
            try:
                # state 매칭을 위해 URL에서 state 파싱 후 강제로 설정
                qs = urllib.parse.urlparse(auth_response).query
                params = urllib.parse.parse_qs(qs)
                returned_state = params.get("state", [""])[0]
                flow.state = returned_state

                flow.fetch_token(authorization_response=auth_response)
                st.session_state.credentials = flow.credentials
                st.experimental_rerun()
            except Exception as e:
                st.error(f"❌ 인증 실패: {e}")

else:
    creds = st.session_state.credentials
    request = Request()
    try:
        idinfo = id_token.verify_oauth2_token(creds.id_token, request, client_id)
    except Exception as e:
        st.error(f"❌ 토큰 검증 실패: {e}")
        st.stop()

    service = build("sheets", "v4", credentials=creds)
    yt      = yt_build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    display_name = idinfo.get("name") or idinfo["email"].split("@")[0]
    st.success(f"👋 안녕하세요, {display_name} 님!")
    st.write("📧 이메일:", idinfo["email"])

    st.subheader("▶ 유튜브 영상 등록")
    video_url = st.text_input("YouTube URL을 붙여넣으세요")
    if st.button("영상 등록"):
        match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", video_url)
        if not match:
            st.error("❌ 올바른 YouTube URL이 아닙니다.")
        else:
            vid = match.group(1)
            try:
                resp = yt.videos().list(part="statistics", id=vid).execute()
                views = int(resp["items"][0]["statistics"].get("viewCount", 0))
            except Exception as e:
                st.error(f"❌ YouTube API 호출 실패: {e}")
                st.stop()

            ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            today = ts.split()[0]
            vals = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!B:C"
            ).execute().get("values", [])
            if any(v==vid and t.startswith(today) for v,t in vals):
                st.info("ℹ️ 오늘 이미 등록된 영상입니다.")
            else:
                service.spreadsheets().values().append(
                    spreadsheetId=SPREADSHEET_ID,
                    range=f"{SHEET_NAME}!A:D",
                    valueInputOption="RAW",
                    body={"values":[[idinfo["email"], vid, ts, views]]}
                ).execute()
                st.success(f"✅ 조회수: {views:,}회")
                st.success("✅ 스프레드시트에 저장되었습니다!")

    st.subheader("📊 회귀분석 및 예측")
    rows = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!B2:B"
    ).execute().get("values", [])
    ids = sorted({r[0] for r in rows if r})
    if ids:
        sel = st.selectbox("분석할 비디오 ID를 선택하세요", ids)
        if st.button("분석 시작"):
            data = service.spreadsheets().values().get(
                spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!A2:D"
            ).execute().get("values", [])
            pts = []
            for e,v,t,vw in data:
                if v==sel:
                    pts.append((datetime.strptime(t,"%Y-%m-%d %H:%M:%S"), int(vw)))
            if len(pts)<3:
                st.error("데이터가 3개 미만입니다.")
            else:
                pts.sort()
                t0 = pts[0][0]
                x = np.array([(tt-t0).total_seconds()/3600 for tt,_ in pts])
                y = np.array([vv for _,vv in pts])
                a,b,c = np.polyfit(x,y,2)
                st.latex(rf"조회수 = {a:.3f}x² + {b:.3f}x + {c:.3f}")
                roots = np.roots([a,b,c-1_000_000])
                rp = next((r.real for r in roots if np.isreal(r) and r>0), None)
                if rp:
                    pred = t0 + timedelta(hours=rp)
                    st.write(f"🎯 100만회 예상 시점: **{pred}**")
                else:
                    st.write("⚠️ 예측 불가")
                fig,ax = plt.subplots()
                ax.scatter(x,y,label="실측")
                xs = np.linspace(0,x.max()*1.1,200)
                ax.plot(xs, a*xs**2+b*xs+c, label="회귀곡선")
                ax.set_xlabel("시간(시간)")
                ax.set_ylabel("조회수")
                ax.legend()
                st.pyplot(fig)
    else:
        st.info("등록된 영상이 없습니다.")
