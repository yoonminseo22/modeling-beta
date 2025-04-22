import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from google.oauth2 import id_token
from googleapiclient.discovery import build
import requests
import os

st.set_page_config(page_title="📈 유튜브 조회수 분석기", layout="centered")
st.title("📈 유튜브 조회수 분석기")

CLIENT_SECRET = {
    "web": {
        client_id = st.secrets["google_oauth"]["client_id"]
        client_secret = st.secrets["google_oauth"]["client_secret"]
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "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",
        "redirect_uris": ["https://modeling-beta-1.streamlit.app/"]
    }
}

REDIRECT_URI = "https://modeling-beta-1.streamlit.app"

# 1️⃣ 인증 흐름 시작
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/spreadsheets"]

flow = Flow.from_client_config(
    CLIENT_SECRET,
    scopes=SCOPES,
    redirect_uri=REDIRECT_URI
)

auth_url, _ = flow.authorization_url(prompt="consent")

query_params = st.query_params

# 2️⃣ 로그인하지 않은 경우
if "credentials" not in st.session_state and "code" not in query_params:
    st.markdown(f"[🔐 Google 계정으로 로그인하기]({auth_url})")

# 3️⃣ 로그인 후 돌아온 경우
if "code" in query_params and "credentials" not in st.session_state:
    try:
        flow.fetch_token(code=query_params["code"][0])
        credentials = flow.credentials
        request = Request()
        id_info = id_token.verify_oauth2_token(
            credentials.id_token, request, CLIENT_SECRET["web"]["client_id"]
        )
        st.session_state["credentials"] = credentials
        st.session_state["user_info"] = id_info
        st.experimental_rerun()
    except Exception as e:
        st.error(f"❌ 인증 오류: {e}")

# 4️⃣ 로그인 완료 시 기능 제공
if "credentials" in st.session_state:
    creds = st.session_state["credentials"]
    user = st.session_state["user_info"]
    st.success(f"👋 안녕하세요, {user['name']} 님!")
    st.write("📧", user["email"])

    # 구글 시트 쓰기 기능
    SPREADSHEET_ID = "11WkROAZtU8bKo1ezzuXiNigbdFyB5rqYPr5Lyd1ve24"
    SHEET_NAME = "Sheet1"  # 시트 탭 이름

    service = build("sheets", "v4", credentials=creds)

    st.subheader("✅ 유튜브 링크를 입력하세요")
    link = st.text_input("🔗 유튜브 링크")
    조회수 = st.number_input("👁 조회수", min_value=0)

    if st.button("시트에 저장"):
        try:
            sheet = service.spreadsheets().values().append(
                spreadsheetId=SPREADSHEET_ID,
                range=f"{SHEET_NAME}!A1",
                valueInputOption="RAW",
                body={"values": [[user["email"], link, 조회수]]}
            ).execute()
            st.success("✅ 시트에 저장 완료!")
        except Exception as e:
            st.error(f"❌ 저장 실패: {e}")

