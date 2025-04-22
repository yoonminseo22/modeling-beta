import streamlit as st
import google.auth.transport.requests
from google_auth_oauthlib.flow import Flow
from google.oauth2 import id_token
import os
import pathlib

# 페이지 설정
st.set_page_config(page_title="📈 Youtube 조회수 분석기", page_icon="📊", layout="centered")

st.title("📈 Youtube 조회수 분석기")
st.subheader("Google 계정으로 로그인하고, 조회수를 분석하세요!")

# 클라이언트 시크릿 파일 경로
CLIENT_SECRETS_FILE = "client_secret.json"

# Streamlit Cloud에 배포한 후 이 부분에 실제 주소 입력
REDIRECT_URI = "https://yoonminseo22-modeling-beta.streamlit.app"

# OAuth 설정
SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']

flow = Flow.from_client_secrets_file(
    CLIENT_SECRETS_FILE,
    scopes=SCOPES,
    redirect_uri=REDIRECT_URI
)

auth_url, _ = flow.authorization_url(prompt='consent')

# 로그인 안 한 경우
if "credentials" not in st.session_state:
    st.markdown(f"[🔐 Google 계정으로 로그인하기]({auth_url})")

# 로그인 후 redirect 되어 돌아온 경우
query_params = st.experimental_get_query_params()
if "code" in query_params:
    flow.fetch_token(code=query_params["code"][0])
    credentials = flow.credentials
    request = google.auth.transport.requests.Request()
    id_info = id_token.verify_oauth2_token(
        credentials._id_token, request, flow.client_config["client_id"]
    )
    st.session_state["credentials"] = id_info
    st.experimental_rerun()

# 로그인 성공한 경우
if "credentials" in st.session_state:
    st.success("✅ 로그인 완료!")
    st.write(f"👋 안녕하세요, {st.session_state['credentials']['name']} 님!")
    st.write("이제 유튜브 링크를 붙여넣고 조회수를 분석할 수 있어요.")