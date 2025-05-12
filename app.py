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
            df["timestamp"] = pd.to_datetime(df["timestamp"], infer_datetime_format=True)
            df["viewCount"] = df["viewCount"].astype(int)
            df = df.sort_values("timestamp").reset_index(drop=True)

            base = df["timestamp"].min()
            x_all = (df["timestamp"] - base).dt.total_seconds().values
            y_all = df["viewCount"].values

            # 2) 가능한 3점 조합 중 'a>0' & f' >0 on interval' 조건 만족 조합 찾기
            candidates = []
            for i, j, k in combinations(range(len(df)), 3):
                xi = x_all[[i, j, k]]
                yi = y_all[[i, j, k]]
                a_coef, b_coef, _ = np.polyfit(xi, yi, 2)

                # concave up
                if a_coef <= 0:
                    continue

                # derivative positive at i and k
                deriv_i = 2 * a_coef * xi[0] + b_coef
                deriv_k = 2 * a_coef * xi[2] + b_coef
                if deriv_i <= 0 or deriv_k <= 0:
                    continue

                # fit error
                y_pred = a_coef*xi**2 + b_coef*xi + _
                mse = np.mean((yi - y_pred)**2)
                candidates.append((mse, (i, j, k)))

            if candidates:
                # best triple by lowest MSE
                _, (i1, i2, i3) = min(candidates, key=lambda x: x[0])
                synthetic = None
                sel_idx = [i1, i2, i3]
            else:
                # fallback: last two + synthetic
                i1, i2 = len(df)-2, len(df)-1
                dt = x_all[i2] - x_all[i1]
                slope_last = (y_all[i2] - y_all[i1]) / dt
                # amplify slope to enforce accel>0
                slope3 = slope_last * 1.2
                t3 = x_all[i2] + dt
                y3 = y_all[i2] + slope3 * dt
                ts3 = base + pd.to_timedelta(t3, unit="s")
                synthetic = {"timestamp": ts3, "viewCount": int(y3)}
                sel_idx = [i1, i2, "synthetic"]

            # 3) 선택된 점 DataFrame
            pts = []
            for idx in sel_idx:
                if idx == "synthetic":
                    pts.append(synthetic)
                else:
                    pts.append({
                        "timestamp": df.loc[idx, "timestamp"],
                        "viewCount": int(df.loc[idx, "viewCount"])
                    })
            sel_df = pd.DataFrame(pts)

            # 4) regression
            x_sel = (sel_df["timestamp"] - base).dt.total_seconds().values
            y_sel = sel_df["viewCount"].values
            a, b, c = np.polyfit(x_sel, y_sel, 2)

            st.markdown(f"**회귀식:** `y = {a:.3e}·x² + {b:.3e}·x + {c:.3e}`")

            # 5) 예측
            roots = np.roots([a, b, c - 1_000_000])
            rr = [r.real for r in roots if abs(r.imag) < 1e-6]
            if rr:
                t_pred = max(rr)
                dt_pred = base + pd.to_timedelta(t_pred, unit="s")
                st.write(f"▶️ 조회수 **1,000,000회** 돌파 예상 시점: **{dt_pred}**")

            # 6) 시각화
            fig, ax = plt.subplots(figsize=(8,4))
            # 전체 데이터
            ax.scatter(df["timestamp"], y_all, color="skyblue", alpha=0.6, s=20, label="전체 실제 데이터")
            # 포물선 곡선
            ts_curve = np.linspace(x_all.min(), x_all.max(), 300)
            ax.plot(
                base + pd.to_timedelta(ts_curve, unit="s"),
                a*ts_curve**2 + b*ts_curve + c,
                color="orange", lw=2, label="2차 회귀곡선 (전체)"
            )
            # 실제 선택 점
            real_idxs = [idx for idx in sel_idx if idx != "synthetic"]
            ax.scatter(df.loc[real_idxs, "timestamp"], df.loc[real_idxs, "viewCount"],
                    color="green", s=80, label="선택된 실제 점")
            # synthetic 점
            if synthetic:
                ax.scatter(synthetic["timestamp"], synthetic["viewCount"],
                        color="red", s=100, label="Synthetic 점")

            # x축 전체
            ax.set_xlim(df["timestamp"].min(), df["timestamp"].max())
            # y축
            y_min = min(y_all.min(), y_sel.min()) * 0.9
            y_max = max(y_all.max(), y_sel.max()) * 1.1
            ax.set_ylim(y_min, y_max)

            ax.set_xlabel("시간")
            ax.set_ylabel("조회수")
            ax.legend()
            plt.xticks(rotation=45)
            st.pyplot(fig)

    elif step==3:
        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["viewCount"]  = df["viewCount"].astype(int)
        df = df.sort_values("timestamp").reset_index(drop=True)

        base = df["timestamp"].min()
        x = (df["timestamp"] - base).dt.total_seconds().values
        y = df["viewCount"].values

        # 시간 기반 2차 회귀 계수
        a, b, c = np.polyfit(x, y, 2)
        time_poly = np.poly1d([a, b, c])

        st.markdown(f"**시간 모델:**  $y_\\mathrm{{time}}=\\,{a:.3e}x^2 \\,+\\,{b:.3e}x\\,+\\,{c:.3e}$")

        # 2) 광고비 입력
        budget = st.number_input("투입할 광고비를 입력하세요 (원)", min_value=0, step=1000, value=1000000)

        # 광고비 효과 계수(γ)는 사용자 정의 혹은 과거 데이터로 회귀해서 추정
        # 여기서는 간단히 γ=0.5 로 설정 (원당 √예산 0.5회 증가)
        gamma = st.slider("광고비 효과계수 γ 설정", min_value=0.0, max_value=5.0, value=0.5)

        # 3) 통합 예측
        # - 현재 시점(마지막 데이터)에서의 시간 기반 예측
        x_now = x[-1]
        y_time_now = time_poly(x_now)

        # - 광고비 효과
        y_ad = gamma * np.sqrt(budget)

        # - 합산
        y_total = int(y_time_now + y_ad)

        st.write(f"▶️ 시간 모델 예측 조회수: **{int(y_time_now):,}회**")
        st.write(f"▶️ 광고비 효과 조회수: **{int(y_ad):,}회**")
        st.write(f"▶️ **통합 예측 조회수:** **{y_total:,}회**")

        # 4) 시각화
        fig, ax = plt.subplots(figsize=(8,4))
        # 실제 전체 데이터
        ax.scatter(df["timestamp"], y, color="skyblue", alpha=0.6, s=20, label="실제 조회수")

        # 시간 모델 곡선 (전체 구간)
        ts_curve = np.linspace(0, x_now, 200)
        ax.plot(base + pd.to_timedelta(ts_curve, unit="s"),
                time_poly(ts_curve),
                color="orange", lw=2, label="시간 모델 곡선")

        # 현재 시점 포인트
        t_now = base + pd.to_timedelta(x_now, unit="s")
        ax.scatter(t_now, y_time_now, color="green", s=80, label="시간 모델 예측점")

        # 광고비 효과 후 점
        ax.scatter(t_now, y_time_now + y_ad, color="red", s=100, label="광고비 적용 예측점")

        # 축 설정
        ax.set_xlim(df["timestamp"].min(), df["timestamp"].max() + pd.Timedelta(hours=1))
        ymin = min(y.min(), time_poly(x_now)) * 0.9
        ymax = (time_poly(x_now) + gamma*np.sqrt(budget)) * 1.1
        ax.set_ylim(ymin, ymax)

        ax.set_xlabel("시간")
        ax.set_ylabel("조회수")
        ax.legend()
        plt.xticks(rotation=45)
        st.pyplot(fig)

        if st.button("적합도 평가"):
            # 1) MAE, RMSE 계산
            y_pred_full = time_poly(x) + gamma * np.sqrt(budget)
            mae  = np.mean(np.abs(y - y_pred_full))
            rmse = np.sqrt(np.mean((y - y_pred_full)**2))
            st.write(f"**평균절대오차(MAE):** {mae:,.2f}")

        # ── 0) 학생 의견 입력란 추가 ──
        st.subheader("💬 적합도 평가 의견 남기기")
        session = st.selectbox("조를 선택하세요", ["A조","B조","C조"], key="session")

        opinion_input = st.text_area(
            "모델 예측 결과와 실제 조회수의 차이에 대해 느낀 점이나 개선할 점을 적어주세요.",
            height=120,
            placeholder="예) 저는 예측 모델이 너무 보수적이라고 느꼈습니다…"
        )

        # 하나의 버튼으로 제출 → 요약 → 시트 저장
        if st.button("의견 제출 및 요약 저장"):
            if not opinion_input.strip():
                st.warning("먼저 의견을 입력해 주세요.")
            else:
                # 1) GPT 요약
                prompt = (
                    "다음 학생 의견을 간결하게 요약해 주세요:\n\n"
                    f"{opinion_input}"
                )
                resp = openai.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "당신은 수업 토의 내용을 간결히 요약하는 AI입니다."},
                        {"role": "user",   "content": prompt}
                    ]
                )
                summary = resp.choices[0].message.content
                st.markdown("**요약:**  " + summary)

                # 2) 스프레드시트에 기록
                ss = gc.open_by_key(yt_conf["spreadsheet_id"])
                ws = ss.worksheet("적합도평가")  # 시트 이름 확인
                timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                # [세션, 타임스탬프, 원문 의견, 요약]
                ws.append_row([session, timestamp, opinion_input, summary])

                st.success("의견과 요약이 시트에 저장되었습니다!")

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