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
from itertools import combinations

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
    if col2.button('다음 단계 ▶') and st.session_state['step']<4:
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
        # 그래프 보기 버튼
        if st.button("그래프 보기"):
        # (1) 전처리
            df = pd.DataFrame(records)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df["viewCount"] = df["viewCount"].astype(int)
            df = df.sort_values("timestamp").reset_index(drop=True)

            base = df["timestamp"].min()
            x_all = (df["timestamp"] - base).dt.total_seconds().values
            y_all = df["viewCount"].values

            # 최소 3점 이상인지 체크
            if len(df) < 3:
                st.error("데이터가 3개 미만이면 2차 회귀가 불가능합니다.")
                st.stop()

            # 2) 마지막 세 실제 점
            t0, t1, t2 = x_all[-3], x_all[-2], x_all[-1]
            y0, y1, y2 = y_all[-3], y_all[-2], y_all[-1]
            dt = t1 - t0  # 마지막 두 구간이 같은 간격이라 가정

            # 3) 두 구간의 증가율(1차미분)과 가속도(2차미분) 계산
            s1 = (y1 - y0) / dt
            s2 = (y2 - y1) / dt
            accel = (s2 - s1) / dt

            # 4) synthetic 점 생성: 동일한 dt 간격을 유지하며 가속도 일정
            dt3 = dt
            s3 = s2 + accel * dt3
            t3 = t2 + dt3
            y3 = y2 + s3 * dt3
            ts3 = base + pd.to_timedelta(t3, unit="s")

            # 5) 회귀에 사용할 세 점 (t1, t2, synthetic)
            sel_times = [base + pd.to_timedelta(t1, unit="s"),
                        base + pd.to_timedelta(t2, unit="s"),
                        ts3]
            sel_vals  = [y1, y2, int(y3)]
            x_sel = np.array([(t - base).total_seconds() for t in sel_times])
            y_sel = np.array(sel_vals)

            # 6) 2차 회귀 수행
            a, b, c = np.polyfit(x_sel, y_sel, 2)
            st.markdown(f"**회귀식:** `y = {a:.3e}·x² + {b:.3e}·x + {c:.3e}`")

            # 7) 예측 (1,000,000회 돌파)
            roots = np.roots([a, b, c - 1_000_000])
            real_roots = [r.real for r in roots if abs(r.imag) < 1e-6]
            if real_roots:
                t_pred = max(real_roots)
                dt_pred = base + pd.to_timedelta(t_pred, unit="s")
                st.write(f"▶️ 조회수 **1,000,000회** 돌파 예상 시점: **{dt_pred}**")

            # (7) 그래프 그리기
            fig, ax = plt.subplots(figsize=(8,4))

            # 전체 실제 데이터
            ax.scatter(df["timestamp"], y_all, alpha=0.5, label="실제 조회수")

            # 포물선 회귀곡선: x_sel 범위만 사용
            ts_curve = np.linspace(x_sel.min(), x_sel.max(), 200)
            ax.plot(
                base + pd.to_timedelta(ts_curve, unit="s"),
                a*ts_curve**2 + b*ts_curve + c,
                color="orange", label="2차 회귀곡선"
            )

            # 선택된 실제 점 (초록)
            ax.scatter(sel_times[:2], sel_vals[:2],
                    color="green", s=40, label="선택된 실제 점")
            # 합성된 점 (빨강)
            ax.scatter(ts3, int(y3),
                    color="red", s=40, label="Synthetic 점")

            ax.set_xlabel("시간")
            ax.set_ylabel("조회수")

            # (a) y축 범위를 실제 조회수 주변으로 한정
            y_min = min(y_all.min(), y_sel.min()) * 0.9
            y_max = max(y_all.max(), y_sel.max()) * 1.1
            ax.set_ylim(y_min, y_max)

            ax.legend()
            plt.xticks(rotation=45)
            st.pyplot(fig)

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

    elif step==4:
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

if "history" not in st.session_state:
    st.session_state["history"] = []

st.sidebar.markdown("## 🗨️ AI 챗봇")
with st.sidebar.form("chat_form", clear_on_submit=True):
    chat_input = st.text_input("질문을 입력하세요", key="chat_input")
    submitted = st.form_submit_button("전송")

if submitted:
    # 2) API 호출
    messages = [{"role":"system","content":"당신은 친절한 수학 튜터입니다."}]
    # 대화 히스토리도 포함시키려면:
    for role, msg in st.session_state["history"]:
        messages.append({
                "role":"user" if role=="🧑‍🎓" else "assistant", 
                "content":msg
        })
    messages.append({"role":"user","content": chat_input})

    res = openai.chat.completions.create(
        model="gpt-3.5-turbo", messages=messages
    )
    answer = res.choices[0].message.content

    # 3) 히스토리에 추가
    st.session_state["history"].append(("🧑‍🎓", chat_input))
    st.session_state["history"].append(("🤖", answer))

    # 5) 대화 내용 보여주기
    if st.session_state["history"]:
        for role, msg in st.session_state["history"][-1:]:
            st.sidebar.markdown(f"**{role}:** {msg}")

    with st.expander("이전 대화 기록 보기"):
        if len(st.session_state["history"]) > 1:
            for role, msg in st.session_state["history"][:-1]:
                st.markdown(f"**{role}:** {msg}")
        else:
            st.markdown("이전 대화 내역이 없습니다.")