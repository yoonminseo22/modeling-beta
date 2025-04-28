# app.py
import streamlit as st
import gspread
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from hashlib import sha256
from datetime import datetime

st.set_page_config("📈 유튜브 조회수 분석기", layout="centered")

st.title("📈 유튜브 조회수 분석기")
st.subheader("학생용 로그인/회원가입")

# --- 1) 구글 서비스 계정으로 스프레드시트 인증 ---
gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])

# --- 2) 시크릿에서 시트 정보 불러오기 ---
yt_conf  = st.secrets["sheets"]["youtube"]  # 조회 기록용 시트
usr_conf = st.secrets["sheets"]["users"]    # 회원DB용 시트
YOUTUBE_API_KEY = st.secrets["youtube"]["api_key"]

# --- 3) 각각의 워크시트 열기 ---
yt_wb     = gc.open_by_key(yt_conf["spreadsheet_id"])
yt_sheet  = yt_wb.worksheet(yt_conf["sheet_name"])

usr_wb    = gc.open_by_key(usr_conf["spreadsheet_id"])
usr_sheet = usr_wb.worksheet(usr_conf["sheet_name"])

# 해시 함수
def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


# ==== 회원가입 UI ====
def signup_ui():
    st.header("회원가입")
    sid = st.text_input("학번", key="signup_sid")
    pwd = st.text_input("비밀번호", type="password", key="signup_pwd")
    if st.button("회원가입"):
        rows = usr_sheet.get_all_records()
        if any(r["학번"] == sid for r in rows):
            st.error("이미 등록된 학번입니다.")
        else:
            pw_hash = hash_password(pwd)
            usr_sheet.append_row([sid, pw_hash])
            st.success("회원가입이 완료되었습니다!")

# 로그인 UI
def login_ui():
    st.header("로그인")
    sid = st.text_input("학번", key="login_sid")
    pwd = st.text_input("비밀번호", type="password", key="login_pwd")
    if st.button("로그인"):
        rows = usr_sheet.get_all_records()
        target = next((r for r in rows if r["학번"] == sid), None)
        if not target:
            st.error("등록되지 않은 학번입니다.")
        else:
            if hash_password(pwd) == target["암호(해시)"]:
                st.success(f"환영합니다, {sid}님!")
                st.session_state["logged_in"] = sid
            else:
                st.error("비밀번호가 일치하지 않습니다.")

                
# 로그인 완료 후 간단 메시지
if st.session_state.get("logged_in"):
    st.write("🔐 로그인 되었습니다. 유튜브 조회수 분석으로 이동하세요.")


# 유튜브 영상 ID 추출
def extract_video_id(url):
    import re
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None

# 조회수 API 호출
def get_video_statistics(video_id):
    url = (
        f"https://www.googleapis.com/youtube/v3/videos"
        f"?part=statistics&id={video_id}&key={YOUTUBE_API_KEY}"
    )
    r = requests.get(url).json()
    items = r.get("items")
    if items:
        stats = items[0]["statistics"]
        return {
            "viewCount": int(stats.get("viewCount", 0)),
            "likeCount": int(stats.get("likeCount", 0)),
            "commentCount": int(stats.get("commentCount", 0)),
        }
    return None


# === 메인 탭 구조 ===
tab1, tab2 = st.tabs(["로그인", "회원가입"])

with tab2:
    signup_ui()

with tab1:
    if "user" not in st.session_state:
        login_ui()
        st.stop()  # 로그인 전에는 나머지 화면 비활성화
    user = st.session_state["user"]

    st.sidebar.success(f"👋 {user['이름']}님 반갑습니다")

    st.title("📈 유튜브 조회수 기록 / 분석")

    # ---- 유튜브 조회수 기록 ----
    st.header("1️⃣ 조회수 기록하기")
    yt_url = st.text_input("유튜브 링크를 입력하세요")
    if st.button("조회수 기록"):
        vid = extract_video_id(yt_url)
        if not vid:
            st.error("⛔ 유효한 유튜브 링크가 아닙니다.")
        else:
            stats = get_video_statistics(vid)
            if not stats:
                st.error("😢 영상 정보를 불러올 수 없습니다.")
            else:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # ['학번','video_id','timestamp','viewCount','likeCount','commentCount']
                yt_sheet.append_row([
                    user["학번"], vid, timestamp,
                    stats["viewCount"], stats["likeCount"], stats["commentCount"]
                ])
                st.success("✅ 기록 완료")

    # ---- 데이터 불러오기 & 분석 ----
    st.header("2️⃣ 조회수 분석하기")
    records = yt_sheet.get_all_records()
    if not records:
        st.info("아직 기록된 데이터가 없습니다.")
    else:
        df = pd.DataFrame(records)
        # 날짜형 변환
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["viewCount"] = df["viewCount"].astype(int)

        # x: 시간(초 경과), y: 조회수
        x = (df["timestamp"] - df["timestamp"].min()).dt.total_seconds().values
        y = df["viewCount"].values

        # 2차 회귀
        coef = np.polyfit(x, y, 2)
        poly = np.poly1d(coef)

        # 100만 돌파 예상 시점
        # coef[0]*t^2 + coef[1]*t + coef[2] = 1e6  를 풀기
        roots = np.roots([coef[0], coef[1], coef[2] - 1e6])
        # 실수 중 가장 큰 것
        t_future = max(r.real for r in roots if abs(r.imag) < 1e-6)
        dt_future = df["timestamp"].min() + pd.to_timedelta(t_future, unit="s")

        st.write(f"▶️ 조회수 1,000,000회 돌파 예상 시점: **{dt_future}**")

        # 시각화
        fig, ax = plt.subplots(figsize=(8,4))
        ax.scatter(df["timestamp"], y, label="실제 조회수")
        ts = pd.date_range(df["timestamp"].min(), dt_future, periods=200)
        xs = (ts - df["timestamp"].min()).total_seconds()
        ax.plot(ts, poly(xs), color="orange", label="2차 회귀곡선")
        ax.set_xlabel("시간")
        ax.set_ylabel("조회수")
        ax.legend()
        plt.xticks(rotation=45)
        st.pyplot(fig)

    # ---- 광고비 모델 추가 (옵션) ----
    st.header("3️⃣ 광고비 모델 추가하기")
    budget = st.number_input("투입한 광고비를 입력하세요 (원 단위)", step=1000)
    if st.button("모델에 반영"):
        # 예: 조회수 = a * sqrt(budget)  이런 모델을 간단히 시연
        a = coef[0] if len(coef)>0 else 1
        pred = a * np.sqrt(budget)
        st.write(f"예상 추가 조회수: {int(pred):,}회")