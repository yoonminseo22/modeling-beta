import streamlit as st
from google_auth_oauthlib.flow import Flow
from google.auth.transport import requests
from google.oauth2 import id_token

st.set_page_config(page_title="📈 유튜브 조회수 분석기", layout="centered")

st.title("📈 유튜브 조회수 분석기")
st.subheader("Google 계정으로 로그인하고, 조회수를 분석하세요!")

# 🔐 secrets.toml에서 클라이언트 정보 불러오기
client_id = st.secrets["google_oauth"]["client_id"]
client_secret = st.secrets["google_oauth"]["client_secret"]

REDIRECT_URI = "https://yoonminseo22-modeling-beta.streamlit.app"  # ← 앱 주소로 교체

# OAuth flow 객체 구성
flow = Flow.from_client_config(
    {
        "web": {
            "client_id": client_id,
            "project_id": "modeling-beta",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret,
            "redirect_uris": [REDIRECT_URI]
        }
    },
    scopes=[
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ],
    redirect_uri=REDIRECT_URI
)

auth_url, _ = flow.authorization_url(prompt="consent")

# 👉 로그인하지 않은 상태
if "credentials" not in st.session_state:
    st.markdown(f"[🔐 Google 계정으로 로그인하기]({auth_url})")

# 👈 로그인 후 redirect로 돌아왔을 때
query_params = st.query_params
if "code" in query_params:
    flow.fetch_token(code=query_params["code"][0])
    credentials = flow.credentials
    request = requests.Request()
    id_info = id_token.verify_oauth2_token(
        credentials._id_token, request, client_id
    )
    st.session_state["credentials"] = id_info
    st.experimental_rerun()

# ✅ 로그인 성공
if "credentials" in st.session_state:
    user = st.session_state["credentials"]
    st.success(f"👋 환영합니다, {user['name']} 님!")
    st.write(f"📧 이메일: {user['email']}")
    st.markdown("이제 유튜브 링크를 붙여넣고 조회수 분석을 시작할 수 있어요.")

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

    