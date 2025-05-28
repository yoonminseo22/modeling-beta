# app.py
import openai
import streamlit as st
import gspread
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib import font_manager as fm, rcParams
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
import os, time, json, math, textwrap, hashlib, requests
from oauth2client.service_account import ServiceAccountCredentials
from itertools import combinations

# 기본 설정
openai.api_key = st.secrets["openai"]["api_key"]
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

yt_id     = yt_conf["spreadsheet_id"]
yt_name  = yt_conf["sheet_name"]
usr_id    = usr_conf["spreadsheet_id"]
usr_name = usr_conf["sheet_name"]

# ── Sheets 도우미 (429 백오프) ───────────────────────────────────────────────

def safe_append(ws, row: List[Any]):
    """429 대응 append_row."""
    for wait in (0, 2, 4, 8, 16):
        try:
            ws.append_row(row, value_input_option="USER_ENTERED")
            return
        except gspread.exceptions.APIError as e:
            if e.response.status == 429:
                time.sleep(wait)
            else:
                raise
    st.error("❌ Google Sheets 쿼터 초과 – 잠시 후 다시 시도하세요.")

@st.cache_data(ttl=300, show_spinner=False)
def load_sheet_records(_spreadsheet_id: str, _sheet_name: str) -> list:
    """
    구글 스프레드시트의 모든 레코드를 불러와 5분간 캐싱합니다.
    429 에러 발생 시 최대 5번까지 지수 백오프를 시도합니다.
    """
    for wait in (0, 1, 2, 4, 8):
        try:
            ws = gc.open_by_key(_spreadsheet_id).worksheet(_sheet_name)
            return ws.get_all_records()
        except gspread.exceptions.APIError as e:
            if getattr(e, 'response', None) and e.response.status == 429:
                time.sleep(wait)
            else:
                raise
    return []

VIDEO_CRITERIA = {"max_views":1_000_000, "min_subs":100_000, "max_subs":3_000_000}

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_video_details(vid: str) -> Dict[str,Any] | None:
    url = ("https://www.googleapis.com/youtube/v3/videos"
           f"?part=snippet,statistics&id={vid}&key={YOUTUBE_API_KEY}")
    data = requests.get(url).json()
    if not data.get("items"):
        return None
    item = data["items"][0]
    stats = item["statistics"]
    snippet = item["snippet"]
    # 채널 구독자
    chan = requests.get("https://www.googleapis.com/youtube/v3/channels"
                        f"?part=statistics&id={snippet['channelId']}&key={YOUTUBE_API_KEY}").json()
    subs = int(chan["items"][0]["statistics"].get("subscriberCount",0))
    return {
        "title" : snippet["title"],
        "pub"   : snippet["publishedAt"][:10],
        "views" : int(stats.get("viewCount",0)),
        "subs"  : subs,
    }

def extract_video_id(url:str):
    import re
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url)
    return m.group(1) if m else None

# ── 공통 UI 컴포넌트 ────────────────────────────────────────────────────────

def step_header(title:str, goal:str, qs:List[str]):
    st.markdown(f"### {title}")
    st.info(f"**차시 목표** – {goal}")
    with st.expander("💡 핵심 발문"):
        st.markdown("\n".join([f"- {q}" for q in qs]))

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
        usr_rows = load_sheet_records(usr_id, usr_name)
        if any(r["학번"] == sid for r in usr_rows):
            st.error("이미 등록된 학번입니다.")
        else:
            sid_text=f"'{sid}"
            ws = gc.open_by_key(usr_id).worksheet(usr_name)
            safe_append(ws, [sid_text, name, pw_hash])

            st.success(f"{name}님, 회원가입이 완료되었습니다!")

# 로그인 UI
def login_ui():
    st.header("🔐 로그인")
    usr_rows = load_sheet_records(usr_id, usr_name)
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
        user = next((r for r in usr_rows if int(r["학번"]) == sid_int), None)
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
    st.info(f"현재  {step}번째 활동 중")

    ss_user = gc.open_by_key(usr_id)
    ss_yt   = gc.open_by_key(yt_id)
    st.write("▶ user spreadsheet title:", ss_user.title)
    st.write("▶ yt   spreadsheet title:", ss_yt.title)
    st.write("▶ Database-beta 스프레드시트의 시트들:", 
             [ws.title for ws in ss_user.worksheets()])
    yt_rows = load_sheet_records(yt_id, yt_name)
    records = [r for r in yt_rows if str(r.get('학번','')) == sid]
    yt_ws = gc.open_by_key(yt_id).worksheet(yt_name)
    usr_rows = load_sheet_records(usr_id, usr_name)
    st.write("▶ usr_id      :", usr_id)
    st.write("▶ usr_name    :", usr_name)
    st.write("▶ yt_id       :", yt_id)
    st.write("▶ yt_name     :", yt_name)
    st.write("▶ user_rows 컬럼:", pd.DataFrame(usr_rows).columns.tolist())
    st.write("▶ yt_rows 컬럼:", pd.DataFrame(yt_rows).columns.tolist())
    st.write("▶ records 컬럼:", pd.DataFrame(records).columns.tolist())

    if records:
        df = pd.DataFrame(records)
        df.columns = df.columns.str.strip().str.lower()
        df['timestamp'] = (
            df['timestamp']
            .astype(str)
            .str.replace(r'\s*-\s*','-',regex=True)
            .str.replace(r'\s+',' ',regex=True)
            .str.strip()
        )
        df['timestamp'] = pd.to_datetime(df['timestamp'], errors='raise')
        df['viewcount'] = df['viewcount'].astype(int)
        df = df.sort_values('timestamp').reset_index(drop=True)

        base = df['timestamp'].min()
        x = (df['timestamp'] - base).dt.total_seconds().values
        y = df['viewcount'].values
    else:
        df = None


    if step==1:
        step_header("1️⃣ 유튜브 조회수 기록하기", "실생활 데이터로 이차함수 회귀 분석 시작하기",
                    ["회귀분석이란 무엇일까?", "왜 직선이 아닌 곡선으로 예측을 할까?", "어떤 조건으로 영상을 선택해야 할까?"])
        yt_url = st.text_input("유튜브 링크를 입력하세요")
        if st.button("조건 검증 및 조회수 기록"):
            vid = extract_video_id(yt_url)
            if not vid:
                st.error("⛔ 유효한 유튜브 링크가 아닙니다."); return
            info = fetch_video_details(vid)
            if not info:
                st.error("영상 정보를 가져올 수 없습니다."); return
            valid = (info['views']<VIDEO_CRITERIA['max_views'] and
                      VIDEO_CRITERIA['min_subs']<=info['subs']<=VIDEO_CRITERIA['max_subs'])
            st.write(info)
            if not valid:
                st.warning("조건을 만족하지 않습니다. 다른 영상을 선택하세요."); return
            # ['학번','video_id','timestamp','viewCount','likeCount','commentCount']
            stats = {k:info[k] for k in ('views',)}  # views만 사용
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            safe_append(yt_ws, [sid, vid, ts, stats['views']])
            st.success("✅ 기록 완료")

    elif step==2:
        step_header("2️⃣-1️⃣ 유튜브 조회수 이차 회귀 분석하기",
                    "선택한 데이터로 모델 적합 및 100만 예측하기",
                    ["이차함수의 a, b, c의 값은 그래프에 어떤 영향을 줄까?", "모델이 잘 맞는지 어떻게 판단할까?", "정말 이차함수의 그래프가 데이터 경향을 잘 설명해줄까?"])
        if not records:
            st.info("내 기록이 아직 없습니다. 먼저 '1️⃣ 조회수 기록하기'로 기록하세요.")
            return
        
        df = pd.DataFrame(records)
        # 2) 컬럼명 모두 소문자·공백 제거
        df.columns = (
            df.columns
            .str.strip()           # 앞뒤 공백 제거
            .str.lower()           # 모두 소문자로
        )

        # 이제 df.columns 를 찍어보면:
        # ['학번','video_id','timestamp','viewcount','likecount','commentcount']

        # 그래프 보기 버튼
        if st.button("회귀 분석하기"):
            # 최적 세 점 선택
            candidates = []
            for i, j, k in combinations(range(len(df)), 3):
                xi, yi = x[[i, j, k]], y[[i, j, k]]
                a, b, c = np.polyfit(xi, yi, 2)
                if a <= 0 or (2*a*xi[0] + b) <= 0 or (2*a*xi[2] + b) <= 0:
                    continue
                mse = np.mean((yi - (a*xi**2 + b*xi + c))**2)
                candidates.append((mse, (i, j, k)))
            idxs = min(candidates, key=lambda v: v[0])[1] if candidates else list(range(min(3, len(df))))
            sel = df.loc[list(idxs)]
            a, b, c = np.polyfit((sel['timestamp'] - base).dt.total_seconds(), sel['viewcount'], 2)
            st.session_state.update({'a':a, 'b':b, 'c':c})

            # 세 점 시각화
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.scatter(sel['timestamp'], sel['viewcount'], s=100)
            ax.set_xlabel('시간'); ax.set_ylabel('조회수'); plt.xticks(rotation=45)
            st.pyplot(fig)
            st.markdown(f"**회귀식:** y = {a:.3e}x² + {b:.3e}x + {c:.3e}")

            # 정수화된 회귀식 및 그래프
            a_int, b_int, c_int = np.round([a, b, c]).astype(int)
            ts_int = np.linspace(0, x.max(), 200)
            fig_int, ax_int = plt.subplots(figsize=(6, 4))
            ax_int.plot(
                base + pd.to_timedelta(ts_int, 's'),
                a_int*ts_int**2 + b_int*ts_int + c_int
            )
            ax_int.set_xlabel('시간'); ax_int.set_ylabel('조회수'); plt.xticks(rotation=45)
            st.pyplot(fig_int)
            st.markdown(f"**정수화된 회귀식:** y = {a_int}x² + {b_int}x + {c_int}")

                        # 실측 대비 회귀 성능 평가
            if st.button("적합도 평가"):
                y_pred = a * x**2 + b * x + c
                mae = np.mean(np.abs(y - y_pred))
                rmse = np.sqrt(np.mean((y - y_pred)**2))
                mse = np.mean((y - y_pred)**2)
                st.write(f"**평균절대오차(MAE):** {mae:,.2f}")
                st.write(f"**제곱근평균제곱오차(RMSE):** {rmse:,.2f}")
                st.write(f"**평균제곱오차(MSE):** {mse:,.2f}")

                mean_views = y.mean()
                mae_ratio = mae / mean_views * 100
                st.write(f"📊 MAE/평균 조회수 비율: {mae_ratio:.2f}%")

                data_range = y.max() - y.min()
                mae_range = mae / data_range * 100
                st.write(f"📊 MAE/범위 비율: {mae_range:.2f}%")

                mape = np.mean(np.abs((y - y_pred) / y)) * 100
                st.write(f"📊 평균절대백분율오차(MAPE): {mape:.2f}%")

                residuals = y - y_pred
                fig_res, ax_res = plt.subplots(figsize=(6, 3))
                ax_res.scatter(df['timestamp'], residuals)
                ax_res.axhline(0, linestyle='--')
                ax_res.set_xlabel('시간'); ax_res.set_ylabel('Residuals')
                plt.xticks(rotation=45)
                st.pyplot(fig_res)

            # 실제 데이터 더보기 및 차이 이유 저장
            if st.button("실제 데이터 더 확인하기"):
                ts_curve = np.linspace(0, x.max(), 200)
                fig2, ax2 = plt.subplots(figsize=(6, 4))
                ax2.scatter(df['timestamp'], y, alpha=0.5)
                ax2.plot(
                    base + pd.to_timedelta(ts_curve, 's'), a*ts_curve**2 + b*ts_curve + c
                )
                ax2.set_xlabel('시간'); ax2.set_ylabel('조회수'); plt.xticks(rotation=45)
                st.pyplot(fig2)
            
                    # ── 0) 학생 의견 입력란 추가 ──
        st.subheader("💬 회귀분석과 적합도 평가 의견 남기기")
                # ── 반 선택 ─────────────────────────────────────────
        cls = st.selectbox(
            "반을 선택하세요",              # 라벨
            [f"{i}반" for i in range(1, 7)],  # 1~6반
            key="class_select"
        )

        # ── 조 선택 ─────────────────────────────────────────
        team = st.selectbox(
            "조를 선택하세요",
            [f"{c}조" for c in "ABCD"],        # A~D조
            key="team_select"
        )

        st.write(f"선택 결과 → {cls} {team}")
        session = f"{cls}-{team}"

        opinion_input = st.text_area(
            "모델 예측 결과와 실제 조회수의 차이에 대해 느낀 점이나 개선할 점을 적어주세요.",
            height=120,
            placeholder="예) 모델이 영상 업로드 초기의 급격한 조회수 증가를 과대평가한 것 같습니다, 이차함수 회귀만으로는 예측이 제한적이라는 것을 느꼈습니다. 등등"
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
                eval_sheet_name = "적합도평가"  # 필요하면 secrets.toml 에서 불러오세요
                ws = gc.open_by_key(yt_id).worksheet(eval_sheet_name)
                timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                row = [session, timestamp, opinion_input, summary]
                safe_append(ws, row)

                st.success("의견과 요약이 시트에 저장되었습니다!")



    elif step==3 and all(k in st.session_state for k in ('a','b','c')):
        step_header(
            "2️⃣-2️⃣ γ(광고효과) 시뮬레이션",
            "광고비 투입에 따른 조회수 증가를 실험해보세요",
            ["γ 값은 어떻게 해석할까?", "만약 광고비를 두 배로 늘린다면?", "광고비가 효율적일 조건은?"]
        )
        a, b, c = st.session_state['a'], st.session_state['b'], st.session_state['c']
        time_poly = np.poly1d([a, b, c])

        # 광고비 및 γ 입력 (1만 원 단위)
        budget = st.number_input(
            "투입할 광고비를 입력하세요 (원)",
            min_value=0,
            step=10000,
            value=1000000
        )
        gamma = st.slider(
            "광고효과 계수 γ 설정",
            min_value=0.0,
            max_value=5.0,
            value=0.5
        )

        # 예측 시점 값 계산
        x_now      = x[-1]
        t_now      = base + pd.to_timedelta(x_now, 's')
        y_time_now = time_poly(x_now)

        # 광고비 단위 계산 (1만 원을 1단위로 본다)
        unit  = 10000
        units = budget // unit
        y_ad  = gamma * units
        y_total = y_time_now + y_ad

        # 결과 출력
        st.write(f"▶️ 시간 모델 예측 조회수: **{int(y_time_now):,}회**")
        st.write(f"▶️ 광고비 효과 조회수: **{int(y_ad):,}회** (γ×{units})")
        st.write(f"▶️ **통합 예측 조회수:** **{int(y_total):,}회**")

        # 시각화
        fig2, ax2 = plt.subplots(figsize=(8,4))
        ax2.scatter(df['timestamp'], y, alpha=0.5, label="실제 조회수")
        ts_curve = np.linspace(0, x_now, 200)
        ax2.plot(
            base + pd.to_timedelta(ts_curve, 's'),
            time_poly(ts_curve),
            color="orange", lw=2, label="시간 모델 곡선"
        )
        ax2.scatter(
            t_now, y_time_now,
            color="green", s=80, label="시간 모델 예측점"
        )
        ax2.scatter(
            t_now, y_total,
            color="red", s=100, label="광고비 적용 예측점"
        )
        ax2.set_xlabel("시간")
        ax2.set_ylabel("조회수")
        ax2.legend()
        plt.xticks(rotation=45)
        st.pyplot(fig2)

        with st.expander("📖 γ(감마) 계수(광고효과)란?"):
            st.markdown("""
            - **γ(감마) 계수**: 광고비 1만 원을 썼을 때 늘어나는 조회수를 나타내는 숫자예요.  
            예를 들어 γ=2라면, 광고비 1만 원당 조회수가 2회씩 늘어난다는 뜻이죠.

            - **왜 1만 원 단위일까?**  
            너무 큰 단위(100만 원)보다 작은 단위(1만 원)로 나누면 계산하기 쉽고,  
            학생들도 `광고비 / 10,000`을 통해 늘어날 조회수를 바로 구해볼 수 있어요.

            - **간단 모형**:  
            ```
            조회수_증가 = γ × (광고비 ÷ 10,000)
            ```
            - 광고비를 10만 원 썼을 때(=10×10,000), γ=3이면  
                조회수_증가 = 3 × 10 = 30회
            """)

    elif step==4:
        step_header("3️⃣ 토의 내용 입력 & 요약하기",
                "프로젝트를 정리하고 수학적 모델링의 가치 확인하기",
                ["우리가 만든 모델의 장점과 한계는 무엇일까?", "썸네일, 알고리즘 같은 바이럴 요소를 어떻게 반영할까?", "프로젝트 진행 시 수학이 결정을 도와준 순간은 언제였을까?"])
                # ── 반 선택 ─────────────────────────────────────────
        cls = st.selectbox(
            "반을 선택하세요",              # 라벨
            [f"{i}반" for i in range(1, 7)],  # 1~6반
            key="class_select"
        )

        # ── 조 선택 ─────────────────────────────────────────
        team = st.selectbox(
            "조를 선택하세요",
            [f"{c}조" for c in "ABCD"],        # A~D조
            key="team_select"
        )

        st.write(f"선택 결과 → {cls} {team}")
        session = f"{cls}-{team}"

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
            ss = gc.open_by_key(yt_id)
            ds = ss.worksheet("토의요약")  # 미리 만들어두세요
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            row = [session, timestamp, raw, summary]
            safe_append(ds, row)
            st.info("스프레드시트에 저장되었습니다.")

def teacher_ui():
    st.title("🧑‍🏫 교사용 대시보드")
    df = pd.DataFrame(load_sheet_records(yt_name), columns=["학번","video_id","timestamp","viewcount"])
    if df.empty:
        st.info("데이터가 없습니다."); return
    st.metric("제출 건수", len(df))
    st.metric("평균 조회수", int(df["viewcount"].mean()))
    st.dataframe(df.tail(20))

# === 메인 탭 구조 ===
tab1, tab2 = st.tabs(["로그인", "회원가입"])
with tab1:
    if not st.session_state["logged_in"]:
        login_ui()
    else:
        MODE = st.sidebar.radio("모드 선택", ["학생용 페이지", "교사용 페이지"])
        if MODE == "학생용 페이지":
            main_ui()
        else:
            if not st.session_state.get("teacher_auth", False):
                pw = st.sidebar.text_input("교사 비밀번호를 입력하세요", type="password")
                if st.sidebar.button("확인"):
                    if pw == st.secrets["teacher"]["access_pw"]:   # ★ secrets.toml에 저장
                        st.session_state["teacher_auth"] = True
                        st.sidebar.success("교사 인증 완료!")
                        st.rerun()    # 페이지 새로 고침
                    else:
                        st.sidebar.error("비밀번호가 틀립니다.")
                st.stop()   # 비밀번호 맞을 때까지 teacher_ui 실행 차단
            # ② 인증 완료 → 교사용 대시보드
            teacher_ui()
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