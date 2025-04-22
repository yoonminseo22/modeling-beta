import streamlit as st
import requests
from urllib.parse import urlencode, parse_qs
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

st.set_page_config(page_title="📈 유튜브 조회수 분석기", layout="centered")

st.title("📈 유튜브 조회수 분석기")
st.subheader("Google 계정으로 로그인하고, 조회수를 분석하세요!")

# 🔐 secrets.toml에서 OAuth 정보
client_id = st.secrets["google_oauth"]["client_id"]
client_secret = st.secrets["google_oauth"]["client_secret"]
redirect_uri = "https://modeling-beta-1.streamlit.app"

# 🔑 로그인 URL 생성
auth_base = "https://accounts.google.com/o/oauth2/auth"
auth_params = {
    "client_id": client_id,
    "response_type": "code",
    "scope": "openid email profile",
    "redirect_uri": redirect_uri,
    "access_type": "offline",
    "prompt": "consent"
}
auth_url = f"{auth_base}?{urlencode(auth_params)}"

# 🔁 query param 체크
query_params = st.query_params

# 🔑 로그인한 적 없으면 로그인 버튼
if "credentials" not in st.session_state and "code" not in query_params:
    st.markdown(f"[🔐 Google 계정으로 로그인하기]({auth_url})")

# 🔄 로그인 후 돌아온 경우 (code 처리)
if "code" in query_params and "credentials" not in st.session_state:
    try:
        code = query_params["code"][0]
        token_url = "https://oauth2.googleapis.com/token"
        token_data = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code"
        }
        response = requests.post(token_url, data=token_data)
        token_info = response.json()

        # ⛔ 실패한 경우
        if "id_token" not in token_info:
            st.error(f"❌ 인증 실패: {token_info}")
        else:
            # ✅ 인증 성공
            idinfo = id_token.verify_oauth2_token(
                token_info["id_token"],
                google_requests.Request(),
                client_id
            )
            st.session_state["credentials"] = idinfo
            st.experimental_rerun()

    except Exception as e:
        st.error(f"❌ 인증 처리 중 오류 발생: {e}")

# ✅ 로그인 성공 시 사용자 정보 표시
if "credentials" in st.session_state:
    user = st.session_state["credentials"]
    st.success(f"👋 환영합니다, {user['name']} 님!")
    st.write(f"📧 이메일: {user['email']}")
    st.markdown("유튜브 링크를 붙여넣고 조회수 분석을 시작할 수 있어요.")

    # ✨ 유튜브 분석 기능 시작!
    st.header("🎥 유튜브 조회수 가져오기")

    YOUTUBE_API_KEY = st.secrets["youtube"]["api_key"]

    def extract_video_id(url):
        import re
        match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
        return match.group(1) if match else None

    def get_video_statistics(video_id):
        import requests
        url = f"https://www.googleapis.com/youtube/v3/videos?part=statistics&id={video_id}&key={YOUTUBE_API_KEY}"
        response = requests.get(url)
        if response.status_code == 200:
            items = response.json().get("items")
            if items:
                return items[0]["statistics"]
        return None

    youtube_url = st.text_input("📎 유튜브 링크를 입력하세요")

    if st.button("조회수 불러오기"):
        video_id = extract_video_id(youtube_url)
        if video_id:
            stats = get_video_statistics(video_id)
            if stats:
                st.success("✅ 조회 완료!")
                st.write(f"👁 조회수: {int(stats.get('viewCount', 0)):,}")
                st.write(f"👍 좋아요 수: {int(stats.get('likeCount', 0)):,}")
                st.write(f"💬 댓글 수: {int(stats.get('commentCount', 0)):,}")
            else:
                st.error("😢 영상 정보를 찾을 수 없습니다.")
        else:
            st.error("⛔ 유효한 유튜브 링크를 입력해주세요.")

