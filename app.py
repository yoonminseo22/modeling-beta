# app.py 라이브러리 로드
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
import io

# 기본 설정
openai.api_key = st.secrets["openai"]["api_key"]
font_path = os.path.join("fonts", "NanumGothic.ttf")
fm.fontManager.addfont(font_path)
prop = fm.FontProperties(fname=font_path)
font_name = prop.get_name()
rcParams["font.family"] = font_name
plt.rc('axes', unicode_minus=False)
# 타이틀 설정
st.set_page_config("📈 유튜브 조회수 분석기", layout="centered")
st.title("📈 유튜브 조회수 분석기")
st.subheader("학생용 로그인/회원가입")


# 세션 상태 초기화 
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

# Sheets 도우미 (429 백오프 안정성) 및 캐시 초기화

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

@st.cache_data
def load_user_records():
    return load_sheet_records(usr_id, usr_name)

@st.cache_data
def load_yt_records():
    return load_sheet_records(yt_id, yt_name)

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

# 공통 UI 컴포넌트

def step_header(title: str, goals: List[str], questions: List[str]):
    st.markdown(f"### {title}")
    # 여러 개의 차시 목표를 리스트로 출력
    st.info("**차시 목표**\n" + "\n".join([f"- {g}" for g in goals]))
    # 핵심 발문은 expander 안에
    with st.expander("💡 핵심 발문"):
        st.markdown("\n".join([f"- {q}" for q in questions]))

# 해시 함수 (비밀번호 해시 처리)
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
    st.cache_data.clear()
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
# GPT 요약가
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
# GPT 대본 생성
def generate_script_example(prompt: str) -> str:
    """
    역할/주제 프롬프트를 받아 1-2문단 분량 예시 발표 대본을 반환합니다.
    """
    try:
        res = openai.chat.completions.create(
            model   = "gpt-3.5-turbo",
            messages= [
                {"role": "system", "content":
                 "당신은 중3 학생 발표 대본을 도와주는 친절한 선생님입니다."},
                {"role": "user",   "content": prompt}
            ],
            temperature = 0.7,
            max_tokens  = 300          # 필요시 조정
        )
        return res.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"GPT 호출 실패: {e}")
        return "⚠️ GPT 호출 실패 – 나중에 다시 시도해 주세요."
    
def fill_example(prompt: str, key: str):
    """GPT 예시 대본을 받아 session_state[key]에 삽입"""
    example = generate_script_example(prompt)
    st.session_state[key] = example
    st.toast("예시 대본이 입력되었습니다! 필요에 맞게 수정해 보세요.")

# 학생 메인 화면(로그인 후) 
def main_ui():
    load_sheet_records.clear()
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


    yt_rows = load_sheet_records(yt_id, yt_name)
    records = [r for r in yt_rows if str(r.get('학번','')) == sid]
    yt_ws = gc.open_by_key(yt_id).worksheet(yt_name)
    usr_rows = load_sheet_records(usr_id, usr_name)

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

        st.session_state["df"] = df
        base = df['timestamp'].min()
        x = (df['timestamp'] - base).dt.total_seconds().values
        y = df['viewcount'].values
    else:
        df = None

    #1차시
    if step==1:
        step_header("1️⃣ 유튜브 조회수 기록하기", ["실제 유튜브 영상 조회수 데이터를 선정하고 이차함수 회귀분석의 필요성을 이해한다.", "조회수 데이터를 수집하기 위한 기준을 설정하고 협력적으로 영상을 선정한다."],
                    ["그냥 점을 이어서 예측하면 정확할까? 왜 정확하지 않을까?", "정확한 예측을 하려면 무엇이 필요할까?", "회귀 분석이란 무엇일까? 왜 중요한 걸까?","그래프 형태가 왜 직선이 아닌 곡선으로 나타날까?","왜 현실의 데이터를 이차함수로 표현하면 좋을까?","우리가 영상 조회수를 예측할 때 어떤 기준으로 영상을 골라야 할까?"])
        yt_url = st.text_input("유튜브 링크를 입력하세요", key="yt_url")
        if st.button("조건 검증 및 조회수 기록", key="record_btn"):
            vid = extract_video_id(yt_url)
            if not vid:
                st.error("⛔ 유효한 유튜브 링크가 아닙니다.")
                st.stop()
            info = fetch_video_details(vid)
            if not info:
                st.error("영상 정보를 가져올 수 없습니다.")
                st.stop()
            valid = (info['views']<VIDEO_CRITERIA['max_views'] and
                      VIDEO_CRITERIA['min_subs']<=info['subs']<=VIDEO_CRITERIA['max_subs'])
            st.write(info)
            if not valid:
                st.warning("조건을 만족하지 않습니다. 다른 영상을 선택하세요.")
                st.stop()
            # ['학번','video_id','timestamp','viewCount','likeCount','commentCount']
            stats = {k:info[k] for k in ('views',)}  # views만 사용
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            safe_append(yt_ws, [sid, vid, ts, stats['views']])
            st.success("✅ 기록 완료")

        raw = st.text_area("나의 영상 선택 기준을 입력하세요", placeholder="예) 구독자 수 5천명 이상, 최근 6개월 이내 업로드, 조회수 증가 곡선이 완만한 영상",  key="selection_raw", height=200)
        if st.button("요약 & 저장", key="summary_btn"):
            if not raw.strip():
                st.error("선정 기준을 입력해야 합니다.")
                st.stop()

            # GPT 요약
            with st.spinner("GPT에게 기준을 요약받는 중..."):
                summary = summarize_discussion(raw)
            st.success("요약 완료!")
            st.write("**요약본**")
            st.write(summary)

            # 스프레드시트 기록
            ss = gc.open_by_key(yt_id)
            ws = ss.worksheet("영상선택기준")  # 미리 해당 시트 생성
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
            row = [sid, timestamp, raw, summary]
            safe_append(ws, row)
            st.info("스프레드시트에 저장되었습니다.")
    #2차시
    elif step==2:
        step_header("2️⃣-1️⃣ 유튜브 조회수 이차 회귀 분석하기",
                    ["조회수 데이터를 활용해 이차함수 회귀식을 생성하고 그 성질(계수, 꼭짓점, 볼록성 등)을 해석할 수 있다.", "생성된 회귀식을 활용하여 조회수가 100만에 도달하는 시점을 예측할 수 있다."],
                    ["이차함수의 계수는 각각 그래프의 어떤 성질을 결정할까?", "회귀 분석을 할 때, 왜 3개의 점이 필요한 걸까?", "우리가 만든 회귀식으로 어떻게 100만 조회수 시점을 예측할 수 있을까?","예측한 결과가 실제와 다를 때, 어떤 원인이 있을 수 있을까?"])
        if not records:
            st.info("내 기록이 아직 없습니다. 먼저 '1️⃣ 조회수 기록하기'로 기록하세요.")
            return
    
        # 그래프 보기 버튼
        if st.button("회귀 분석하기"):
            # 1) 최적 세 점 선택
            candidates = []
            for i, j, k in combinations(range(len(df)), 3):
                xi, yi = x[[i, j, k]], y[[i, j, k]]  # 여기서 x, y는 원래 초 단위 x와 원단위 y
                a_tmp, b_tmp, c_tmp = np.polyfit(xi, yi, 2)
                # 순증가 구간(오름차순) 조건 체크
                if a_tmp <= 0 or (2 * a_tmp * xi[0] + b_tmp) <= 0 or (2 * a_tmp * xi[2] + b_tmp) <= 0:
                    continue
                mse = np.mean((yi - (a_tmp * xi**2 + b_tmp * xi + c_tmp))**2)
                candidates.append((mse, (i, j, k)))

            # 후보 중 MSE가 가장 작은 세 점 선택 (없으면 그냥 처음 세 점)
            idxs = min(candidates, key=lambda v: v[0])[1] if candidates else list(range(min(3, len(df))))
            sel = df.loc[list(idxs)].reset_index(drop=True)

            # 2) y_scaled: 만 단위로 축소
            y_scaled = sel['viewcount'] / 10000  # 예: 381000 → 38.1 (만 단위)

            # 3) x_hours: 경과 시간(시 단위) 계산
            elapsed_seconds = (sel['timestamp'] - base).dt.total_seconds()
            x_hours = elapsed_seconds / 3600  # 예: 3600초 → 1.0 (시 단위)

            # 4) 이차회귀계수 계산 (y_scaled에 대해)
            a, b, c = np.polyfit(x_hours, y_scaled, 2)

            elapsed_all = (df['timestamp'] - base).dt.total_seconds()
            x_hours_all = elapsed_all / 3600

            # 5) session_state에 회귀계수와 기본 변수들 저장
            st.session_state.update({
                'a': a,
                'b': b,
                'c': c,
                'base': base,
                'x_hours': x_hours,     # 회귀에 사용된 x(시간 단위)
                'y': y,                 # 원본 조회수(원 단위)
                'y_scaled': y_scaled,    # 선택된 세 점의 조회수(만 단위)
                'x_hours_all': x_hours_all
            })

            # 선택된 세 점만 산점도로 표시
            elapsed_sel = (sel['timestamp'] - base).dt.total_seconds() / 3600
            fig, ax = plt.subplots(figsize=(6, 6))
            ax.scatter(
                elapsed_sel,
                y_scaled,
                s=100,
                color='steelblue',
                label="선택된 세 점 (만 단위)"
            )
            ax.grid(True, linestyle='--', alpha=0.7)
            ax.set_xlabel('경과 시간 (시간 단위)')
            ax.set_ylabel('조회수 (단위: 만 회)')
            ax.legend()
            st.pyplot(fig)

            # 그래프 저장 및 다운로드 버튼
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            buf.seek(0)
            st.download_button(
                label="📷 회귀분석 그래프 다운로드",
                data=buf,
                file_name="regression_plot.png",
                mime="image/png"
            )

            # 회귀식 출력 (만 단위 기준, 소수점 네 자리로)
            str_a = f"{a:.4f}"
            str_b = f"{b:.4f}"
            str_c = f"{c:.4f}"
            st.markdown(
                f"**이차회귀식 (단위: 만 회 기준)**\n\n"
                f"- $y$ : 실제 조회수 ÷ 10,000 (만 단위)\n"
                f"- $x$ : 경과시간 (시간 단위, 기준=base)\n\n"
                f"$$y(만) = {str_a}\\,x^2 \;+\; {str_b}\\,x \;+\; {str_c}$$\n\n"
                f"예를 들어, 위 식에서 $y=100$ ($\\equiv$ 실제 조회수 1,000,000)이 되는 $x$를 구하면,\n"
                f"그 값을 시간(시) 단위로 해석할 수 있습니다."
            )

            st.markdown(
                "**Q1.** 이차함수의 식을 보고 축의 방정식, 볼록성, 꼭짓점, y절편을 찾아보세요.\n\n"
                "**Q2.** 실제 조회수 1,000,000(만 단위로 100)이 되는 시점을 예측해보세요.\n"
                "(Hint: 위 회귀식에서 $y=100$인 $x$를 구하면 됩니다. 단위는 시간(시)입니다.)"
            )

            # 적합도 평가 및 상세 보기 버튼 상태 초기화
            st.session_state["eval_clicked"] = False
            st.session_state["detail_clicked"] = False

        # ─── 2. 회귀 계수와 데이터 준비 (세션에 저장되어 있어야 함) ─────────────
        if "a" in st.session_state and "df" in st.session_state and "base" in st.session_state:
            a         = st.session_state["a"]
            b         = st.session_state["b"]
            c         = st.session_state["c"]
            base      = st.session_state["base"]
            df_global = st.session_state["df"]

            # y_original: 세션에 있으면 그대로, 없으면 df_global에서 추출
            y_original = np.array(df_global['viewcount'])

            # x_hours_all: 세션에 있으면 그대로, 없으면 계산
            if "x_hours_all" in st.session_state:
                x_hours_all = st.session_state["x_hours_all"]
            else:
                elapsed_all = (df_global['timestamp'] - base).dt.total_seconds()
                x_hours_all = elapsed_all / 3600

            # ─── 3. ‘적합도 평가’ 버튼 ───────────────────────────────────────
            if st.button("적합도 평가", key="eval_button"):
                st.session_state["eval_clicked"] = True

            if st.session_state.get("eval_clicked", False):
                # 1) 결측치 있는 행 제거
                df_clean = df_global.dropna(subset=['timestamp', 'viewcount']).reset_index(drop=True)

                # 2) timestamp→datetime, viewcount→numpy array
                timestamps  = pd.to_datetime(df_clean['timestamp'])
                y_original  = df_clean['viewcount'].astype(float).values

                # 3) 시간 경과(초) → 시간(시간 단위)
                elapsed_sec = (timestamps - base).dt.total_seconds()
                x_hours_all = elapsed_sec / 3600

                # 디버깅: 길이 확인 (주석 해제해 보세요)
                # st.write("len(x)=", x_hours_all.size, "len(y)=", y_original.size)

                # 4) 예측값 계산 (만 단위 → 원 단위)
                time_poly     = np.poly1d([a, b, c])
                y_pred_scaled = time_poly(x_hours_all)
                y_pred        = y_pred_scaled * 10000

                # 5) MAE/​MAPE 계산
                errors     = y_original - y_pred
                abs_errors = np.abs(errors)
                MAE        = np.mean(abs_errors)
                MAPE       = np.mean(abs_errors / (y_original + 1)) * 100

                # 6) 결과 출력
                st.markdown(f"### 🔍 평균 절대 오차 (MAE): {MAE:,.0f}회")
                st.markdown(f"### 🔍 평균 오차율 (MAPE): {MAPE:.1f}%")

                # 7) 등급 평가
                if MAPE <= 15:
                    grade = "🟢 매우 정확!"
                elif MAPE <= 40:
                    grade = "🟡 보통 수준"
                else:
                    grade = "🔴 개선 필요"
                st.markdown(f"**모델 적합 등급:** {grade}")

                # 8) 시각화
                df_plot = pd.DataFrame({
                    '시간(시간 단위)': x_hours_all,
                    '실제 조회수':    y_original,
                    '예측 조회수':    y_pred
                })
                st.line_chart(df_plot.set_index('시간(시간 단위)'))

                # 4-7) 개념 설명
                st.markdown("""
        **MAE(평균 절대 오차)**  
        예측값과 실제값의 차이를 모두 양수로 바꿔 평균을 구한 값으로,  
        ‘평균적으로 몇 회’ 차이가 나는지를 직관적으로 알려줘요.

        **MAPE(평균 오차율)**  
        예측 오차가 실제 조회수 대비 몇 퍼센트인지 알려줘서,  
        숫자가 커도 비율로 쉽게 비교할 수 있습니다.

        - 값이 작을수록 모델이 더 정확해요!  
        - 등급과 그래프를 통해 모델 성능을 한눈에 파악해 보세요.
        """)
            if st.button("실제 데이터 더 확인하기", key="detail_button"):
                st.session_state["detail_clicked"] = True

            if st.session_state.get("detail_clicked", False):
                # 1) 결측치 제거 후 재계산
                df_clean = df_global.dropna(subset=['timestamp', 'viewcount']).reset_index(drop=True)
                timestamps = pd.to_datetime(df_clean['timestamp'])
                y_original = df_clean['viewcount'].astype(float).values

                # 2) 시간(시간 단위) 축 재계산
                elapsed_sec = (timestamps - base).dt.total_seconds()
                x_hours_all = elapsed_sec / 3600

                # 3) 회귀 곡선용 시간 샘플
                ts_curve = np.linspace(0, x_hours_all.max(), 200)

                # 4) 플롯 그리기
                fig2, ax2 = plt.subplots(figsize=(6, 4))
                ax2.scatter(timestamps, y_original, alpha=0.5, label="실제 조회수")

                # 5) 모델 곡선 계산 & 플롯
                y_curve_scaled = a * ts_curve**2 + b * ts_curve + c
                y_curve = y_curve_scaled * 10000
                x_curve_timestamps = base + pd.to_timedelta(ts_curve * 3600, unit='s')
                ax2.plot(x_curve_timestamps, y_curve, color='red', linewidth=2, label="회귀 곡선")

                ax2.set_xlabel('시간')
                ax2.set_ylabel('조회수')
                ax2.legend()
                plt.xticks(rotation=45)
                st.pyplot(fig2)

                # 6) 이미지 다운로드 버튼
                buf1 = io.BytesIO()
                fig2.savefig(buf1, format='png', dpi=150, bbox_inches='tight')
                buf1.seek(0)
                st.download_button(
                    label="📷 실제 데이터 그래프 다운로드",
                    data=buf1,
                    file_name="real_data_plot.png",
                    mime="image/png"
                )
            
                    # 학생 의견 입력란
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
            "모델 예측 결과(100만이 되는 시점)을 적고 실제 조회수의 차이에 대해 왜 차이가 발생했는지 그 이유를 적어주세요.",
            height=120,
            placeholder="예) 모델이 영상 업로드 초기의 급격한 조회수 증가를 과대평가한 것 같습니다/이차함수는 계속 올라가는데 영상 조회수의 증가는 한계가 있었습니다. 등등"
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

                # 스프레드시트에 기록
                eval_sheet_name = "적합도평가"  # 해당 시트 미리 생성
                ws = gc.open_by_key(yt_id).worksheet(eval_sheet_name)
                timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                row = [session, timestamp, opinion_input, summary]
                safe_append(ws, row)

                st.success("의견과 요약이 시트에 저장되었습니다!")

    elif step == 3 and all(k in st.session_state for k in ('a','b','c')):
        # 1) 제목 및 질문
        step_header(
            "2️⃣-2️⃣ γ(광고효과) 시뮬레이션(Power Model)",
            ["실제 데이터와 예측값을 비교하여 적합성을 평가(평균 오차)한다.",
            "실제 데이터와 예측값을 비교하며 광고 전략의 영향을 이해한다."],
            ["적합성 평가(평균 오차)를 왜 해야 할까? 이 수치들이 무엇을 의미할까?",
            "광고는 조회수에 어떤 영향을 미칠 수 있을까? 그 영향이 그래프에서 어떻게 나타날까?"]
        )

        # 2) 시간 모델 계수 불러오기
        a, b, c = st.session_state['a'], st.session_state['b'], st.session_state['c']
        time_poly = np.poly1d([a, b, c])

        # 3) 광고비·γ·지수 p 입력
        budget = st.number_input(
            "투입할 광고비를 입력하세요 (원)",
            min_value=0, step=10000, value=1000000, format="%d"
        )
        gamma = st.slider(
            "광고효과 계수 γ 설정 (1만 원당 기본 증가 조회수)",
            min_value=0.0, max_value=20.0, value=2.0, step=0.1
        )
        p = st.slider(
            "광고비 효과 지수 p 설정 (1보다 크게 하면 드라마틱 효과)",
            min_value=1.0, max_value=3.0, value=1.5, step=0.1
        )

        # 4) 현재 시점(시간 단위) 계산
        x_hours = st.session_state["x_hours"]            # (timestamp - base).dt.total_seconds()/3600
        x_now = x_hours.iloc[-1]                         # 마지막 기록 시점 (시간 단위)
        base = st.session_state["base"]                  # 기준 datetime
        t_now = base + pd.to_timedelta(x_now * 3600, 's')

        # 5) 시간 모델 예측값 (만 단위 → 원 단위)
        y_time_scaled = time_poly(x_now)                 # 만 단위 예측
        y_time_now    = int(round(y_time_scaled * 10000))# 원 단위 예측

        # 6) Power 모델 광고효과 계산
        unit_won = 10000
        units = budget // unit_won                       # 만 원 단위로 환산
        y_ad = int(round(gamma * (units ** p)))          # γ × units^p (원 단위 추가 조회수)

        # 7) 통합 예측 조회수
        y_total_now = y_time_now + y_ad

        # 8) 결과 출력
        st.write(f"▶️ 시간 모델 예측 조회수 (광고 없음): **{y_time_now:,}회**")
        st.write(f"▶️ 광고비 효과 조회수 (Power 모델): **+{y_ad:,}회**  (γ×{units}^p)")
        st.write(f"▶️ **통합 예측 조회수:** **{y_total_now:,}회**")

        # 9) 시각화
        fig2, ax2 = plt.subplots(figsize=(8, 4))
        df_global = st.session_state["df"]
        y_original = st.session_state["y"]

        # 실제 데이터
        ax2.scatter(df_global['timestamp'], y_original, alpha=0.5, label="실제 조회수")

        # 시간 모델 곡선 (광고 없음)
        ts_curve = np.linspace(0, x_now, 200)
        y_curve = time_poly(ts_curve) * 10000
        times = base + pd.to_timedelta(ts_curve * 3600, 's')
        ax2.plot(times, y_curve, linestyle="--", color="orange", lw=2, label="시간 모델 (광고 없음)")

        # 광고효과를 더한 Power 모델 곡선
        y_curve_with_ad = y_curve + y_ad
        ax2.plot(times, y_curve_with_ad, color="red", lw=2, label="시간 모델 + 광고 효과")

        # 현재 시점 예측점
        ax2.scatter(t_now, y_time_now, color="green", s=80, label="광고 전 예측")
        ax2.scatter(t_now, y_total_now, color="red",   s=100, label="광고 후 예측")

        ax2.set_xlabel("시간")
        ax2.set_ylabel("조회수 (원 단위)")
        ax2.legend()
        plt.xticks(rotation=45)
        st.pyplot(fig2)

        # 10) 그래프 다운로드
        buf2 = io.BytesIO()
        fig2.savefig(buf2, format='png', dpi=150, bbox_inches='tight')
        buf2.seek(0)
        st.download_button(
            label="📷 광고 효과 Power 모델 그래프 다운로드",
            data=buf2,
            file_name="power_ad_effect_updated.png",
            mime="image/png"
        )
        
        with st.expander("📖 γ(감마)·p(지수) 계수 해설 (학생용)"):
            st.markdown("""
            **1. γ(감마) 계수란?**  
            - 광고비 **1만 원**을 썼을 때, **얼마나 조회수가 더 늘어나는지** 알려주는 숫자예요.  
            - 예를 들어 γ = 2 라고 하면,  
            - 광고비 1만 원당 조회수가 **+2회** 늘어난다는 뜻이랍니다.  
            - 그래서 광고비가 50만 원(=50단위)이라면,  
                `조회수 증가 = 2 × 50 = 100회` 가 추가돼요.

            **2. p(지수) 계수란?**  
            - p는 단순히 곱하기가 아니라, **거듭 제곱**처럼 효과가 커지는 정도를 정해줘요.  
            - 공식은 `조회수 증가 = γ × (units ** p)` 이고,  
            - units = 광고비 ÷ 10,000 (만 원 단위)  
            - p가 **1보다 크면**,  
            - 광고비를 두 배로 올렸을 때,  
            - 조회수 증가폭이 **(2^p)배**로 늘어나서 훨씬 드라마틱해져요!  
            - 예시)  
            - γ=2, 광고비=100만 원 → units=100  
            - p=1.0 → 조회수 증가 = 2 × (100¹) = 200회  
            - p=2.0 → 조회수 증가 = 2 × (100²) = 2 × 10,000 = 20,000회  
            - p=1.5 → 조회수 증가 = 2 × (100¹·⁵) ≈ 2 × 1,000 = 2,000회

            **3. 왜 이렇게 계산할까?**  
            - 실제 광고를 많이 할수록 조회수가 선형보다 더 크게 늘어난다고 가정해 보면,  
            - p를 이용해 ‘광고 효과가 점점 더 커지는 모습’을 보여줄 수 있어요.

            **4. 정리와 팁**  
            1. **γ**는 “단위 광고비로 얻는 기본 조회수”  
            2. **p**가 크면 클수록 “광고비를 늘렸을 때 조회수가 더 폭발적으로 증가”  
            3. 너무 큰 p를 쓰면 현실감이 떨어지니, **1.0~2.0 사이**에서 실험해 보세요.  
            4. 다양한 값을 바꿔 보면서 그래프가 어떻게 달라지는지 눈으로 확인해 보세요!
            """)

    #3차시
    elif step==4:
        step_header("3️⃣ 토의 내용 입력 & 요약하기",
                ["데이터 분석 결과를 종합하여 발표 자료로 구성하고 분석 및 마케팅 전략에 대해 명확하게 전달할 수 있다.","조별 협력을 통해 체계적으로 발표 준비 과정을 경험하고 설득력 있는 발표를 구성할 수 있다."],
                ["우리 조가 분석한 결과를 가장 효과적으로 전달하려면 어떻게 발표를 구성해야 할까?", "우리가 선택한 영상의 특성을 명확히 설명하기 위한 핵심적인 내용은 무엇일까?", "이차함수 회귀식과 그래프에서 꼭 강조해야 하는 성질과 의미는 무엇일까?","예측값과 실제값의 차이를 발표에서 어떻게 설명하면 설득력이 있을까?","우리의 마케팅 전략을 설득력 있게 전달하려면 어떤 자료와 표현을 써야 할까?","이 분석 활동을 통해 어떤 것을 새롭게 배우고 느꼈는지 발표에서 어떻게 말하면 좋을까?"])
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

        st.divider()  # 시각적 구분선

            # ── 역할 선택 & 안내 ───────────────────────────
        roles = {
            "영상 선정 기준": (
                "분석에 적합한 영상 주제와 구독자 규모를 명확히 제시합니다. "
                "주제 특성과 구독자 수치를 근거로 선정 이유를 설명합니다."),
            "회귀분석 결과 및 그래프 설명": (
                "이차함수 회귀식(a, b, c)의 의미를 풀이하고, "
                "그래프의 꼭짓점·볼록성·y절편·100만 조회 시점을 강조합니다."),
            "적합도 평가": (
                "실제 조회수와 예측값의 평균 오차를 제시합니다. "
                "오차 수치가 낮을수록 모델 정확도가 높다는 점을 명확히 합니다."),
            "마케팅 전략": (
                "분석 결과를 바탕으로 광고비 배분과 최적 업로드 타이밍을 제안합니다. "
                "구체적 실행 방안을 포함해 설득력을 높입니다."),
            "느낀점 및 종합 정리": (
                "분석 과정에서 얻은 인사이트와 한계, 개선 방향을 정리합니다. "
                "개인·조별 성장 경험을 담아 발표를 마무리합니다.")}
        my_role = st.selectbox("역할을 선택하세요", list(roles.keys()), key="role_select")
        st.info(f"**내 역할 가이드:**  {roles[my_role]}")

        script_templates = {
            "영상 선정 기준": "예시) 안녕하세요, 저는 저희 조에서 영상 선택 기준을 발표할 ○○○입니다. 저희 조는 영상의 주제, 재미, 그리고 채널의 구독자 수를 기준으로 영상을 골랐습니다. 특히 주제가 인기가 있고 사람들이 관심을 많이 가질 것 같은 영상을 선택했고, 재미있어서 끝까지 볼 만한 영상을 중점으로 살폈습니다. 또 구독자 수가 많은 채널은 조회수가 더 빨리 오를 거라고 생각해 선택했습니다. 감사합니다.",
            "회귀분석 결과 및 그래프 설명": "예시) 안녕하세요, 저는 저희 조에서 회귀식을 설명하고, 100만 조회수를 달성하는 시점을 예측할 ○○○입니다. 저희가 구한 회귀식은 다음과 같습니다. y = □x² + □x + □ 이 식을 이용해 계산해본 결과, 약 □□일 후에 조회수가 100만 회에 도달할 것으로 예측했습니다. 실제 데이터와 비교했을 때, 저희 예측이 얼마나 정확한지 확인할 수 있었습니다. 감사합니다. 또한 저희 회귀식 그래프는 아래로 볼록한 이차함수 형태이며, 다음과 같은 특징을 가집니다. 꼭짓점은 (□□, □□)이고 그래프의 대칭축은 x=□□, y절편은 □□입니다.",
            "적합도 평가": "예시) 안녕하세요, 저는 저희 조의 적합도 평가를 맡은 ○○○입니다. 저희는 예측 모델이 실제 조회수 데이터를 얼마나 잘 설명하는지를 확인하기 위해 평균 오차를 사용했습니다. 저희 결과는 약 **□□□**였습니다. 이 수치는 예측이 실제 데이터와 비교적 가까운 편이라는 것을 보여줍니다. 하지만 일부 시점에서는 예측값과 실제값의 차이가 크게 나는 구간도 있었는데, 그 이유는 영상이 갑자기 바이럴되었거나, 광고 효과가 컸던 시점 때문이라고 생각합니다. 이런 적합도 평가를 통해 단순히 회귀식을 세우는 것뿐 아니라, 그 식이 얼마나 믿을 만한지도 함께 판단할 수 있어서 좋았습니다. 감사합니다.",
            "마케팅 전략": "예시) 안녕하세요, 저는 저희 조의 마케팅 전략 정리를 맡은 ○○○입니다. 저희 조는 분석한 결과를 바탕으로 다음과 같은 전략을 세웠습니다. 광고를 이용해 영상이 초반에 빨리 퍼질 수 있도록 합니다. 제목과 썸네일을 자극적으로 만들어 클릭률을 높입니다. 영상 길이를 짧게 만들어 사람들이 끝까지 볼 수 있게 합니다. 댓글을 자주 달고 시청자들과 소통하여 지속적인 관심을 유도합니다. 이러한 전략을 통해 저희 예측값과 실제 조회수의 차이를 줄일 수 있을 거라 생각합니다. 감사합니다.",
            "느낀점 및 종합 정리": "예시) 안녕하세요, 저는 저희 조의 프로젝트 수업 소감을 맡은 ○○○입니다. 저는 이번 프로젝트를 통해 실제로 유튜브 영상의 조회수를 수학으로 예측할 수 있다는 점이 흥미로웠습니다. 처음에는 수학이 현실에서 별로 쓰이지 않을 줄 알았는데, 이번 활동을 하면서 수학이 생각보다 실생활과 많이 연결되어 있다는 것을 알게 됐습니다. 특히, 실제 데이터로 분석하고 예측했던 경험이 아주 재미있고 유익했습니다. 감사합니다."
        }


        # ── 대본 작성 영역 ─────────────────────────────
        script_key = f"script_{session}_{my_role}"
        script = st.text_area("대본을 작성해 보세요 ✍️",value=script_templates.get(my_role, ""), key=script_key, height=250,
                            placeholder="여기에 발표 대본을 적어 보세요…")

        col1, col2 = st.columns(2)
        with col1:
            # ② 버튼 – on_click으로 콜백 연결
            prompt = (
                f"역할: {my_role}\n"
                "발표 주제: 유튜브 이차회귀 분석 결과\n"
                "200자 내외 발표 대본 작성"
            )
            st.button(
                "💡 스크립트 예시 생성(GPT)",
                on_click=fill_example,
                args=(prompt, script_key)
            )

        with col2:
            if st.button("📑 저장 & 요약", key="save_summary"):
                if not script.strip():
                    st.error("대본이나 토의 내용을 입력해야 저장할 수 있습니다.")
                    st.stop()

                # ① GPT 요약
                with st.spinner("GPT에게 요약을 부탁하는 중…"):
                    summary = summarize_discussion(script)

                # ② 시트 저장
                timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                row = [session, my_role, timestamp, script, summary]
                try:
                    ss = gc.open_by_key(yt_id)
                    ws = ss.worksheet("토의요약")   # 미리 생성
                    safe_append(ws, row)
                    st.success("스프레드시트에 저장되었습니다!")
                except Exception as e:
                    st.error(f"스프레드시트 저장 중 오류: {e}")

                # ③ 요약 출력
                st.markdown("### ✂️ GPT 요약본")
                st.write(summary)
#교사용 대시보드 만들기
def teacher_ui():
    st.title("🧑‍🏫 교사용 대시보드")
    df = pd.DataFrame(load_sheet_records(yt_name), columns=["학번","video_id","timestamp","viewCount"])
    if df.empty:
        st.info("데이터가 없습니다."); return
    st.metric("제출 건수", len(df))
    st.metric("평균 조회수", int(df["viewCount"].mean()))
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