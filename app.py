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
import io

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

            # 5) session_state에 회귀계수와 기본 변수들 저장
            st.session_state.update({
                'a': a,
                'b': b,
                'c': c,
                'base': base,
                'x_hours': x_hours,     # 회귀에 사용된 x(시간 단위)
                'y': y,                 # 원본 조회수(원 단위)
                'y_scaled': y_scaled    # 선택된 세 점의 조회수(만 단위)
            })

            # 6) 세 점(만 단위) 산점도 시각화
            fig, ax = plt.subplots(figsize=(6, 4))
            ax.scatter(sel['timestamp'], y_scaled, s=100, color='steelblue', label="선택된 세 점 (만 단위)")
            ax.set_xlabel('시간')
            ax.set_ylabel('조회수 (단위: 만 회)')
            ax.legend()
            plt.xticks(rotation=45)
            st.pyplot(fig)

            # 7) 그래프 저장 및 다운로드 버튼
            buf = io.BytesIO()
            fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
            buf.seek(0)
            st.download_button(
                label="📷 회귀분석 그래프 다운로드",
                data=buf,
                file_name="regression_plot.png",
                mime="image/png"
            )

            # 8) 회귀식 출력 (만 단위 기준, 소수점 네 자리로 포맷)
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

            # 9) 적합도 평가 및 상세 보기 버튼 상태 초기화
            st.session_state["eval_clicked"] = False
            st.session_state["detail_clicked"] = False

    if "a" in st.session_state and "df" in st.session_state and "base" in st.session_state:
        # 2-a) 세션에서 필요한 값 불러오기 (없는 경우 기본값으로 계산)
        a = st.session_state["a"]
        b = st.session_state["b"]
        c = st.session_state["c"]
        base = st.session_state["base"]
        df_global = st.session_state["df"]

        # y_original: 세션에 있으면 그대로, 없으면 df_global에서 추출
        y_original = st.session_state.get("y_original", df_global['viewcount'].values)

        # x_hours_all: 세션에 있으면 그대로, 없으면 df_global에서 계산
        if "x_hours_all" in st.session_state:
            x_hours_all = st.session_state["x_hours_all"]
        else:
            elapsed_all = (df_global['timestamp'] - base).dt.total_seconds()
            x_hours_all = elapsed_all / 3600

        # 2-b) ‘적합도 평가’ 버튼
        if st.button("적합도 평가", key="eval_button"):
            st.session_state["eval_clicked"] = True

        # 2-c) ‘eval_clicked’가 True인 경우 계산 및 출력
        if st.session_state.get("eval_clicked", False):
            # 2-c-1) 전체 예측값(만 단위) → 전체 예측값(원 단위) 벡터 생성
            time_poly     = np.poly1d([a, b, c])
            y_pred_scaled = time_poly(x_hours_all)      # 만 단위 예측값 (길이 N)
            y_pred        = y_pred_scaled * 10000       # 원 단위 예측값 (길이 N)

            # 2-c-2) 오차(errors) 계산 (길이 N 벡터)
            errors = y_original - y_pred

            # 2-c-3) MAE 계산
            abs_errors = np.abs(errors)
            MAE = np.mean(abs_errors)
            st.write(f"· 평균절대오차(MAE): {MAE:,.2f}")

            # 2-c-4) MSE, RMSE 계산
            sq_errors = errors**2
            MSE = np.mean(sq_errors)
            RMSE = np.sqrt(MSE)
            st.write(f"· 평균제곱오차(MSE): {MSE:,.2f}")
            st.write(f"· 제곱근평균제곱오차(RMSE): {RMSE:,.2f}")

            # 2-c-5) MAE / 평균 조회수 비율
            mean_views = y_original.mean()
            MAE_ratio = MAE / mean_views * 100
            st.write(f"· MAE / 평균 조회수 비율: {MAE_ratio:.2f}%")

            # 2-c-6) MAE / 데이터 범위 비율
            data_range = y_original.max() - y_original.min()
            MAE_range_ratio = MAE / data_range * 100
            st.write(f"· MAE / 데이터 범위 비율: {MAE_range_ratio:.2f}%")

            # 2-c-7) MAPE 계산 (원단위)
            mask = y_original > 0
            pct_errors = np.abs((y_original[mask] - y_pred[mask]) / y_original[mask]) * 100
            MAPE = np.mean(pct_errors)
            st.write(f"· 평균절대백분율오차(MAPE): {MAPE:.2f}%")

            # 2-c-8) 잔차(residual) 그래프 그리기
            fig_res, ax_res = plt.subplots(figsize=(6, 3))
            ax_res.scatter(df_global['timestamp'], errors, s=15, color='purple', label="잔차 (원 단위)")
            ax_res.axhline(0, linestyle='--', color='gray')
            ax_res.set_xlabel('시간')
            ax_res.set_ylabel('잔차 (실제 조회수 − 예측 조회수)')
            ax_res.legend()
            plt.xticks(rotation=45)
            st.pyplot(fig_res)

            if st.button("실제 데이터 더 확인하기", key="detail_button"):
                st.session_state["detail_clicked"] = True

            if st.session_state.get("detail_clicked", False):
                # 1) 회귀에 사용한 x_hours(시간 단위) 배열을 가져온다
                x_hours_all = st.session_state["x_hours"]   # (timestamp – base).dt.total_seconds() / 3600
                # 2) ts_curve: 0부터 x_hours_all.max()까지 200개 점을 생성 (시간 단위)
                ts_curve = np.linspace(0, x_hours_all.max(), 200)

                fig2, ax2 = plt.subplots(figsize=(6, 4))

                # 3) 실제 데이터 산점도 (원본 timestamp vs 원본 viewcount)
                #    df에는 ['timestamp'], y_original (원본 조회수) 가 있다고 가정
                df_global = st.session_state["df"]
                y_original = st.session_state["y"]
                ax2.scatter(df_global['timestamp'], y_original, alpha=0.5, label="실제 조회수")

                # 4) 모델 곡선: ts_curve(시 단위)를 초 단위로 변환해서 timestamp 계산
                base = st.session_state["base"]
                a, b, c = st.session_state["a"], st.session_state["b"], st.session_state["c"]
                # 회귀식으로 예측된 y_scaled (만 단위)
                y_curve_scaled = a * ts_curve**2 + b * ts_curve + c
                # 실제 조회수 단위로 환산 (만 단위 → 원 단위)
                y_curve = y_curve_scaled * 10000

                # x_curve_timestamp: base + (ts_curve 시 단위 → 초 단위) 
                x_curve_timestamp = base + pd.to_timedelta(ts_curve * 3600, unit='s')
                ax2.plot(x_curve_timestamp, y_curve, color='red', linewidth=2, label="회귀 곡선")

                ax2.set_xlabel('시간')
                ax2.set_ylabel('조회수')
                ax2.legend()
                plt.xticks(rotation=45)
                st.pyplot(fig2)

                # 5) 다운로드 버튼 (원단위 곡선 그래프)
                buf1 = io.BytesIO()
                fig2.savefig(buf1, format='png', dpi=150, bbox_inches='tight')
                buf1.seek(0)
                st.download_button(
                    label="📷 실제 데이터 그래프 다운로드",
                    data=buf1,
                    file_name="real_data_plot_scaled.png",
                    mime="image/png"
                )
            
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

                # 2) 스프레드시트에 기록
                eval_sheet_name = "적합도평가"  # 필요하면 secrets.toml 에서 불러오세요
                ws = gc.open_by_key(yt_id).worksheet(eval_sheet_name)
                timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
                row = [session, timestamp, opinion_input, summary]
                safe_append(ws, row)

                st.success("의견과 요약이 시트에 저장되었습니다!")

    elif step == 3 and all(k in st.session_state for k in ('a','b','c')):
        # 제목 및 질문
        step_header(
            "2️⃣-2️⃣ γ(광고효과) 시뮬레이션",
            "광고비 투입에 따른 조회수 증가를 실험해보세요",
            ["γ 값은 어떻게 해석할까?", "만약 광고비를 두 배로 늘린다면?", "광고비가 효율적일 조건은?"]
        )

        # 1) 회귀 계수 불러오기 (a, b, c 모두 “시간(시)” / “만 단위” 기준)
        a, b, c = st.session_state['a'], st.session_state['b'], st.session_state['c']
        time_poly = np.poly1d([a, b, c])

        # 2) 광고비 및 γ 입력 (1만 원 단위)
        budget = st.number_input(
            "투입할 광고비를 입력하세요 (원)",
            min_value=0, step=10000, value=1000000, format="%d"
        )
        gamma = st.slider(
            "광고효과 계수 γ 설정 (1만 원당 추가 조회수)",
            min_value=0.0, max_value=20.0, value=2.0, step=0.1
        )
        # γ=2라면 “광고비 1만 원당 조회수 +2회”(만 단위 아님, 실제 회수)

        # 3) 현재까지 마지막으로 기록된 “경과시간(시간 단위)”과 대응 timestamp 계산
        #    st.session_state["x_hours"]는 (timestamp – base).dt.total_seconds()/3600 형태
        x_hours_all = st.session_state["x_hours"]
        x_now = x_hours_all.iloc[-1]                           # 마지막 시점(시간 단위)
        base = st.session_state["base"]                        # 기준 시점(datetime)
        # 시각화나 출력용 timestamp: x_now(시간) → 초로 변환
        t_now = base + pd.to_timedelta(x_now * 3600, unit='s')  

        # 4) 시간 모델에 의한 예측값(만 단위) → 실제 조회수(원 단위)로 환산
        y_time_scaled = time_poly(x_now)                        # “만 단위 예측값”
        y_time_now = int(round(y_time_scaled * 10000))          # “원 단위 예측값”

        # 5) 광고효과 계산: 
        unit_won = 10000                                        # 1만 원을 1단위로 봄
        units = budget // unit_won                              # 지출한 만 원 단위 수
        y_ad = int(round(gamma * units))                        # 실제 ‘추가 조회수(원 단위)’
        #    ex) γ=2, budget=100만 → units=100 → y_ad=2×100=200회

        # 6) 광고효과 반영 후 현재 통합 예측 조회수
        y_total_now = y_time_now + y_ad                         # (원 단위)

        # 7) 결과 출력
        st.write(f"▶️ 시간 모델 예측 조회수 (광고 없음, 원 단위): **{y_time_now:,}회**")
        st.write(f"▶️ 광고비 효과 조회수 (현재 시점, 원 단위): **+{y_ad:,}회** (γ×{units})")
        st.write(f"▶️ **통합 예측 조회수 (현재 시점, 원 단위):** **{y_total_now:,}회**")

        # 8) 시각화
        fig2, ax2 = plt.subplots(figsize=(8, 4))

        # 8-1) 실제 데이터 산점도 (원본 조회수: 원 단위)
        df_global = st.session_state["df"]
        y_original = st.session_state["y"]
        ax2.scatter(df_global['timestamp'], y_original, alpha=0.5, label="실제 조회수")

        # 8-2) 회귀곡선: ts_curve_hours(0~x_now), 만 단위 예측 → 실제 조회수(원)로 환산
        ts_curve_hours = np.linspace(0, x_now, 200)              # 시간(시) 범위
        y_curve_scaled = time_poly(ts_curve_hours)              # 만 단위 예측값
        y_curve = y_curve_scaled * 10000                        # 원 단위 예측값
        x_curve_timestamp = base + pd.to_timedelta(ts_curve_hours * 3600, unit='s')
        ax2.plot(
            x_curve_timestamp,
            y_curve,
            color="orange", lw=2, linestyle="--",
            label="시간 모델 (광고 없음)"
        )

        # 8-3) 광고효과를 동일하게 더한 곡선 (원 단위)
        y_curve_with_ad = y_curve + y_ad                          # “각 시점마다 +광고효과”
        ax2.plot(
            x_curve_timestamp,
            y_curve_with_ad,
            color="red", lw=2,
            label="시간 모델 + 광고 효과"
        )

        # 8-4) 현재 시점 예측점 표시
        ax2.scatter(
            t_now, y_time_now,
            color="green", s=80,
            label="시간 모델 예측 (광고 없음)"
        )
        ax2.scatter(
            t_now, y_total_now,
            color="red", s=100,
            label="광고 적용 예측점 (원 단위)"
        )

        ax2.set_xlabel("시간")
        ax2.set_ylabel("조회수 (원 단위)")
        ax2.legend()
        plt.xticks(rotation=45)
        st.pyplot(fig2)

        # 9) 그래프 다운로드 버튼
        buf2 = io.BytesIO()
        fig2.savefig(buf2, format='png', dpi=150, bbox_inches='tight')
        buf2.seek(0)
        st.download_button(
            label="📷 광고비 적용 그래프 다운로드",
            data=buf2,
            file_name="budget_plot_with_ad_updated.png",
            mime="image/png"
        )

        # 10) γ(감마) 계수 해설서
        with st.expander("📖 γ(감마) 계수(광고효과)란?"):
            st.markdown("""
            - **γ(감마) 계수**:  
            - 광고비 **1만 원**을 투입했을 때 실제로 늘어나는 조회수를 의미합니다.  
            - 예를 들어, γ=2라면 ‘광고비 1만 원당 조회수 +2회’가 된다는 뜻입니다.  
            - 즉, γ × (광고비 ÷ 10,000) = 광고로 얻은 추가 조회수 (원 단위)
            
            - **왜 모든 시점에 광고효과를 더했을까?**  
            - 실제로 광고를 한 번 집행하면 그 시점 이후에도 노출이 이어지므로,  
                ‘광고 투입 시점 이후의 모든 예측 시간대’에 조회수가 높아집니다.  
            - 따라서 **광고 투입 시점 이후 전체 곡선**에 동일하게 조회수(원 단위)를 더해 주면,  
                학생들이 ‘광고가 곧바로 곡선을 위로 밀어 올린다’는 개념을 시각적으로 이해하기 쉽습니다.
            
            - **코드 해석 예시**:  
            1. γ=3, 광고비=50만 원 → units=50 → y_ad=3×50=150회 (원 단위)  
            2. 시간 모델에서 현재 시점 예측이 20,000회라면  
                – 광고 없음 예측 : 20,000회  
                – 광고 있음 예측 : 20,000 + 150 = 20,150회  
            3. 예를 들어 1시간 뒤 예측(광고 없음)이 21,000회라면  
                – 광고 있음 예측 : 21,000 + 150 = 21,150회
            
            - **만약 광고비를 두 배로 늘린다면?**  
            1. γ=2, 광고비=100만 원 → units=100 → y_ad=2×100=200회  
                → 추가 조회수도 두 배 증가  
            2. 시간 모델 곡선이 이전 대비 더 높게 올라가므로,  
                곡선 간격을 비교하며 광고비 효율을 분석할 수 있습니다.
            
            - **광고비 효율적 조건**:  
            - ‘광고 한 단위(1만 원)당 조회수 증가량(γ)’이 높을수록 효율이 좋습니다.  
            - 현실적으로 γ가 너무 높으면 비현실적이므로, 일정 이상 광고비를 늘려도  
                증가폭이 작아지는 **감쇠형 모델(예: 로그 함수)**을 추가로 고려할 수 있습니다.
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