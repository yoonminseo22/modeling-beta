import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from googleapiclient.discovery import build

st.set_page_config(page_title="📈 유튜브 조회수 분석기", layout="centered")
st.title("📈 유튜브 조회수 분석기")
st.subheader("Google 계정으로 로그인하고, 조회수를 분석하세요!")

client_id     = st.secrets["google_oauth"]["client_id"]
client_secret = st.secrets["google_oauth"]["client_secret"]
redirect_uri  = "https://modeling-beta-1.streamlit.app"

SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/spreadsheets",
    "openid"
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

# Flow는 세션에 단 한 번만 생성
if "flow" not in st.session_state:
    st.session_state["flow"] = Flow.from_client_config(
        flow_config, scopes=SCOPES, redirect_uri=redirect_uri
    )
flow = st.session_state["flow"]

# 아직 인증 안 된 상태
if "credentials" not in st.session_state:
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent"
    )
    st.markdown(f"[🔐 Google 계정으로 로그인하기]({auth_url})")

    # 리디렉션 후 ?code= 파라미터 처리
    params = st.experimental_get_query_params()
    if "code" in params:
        code = params["code"][0]
        try:
            flow.fetch_token(code=code)
            st.session_state["credentials"] = flow.credentials

            # URL에 남은 code 파라미터 삭제
            st.experimental_set_query_params()

            # JS로 즉시 페이지 새로고침
            st.markdown(
                """
                <script>
                    // 쿼리 파라미터 없이 현재 페이지로 강제 이동
                    const cleanUrl = window.location.origin + window.location.pathname;
                    window.location.replace(cleanUrl);
                </script>
                """,
                unsafe_allow_html=True
            )
            st.stop()

        except Exception as e:
            st.error(f"❌ 인증 실패: {e}")

# 인증된 상태: 유튜브 링크 폼을 보여줌
else:
    creds   = st.session_state["credentials"]
    request = Request()
    idinfo  = id_token.verify_oauth2_token(creds.id_token, request, client_id)

    st.success(f"👋 안녕하세요, {idinfo['name']} 님!")
    st.write("📧 이메일:", idinfo["email"])

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
