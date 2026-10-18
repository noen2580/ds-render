"""PC에서 한 번 실행 — 수면 채널(Moonlit Hush)용 유튜브 업로드 토큰을 받는다.

    pip install google-auth-oauthlib google-api-python-client
    python get_channel_token.py

쇼츠와 같은 OAuth 클라이언트 ID·시크릿을 입력하고, 브라우저에서 구글 계정을 고른 뒤
**채널 선택 화면에서 Moonlit Hush 를 고른다**. 끝나면 인증된 채널 이름을 보여 주므로 맞는지 확인하고,
출력된 refresh token 을 GitHub 시크릿 SLEEP_YT_REFRESH_TOKEN 에 넣는다. 토큰은 파일로 저장하지 않는다.
"""
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube"]


def main():
    cid = input("OAuth Client ID: ").strip()
    secret = input("OAuth Client Secret: ").strip()
    flow = InstalledAppFlow.from_client_config(
        {"installed": {"client_id": cid, "client_secret": secret,
                       "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                       "token_uri": "https://oauth2.googleapis.com/token"}}, scopes=SCOPES)
    # 쇼츠 OAuth 클라이언트가 '웹 애플리케이션' 유형이면 등록된 주소(http://localhost:8080/)로만 돌아올 수 있다.
    # redirect_uri_mismatch 가 나면 콘솔의 '승인된 리디렉션 URI' 에 있는 포트를 인자로 준다: python get_channel_token.py 8090
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    cred = flow.run_local_server(host="localhost", port=port, access_type="offline", prompt="consent select_account")
    ch = build("youtube", "v3", credentials=cred).channels().list(part="snippet", mine=True).execute()
    items = ch.get("items") or []
    name = items[0]["snippet"]["title"] if items else "(채널 없음)"
    handle = items[0]["snippet"].get("customUrl", "") if items else ""
    print(f"\n인증된 채널: {name} {handle}")
    if "moonlit" not in (name + handle).lower():
        print("⚠ Moonlit Hush 가 아니다 — 다시 실행해 채널 선택 화면에서 Moonlit Hush 를 고를 것")
        return
    print("\nSLEEP_YT_REFRESH_TOKEN =", cred.refresh_token)


if __name__ == "__main__":
    main()
