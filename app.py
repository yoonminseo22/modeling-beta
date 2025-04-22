import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from googleapiclient.discovery import build

st.set_page_config(page_title="📈 유튜브 조회수 분석기", layout="centered")
st.title("📈 유튜브 조회수 분석기")
st.subheader("Google 계정으로 로그인하고, 조회수를 분석하세요!")


client_id = st.secrets["google_oauth"]["client_id"]
client_secret = st.secrets["google_oauth"]["client_secret"]
redirect_uri = "https://modeling-beta-1.streamlit.app"

SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/spreadsheets",
    "openid"
]

flow = Flow.from_client_config(
    {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri]
        }
    },
    scopes=SCOPES,
    redirect_uri=redirect_uri
)

auth_url, _ = flow.authorization_url(prompt="consent")
query = st.query_params

# Step 1: 최초 로그인 버튼
if "credentials" not in st.session_state and "code" not in query and "code_waiting" not in st.session_state:
    st.markdown(f"[🔐 Google 계정으로 로그인하기]({auth_url})")

# Step 2: code 받으면 query param 초기화 후 세션에 저장
if "code" in query and "code_used" not in st.session_state:
    st.session_state["code_waiting"] = query["code"][0]
    st.experimental_set_query_params()
    st.rerun()

# Step 3: code 기반 인증 (한 번만 실행)
if "code_waiting" in st.session_state and "code_used" not in st.session_state:
    code = st.session_state["code_waiting"]
    st.session_state["code_used"] = code
    try:
        flow.fetch_token(code=code)
        credentials = flow.credentials
        request = Request()
        id_info = id_token.verify_oauth2_token(
            credentials.id_token,
            request,
            client_id
        )
        st.session_state["credentials"] = credentials
        st.session_state["user_info"] = id_info
        st.rerun()
    except Exception as e:
        st.error(f"❌ 인증 실패: {e}")

# Step 4: 인증 완료된 사용자
if "credentials" in st.session_state:
    creds = st.session_state["credentials"]
    user = st.session_state["user_info"]
    st.success(f"👋 안녕하세요, {user['name']} 님!")
    st.write("📧 이메일:", user["email"])

    SPREADSHEET_ID = "11WkROAZtU8bKo1ezzuXiNigbdFyB5rqYPr5Lyd1ve24"
    SHEET_NAME = "Sheet1"

    service = build("sheets", "v4", credentials=creds)

    st.subheader("✅ 유튜브 링크를 입력하세요")
    link = st.text_input("🔗 유튜브 링크")
    views = st.number_input("👁 조회수", min_value=0)

    if st.button("📩 시트에 저장"):
        try:
            service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A1",
                valueInputOption="RAW",
                body={"values": [[user["email"], link, views]]}
            ).execute()
            st.success("✅ 저장 완료!")
        except Exception as e:
            st.error(f"❌ 저장 실패: {e}")
