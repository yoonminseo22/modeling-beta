import streamlit as st
import gspread
import hashlib

# 1) 시트 연결
gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
SHEET_KEY = st.secrets["sheets"]["students_sheet_key"]
sheet = gc.open_by_key(SHEET_KEY).sheet1

# 2) 비밀번호 해시 함수
def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

# 3) 회원가입 UI
def signup_ui():
    st.subheader("🔐 회원가입")
    with st.form("signup_form"):
        sid  = st.text_input("학번")
        name = st.text_input("이름")
        pw   = st.text_input("비밀번호", type="password")
        pw2  = st.text_input("비밀번호 확인", type="password")
        ok = st.form_submit_button("가입하기")
    if ok:
        if not (sid and name and pw):
            st.error("모두 입력해주세요.")
        elif pw != pw2:
            st.error("비밀번호가 다릅니다.")
        else:
            rows = sheet.get_all_records()
            if any(r["학번"] == sid for r in rows):
                st.error("이미 가입된 학번입니다.")
            else:
                sheet.append_row([sid, name, hash_pw(pw)])
                st.success("가입 완료! 로그인하세요.")

# 4) 로그인 UI
def login_ui():
    st.subheader("🔑 로그인")
    with st.form("login_form"):
        sid = st.text_input("학번")
        pw  = st.text_input("비밀번호", type="password")
        ok = st.form_submit_button("로그인")
    if ok:
        rows = sheet.get_all_records()
        for r in rows:
            if r["학번"] == sid and r["암호(해시)"] == hash_pw(pw):
                st.session_state["sid"]  = sid
                st.session_state["name"] = r["이름"]
                st.success(f"{r['이름']}님, 환영합니다!")
                return
        st.error("학번 또는 비밀번호가 틀렸습니다.")

# 5) 메인 로직
st.title("🔢 유튜브 분석기 - 학생용")

if "sid" not in st.session_state:
    tab1, tab2 = st.tabs(["로그인", "회원가입"])
    with tab1: login_ui()
    with tab2: signup_ui()
    st.stop()

# 로그인 완료 화면
st.write(f"👋 안녕하세요, **{st.session_state['name']}**님!")

# 여기에 조회수 분석 UI 넣기
url = st.text_input("유튜브 URL을 입력하세요")
if st.button("분석 시작"):
    st.write("분석 중…")  # 분석 로직 구현

# 로그아웃
if st.button("🔓 로그아웃"):
    del st.session_state["sid"]
    del st.session_state["name"]
    st.experimental_rerun()