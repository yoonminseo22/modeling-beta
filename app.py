import streamlit as st
import pyrebase

st.set_page_config(page_title="YouTube 조회수 분석기", layout="wide")
st.title("📈 YouTube 조회수 분석기")

st.write("구글 로그인 후, 유튜브 링크를 붙여넣고 회귀분석 결과를 확인하세요.")

# 🔐 1. Firebase 설정 정보
firebaseConfig = {
    "apiKey": "AIzaSyA7-9mz0poBpO74-Pqsc_HzeCuS8KKUid4",
    "authDomain": "modeling-beta.firebaseapp.com",
    "projectId": "modeling-beta",
    "storageBucket": "modeling-beta.firebasestorage.app",
    "messagingSenderId": "849291035256",
    "appId": "1:849291035256:web:658b88d471fff208c4238d",
    "measurementId": "G-4VJSKE7ZXT"
}

firebase = pyrebase.initialize_app(firebaseConfig)
auth = firebase.auth()

# 🧾 2. 로그인 UI
st.set_page_config(page_title="YouTube 분석기 로그인")
st.title("🔐 YouTube 분석기 - 로그인")

email = st.text_input("이메일", key="email")
password = st.text_input("비밀번호", type="password", key="password")

# 🟢 로그인
if st.button("로그인"):
    try:
        user = auth.sign_in_with_email_and_password(email, password)
        st.success("✅ 로그인 성공!")
        st.session_state["user"] = user
    except:
        st.error("❌ 이메일 또는 비밀번호를 확인해주세요.")

# 🔵 회원가입
if st.button("회원가입"):
    try:
        auth.create_user_with_email_and_password(email, password)
        st.success("🎉 회원가입 성공! 이제 로그인하세요.")
    except:
        st.error("⚠ 이미 존재하거나 비밀번호가 약합니다.")