# app.py
import openai
import streamlit as st
import gspread
import requests
import hashlib
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager as fm, rcParams
from datetime import datetime
import os
from oauth2client.service_account import ServiceAccountCredentials

openai.api_key = st.secrets["openai"]["api_key"]

# 폰트 설정
font_path = os.path.join("fonts", "NanumGothic.ttf")
fm.fontManager.addfont(font_path)
prop = fm.FontProperties(fname=font_path)
font_name = prop.get_name()
rcParams["font.family"] = font_name
plt.rc('axes', unicode_minus=False)

st.set_page_config("📈 유튜브 조회수 분석기", layout="centered")

st.title("📈 유튜브 조회수 분석기")
st.subheader("학생용 로그인/회원가입")


# --- 1) 세션 상태 초기화 ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "user" not in st.session_state:
    st.session_state["user"] = None
if "step" not in st.session_state:
    st.session_state["step"] = 1  # 수업 단계


# 구글 시트 인증
scope = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/drive"]
creds_dict = st.secrets["gcp_service_account"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
gc = gspread.authorize(creds)

yt_conf  = st.secrets["sheets"]["youtube"]  # 조회 기록용 시트
usr_conf = st.secrets["sheets"]["users"]    # 회원DB용 시트
YOUTUBE_API_KEY = st.secrets["youtube"]["api_key"]

yt_wb     = gc.open_by_key(yt_conf["spreadsheet_id"])
yt_sheet  = yt_wb.worksheet(yt_conf["sheet_name"])
usr_wb    = gc.open_by_key(usr_conf["spreadsheet_id"])
usr_sheet = usr_wb.worksheet(usr_conf["sheet_name"])

# 해시 함수
def hash_password(pw: str) -> str:
    if not isinstance(pw, str) or pw == "":
        return ""
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()


# ==== 회원가입 UI ====
def signup_ui():
    st.subheader("회원가입")
    sid = st.text_input("학번", key="signup_sid")
    name = st.text_input("이름", key="signup_name")
    pwd = st.text_input("비밀번호", type="password", key="signup_pwd")
    if st.button("회원가입"):
        if not sid or not name or not pwd:
            st.error("학번, 이름, 비밀번호를 모두 입력해주세요.")
            return
        pw_hash = hash_password(pwd)
        if pw_hash == "":
            st.error("비밀번호 처리에 문제가 발생했습니다.")
            return
        rows = usr_sheet.get_all_records()
        if any(r["학번"] == sid for r in rows):
            st.error("이미 등록된 학번입니다.")
        else:
            usr_sheet.append_row([sid, name, pw_hash])
            st.success(f"{name}님, 회원가입이 완료되었습니다!")

# 로그인 UI
def login_ui():
    st.header("🔐 로그인")
    rows = usr_sheet.get_all_records()
    sid = st.text_input("학번", key="login_sid")
    pwd = st.text_input("비밀번호", type="password", key="login_pwd")

    if st.button("로그인"):
        # 숫자로 비교하고 싶으면:
        try:
            sid_int = int(sid)
        except ValueError:
            st.error("학번은 숫자여야 합니다.")
            return

        # 이미 해시된 비밀번호
        pw_hash = hash_password(pwd)
        # 학번으로 회원 찾기
        user = next((r for r in rows if str(r["학번"]) == sid), None)
        if not user:
            st.error("❌ 등록되지 않은 학번입니다.")
            return

        # 비밀번호 해시 비교
        if user.get("암호(해시)") != pw_hash:
            st.error("❌ 비밀번호가 일치하지 않습니다.")
            return

        # 로그인 성공!
        st.session_state["logged_in"] = True
        st.session_state["user"] = user
        st.success(f"🎉 환영합니다, {user['이름']}님!")
        st.rerun()
        return

# 유튜브 영상 ID 추출
def extract_video_id(url):
    import re
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None

# 조회수 API 호출
def get_video_statistics(video_id):
    import requests
    url = (
        f"https://www.googleapis.com/youtube/v3/videos"
        f"?part=statistics&id={video_id}&key={YOUTUBE_API_KEY}"
    )
    r = requests.get(url)
    st.write("🔗 요청 URL:", url)
    st.write("📣 HTTP Status:", r.status_code)
    try:
        data = r.json()
        st.write("📝 응답 JSON:", data)
    except Exception as e:
        st.write("⚠️ JSON 파싱 오류:", e)
        return None

    items = data.get("items")
    if items:
        stats = items[0]["statistics"]
        return {
            "viewCount": int(stats.get("viewCount", 0)),
            "likeCount": int(stats.get("likeCount", 0)),
            "commentCount": int(stats.get("commentCount", 0)),
        }
    return None

def summarize_discussion(text):
    resp = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role":"system", "content":"당신은 훌륭한 요약가입니다."},
            {"role":"user", "content":f"다음 토의 내용을 짧고 깔끔하게 요약해주세요:\n\n{text}"}
        ],
        temperature=0.3,
        max_tokens=300
    )
    return resp.choices[0].message.content.strip()


def step4_ui():
    st.header("4️⃣ 토의 내용 입력 & 요약하기")

    # 4차시 세션 구분 (예: A조, B조 등)
    session = st.selectbox("조를 선택하세요", ["A조","B조","C조"], key="session")

    # 토의 내용 입력
    raw = st.text_area("토의 내용을 입력하세요", key="discussion_raw", height=200)

    if st.button("요약 & 저장"):
        if not raw.strip():
            st.error("토의 내용을 입력해야 합니다.")
            return
        with st.spinner("GPT에게 요약을 부탁하는 중..."):
            summary = summarize_discussion(raw)
        st.success("요약 완료!")
        st.write("**요약본**")
        st.write(summary)

        # 스프레드시트 기록
        ss = gc.open_by_key(yt_conf["spreadsheet_id"])
        ds = ss.worksheet("토의요약")  # 미리 만들어두세요
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        ds.append_row([session, timestamp, raw, summary])
        st.info("스프레드시트에 저장되었습니다.")



# --- 8) 메인 화면(로그인 후) ---
def main_ui():
    user = st.session_state["user"]
    sid = str(user["학번"]) 
    st.sidebar.success(f"👋 {user['이름']}님, 반갑습니다!")
    st.write("로그인에 성공했습니다! 이곳에서 유튜브 분석 기능을 사용하세요.")
    col1,col2=st.sidebar.columns(2)
    if col1.button('◀ 이전 단계') and st.session_state['step']>1:
        st.session_state['step']-=1
        st.rerun()
    if col2.button('다음 단계 ▶') and st.session_state['step']<3:
        st.session_state['step']+=1
        st.rerun()
    step=st.session_state['step']
    st.info(f"현재  {step}차시 활동 중")

    
    all_records = yt_sheet.get_all_records()
    records = [r for r in all_records if str(r["학번"]) == sid]

    if step==1:
        st.header("1️⃣ 유튜브 조회수 기록하기")
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

    elif step==2:
        st.header("2️⃣ 유튜브 조회수 분석하기")
        if not records:
            st.info("내 기록이 아직 없습니다. 먼저 '1️⃣ 조회수 기록하기'로 기록하세요.")
            return
        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["viewCount"] = df["viewCount"].astype(int)
        x = (df["timestamp"] - df["timestamp"].min()).dt.total_seconds().values
        y = df["viewCount"].values
        coef = np.polyfit(x, y, 2)
        poly = np.poly1d(coef)
        target = 1_000_000
        roots = np.roots([coef[0], coef[1], coef[2] - target])
        a, b, c = coef
        formula = f"y = {a:.3e} x² + {b:.3e} x + {c:.3e}"
        st.markdown(f"**2차 회귀식:**  `{formula}`")
        if st.button('그래프 보기'):
            target = 1_000_000
            roots = np.roots([coef[0], coef[1], coef[2] - target])
            real_roots = [r.real for r in roots if abs(r.imag) < 1e-6]
            if real_roots:
                t_future = max(real_roots)
                dt_future = df["timestamp"].min() + pd.to_timedelta(t_future, unit="s")
                st.write(f"▶️ 조회수 {target:,}회 돌파 예상 시점: **{dt_future}**")

                ts = pd.date_range(df["timestamp"].min(), dt_future, periods=200)
                xs = (ts - df["timestamp"].min()).total_seconds()
                ys = coef[0]*xs**2 + coef[1]*xs + coef[2]

                fig, ax = plt.subplots(figsize=(8,4))
                ax.scatter(df["timestamp"], y, label="실제 조회수")
                ax.plot(ts, ys, color="orange", label="2차 회귀곡선")
                ax.set_xlabel("시간")
                ax.set_ylabel("조회수")
                ax.legend()
                plt.xticks(rotation=45)
                st.pyplot(fig)

                y_pred = poly(x)
                residuals = y - y_pred

                rmse = np.sqrt(np.mean(residuals**2))
                st.markdown(f"**잔차(RMSE):** {rmse:,.0f} 회")

                fig2, ax2 = plt.subplots(figsize=(8,3))
                ax2.hlines(0, df["timestamp"].min(), df["timestamp"].max(), colors="gray", linestyles="dashed")
                ax2.scatter(df["timestamp"], residuals)
                ax2.set_ylabel("잔차 (관측치 - 예측치)")
                ax2.set_xlabel("시간")
                plt.xticks(rotation=45)
                st.pyplot(fig2)
            else:
                st.warning("❗목표 조회수 돌파 시점을 회귀모델로 예측할 수 없습니다.")

    elif step==3:
        records = [r for r in all_records if str(r["학번"]) == sid]
        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["viewCount"]  = df["viewCount"].astype(int)
        x = (df["timestamp"] - df["timestamp"].min()).dt.total_seconds().values
        y = df["viewCount"].values
        coef = np.polyfit(x, y, 2)
        st.header("3️⃣ 광고비 모델 추가하기")
        budget = st.number_input("투입한 광고비를 입력하세요 (원 단위)", step=1000)
        if st.button("모델에 반영"):
            # 예: 조회수 = a * sqrt(budget)  이런 모델을 간단히 시연
            a = coef[0] if len(coef)>0 else 1
            pred = a * np.sqrt(budget)
            st.write(f"예상 추가 조회수: {int(pred):,}회")

    elif step == 4:
        step4_ui()


# === 메인 탭 구조 ===
tab1, tab2 = st.tabs(["로그인", "회원가입"])
with tab1:
    if not st.session_state["logged_in"]:
        login_ui()
    else:
        main_ui()
with tab2:
    if not st.session_state["logged_in"]:
        signup_ui()
    else:
        st.info("이미 로그인된 상태입니다.")

# 1) 세션에 history, chat_input 초기화
if "history" not in st.session_state:
    st.session_state["history"] = []
if "chat_input" not in st.session_state:
    st.session_state["chat_input"] = "새값"

st.sidebar.markdown("## 🗨️ AI 챗봇")
chat_input = st.sidebar.text_input(
    "질문을 입력하세요", key="chat_input"
)

if st.sidebar.button("전송"):
    # 2) API 호출
    messages = [{"role":"system","content":"당신은 친절한 수학 튜터입니다."}]
    # 대화 히스토리도 포함시키려면:
    for role, msg in st.session_state["history"]:
        messages.append({"role":"user" if role=="🧑‍🎓" else "assistant", "content":msg})
    messages.append({"role":"user","content": chat_input})

    res = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages
    )
    answer = res.choices[0].message.content

    # 3) 히스토리에 추가
    st.session_state["history"].append(("🧑‍🎓", chat_input))
    st.session_state["history"].append(("🤖", answer))
    # 4) 입력창 리셋
    st.session_state["chat_input"] = "새값"

# 5) 대화 내용 보여주기
for role, msg in st.session_state["history"]:
    if role == "🧑‍🎓":
        st.sidebar.markdown(f"**{role}:** {msg}")
    else:
        st.sidebar.markdown(f"**{role}:** {msg}")

with st.expander("이전 대화 기록 보기"):
    for turn in st.session_state.history:
        st.markdown(f"**{turn['role']}**: {turn['content']}")