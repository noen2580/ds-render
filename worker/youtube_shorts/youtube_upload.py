"""YouTube Data API v3 업로드 래퍼 — 저장된 OAuth 자격증명(credentials/youtube_oauth.json) 사용.
자격증명이 없으면 get_youtube_token.py를 먼저 실행해야 한다."""
import json
import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

CREDENTIALS_PATH = Path(__file__).parent / "credentials" / "youtube_oauth.json"
# upload 만으로는 업로드밖에 못 한다 — 올린 뒤 videos().list 로 확인하거나
# 설명란을 고치려면(videos().update) 관리 권한이 필요하다. 실측(2026-09-05):
# upload 스코프로 videos().list 를 부르면 403 insufficientPermissions 다.
# **이 값을 바꿔도 이미 발급된 토큰의 권한은 넓어지지 않는다** —
# get_youtube_token.py 로 한 번 다시 인증해야 실제로 반영된다.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def _load_credentials() -> Credentials:
    if not CREDENTIALS_PATH.exists():
        raise RuntimeError(
            f"{CREDENTIALS_PATH} 없음 — 먼저 get_youtube_token.py를 실행해 인증하세요."
        )
    data = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    return Credentials(
        token=None,
        refresh_token=data["refresh_token"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        # 재인증(reauth_youtube.py)으로 받은 권한 목록이 있으면 그걸 쓴다 — 받지 않은 권한을
        # 요청하면 갱신이 invalid_scope 로 실패한다.
        scopes=data.get("scopes") or SCOPES,
    )


# 수익창출(YPP) 기준 업로드 기본값. 환경변수로 덮어쓸 수 있다.
# 카테고리 26(노하우/스타일) — "OO 고르는 법·비교" 영상이라 People & Blogs(22)보다 맞고,
# 광고 매칭도 생활·쇼핑 쪽으로 붙는다.
CATEGORY_ID = os.environ.get("YT_CATEGORY_ID", "26")
LANGUAGE = os.environ.get("YT_LANGUAGE", "ko")
# 쿠팡 파트너스 수수료를 받는 영상이다 — 유튜브의 "유료 프로모션 포함" 표시를 켠다.
# 설명란 문구(공정위 고지)와 별개로 유튜브 정책상 체크가 필요하고, 빠지면 수익창출 심사에서
# 정책 위반으로 잡힐 수 있다. 끄려면 YT_PAID_PROMOTION=0.
PAID_PROMOTION = os.environ.get("YT_PAID_PROMOTION", "1") != "0"


def build_body(title: str, description: str, tags: list[str], privacy: str, synthetic: bool = False) -> dict:
    """videos().insert 본문. 테스트에서 자격증명 없이 확인할 수 있게 따로 뺐다.
    synthetic — AI 로 만든 사실적 장면(Veo 훅 장면)이 들어간 영상. 유튜브 정책상 '변경되거나 합성된
    콘텐츠'로 표시해야 한다(status.containsSyntheticMedia)."""
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags,
            "categoryId": CATEGORY_ID,
            "defaultLanguage": LANGUAGE,
            "defaultAudioLanguage": LANGUAGE,
        },
        "status": {
            "privacyStatus": privacy,
            # 아동용으로 표시되면 맞춤 광고·댓글이 꺼져 수익이 거의 안 난다.
            "selfDeclaredMadeForKids": False,
            "license": "youtube",
            "embeddable": True,
            "publicStatsViewable": True,
        },
    }
    if synthetic:
        body["status"]["containsSyntheticMedia"] = True
    return body


def upload(video_path: Path, title: str, description: str, tags: list[str],
           privacy: str = "unlisted", thumbnail: Path | None = None, synthetic: bool = False) -> dict:
    creds = _load_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    body = build_body(title, description, tags, privacy, synthetic)
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        _status, response = request.next_chunk()

    video_id = response["id"]

    # 썸네일 — 쇼츠 피드는 영상 첫 프레임을 쓰지만, **검색 결과·채널의 쇼츠 탭·
    # 구독 피드에서는 썸네일이 노출된다.** 실패해도 업로드 자체는 살린다.
    if thumbnail and Path(thumbnail).exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail), mimetype="image/png"),
            ).execute()
            log_ok = "썸네일 등록됨"
        except Exception as e:
            log_ok = f"썸네일 실패({e})"
        print(f"  {log_ok}")

    # 유료 프로모션 표시는 업로드와 따로 건다 — 실패해도(권한 부족 등) 업로드는 살린다.
    if PAID_PROMOTION:
        try:
            youtube.videos().update(
                part="paidProductPlacementDetails",
                body={"id": video_id,
                      "paidProductPlacementDetails": {"hasPaidProductPlacement": True}},
            ).execute()
            print("  유료 프로모션 표시됨")
        except Exception as e:
            print(f"  유료 프로모션 표시 실패({e})")

    # **올렸다는 응답이 왔다고 실제로 올라간 게 아니다.** 예약이 안 걸리거나 공개
    # 설정만 바뀌는 경우가 있어서, 올린 뒤 다시 조회해 상태를 확인한다.
    verified = _verify(youtube, video_id, privacy)

    return {"video_id": video_id, "url": f"https://youtu.be/{video_id}",
            "verified": verified}


def _verify(youtube, video_id: str, expect_privacy: str) -> dict:
    """업로드 결과를 되읽어 확인한다.

    uploadStatus 가 'processed'/'uploaded' 이고 privacyStatus 가 요청한 값과
    같아야 실제로 올라간 것이다. 다르면 그대로 돌려줘서 호출부가 알 수 있게 한다."""
    try:
        r = youtube.videos().list(part="status,snippet", id=video_id).execute()
        items = r.get("items") or []
        if not items:
            return {"ok": False, "reason": "조회 결과 없음"}
    except Exception as e:
        # 권한 부족은 업로드 실패가 아니다 — 구분해서 알려야 엉뚱한 데를 파지 않는다.
        if "insufficientPermissions" in str(e) or "insufficient authentication" in str(e):
            return {"ok": None, "reason":
                    "검증 건너뜀 — 저장된 토큰에 조회 권한이 없습니다. "
                    "get_youtube_token.py 를 한 번 다시 실행하면 활성화됩니다."}
        return {"ok": False, "reason": str(e)}

    try:
        st = items[0]["status"]
        ok = (st.get("uploadStatus") in ("uploaded", "processed")
              and st.get("privacyStatus") == expect_privacy)
        return {"ok": ok, "uploadStatus": st.get("uploadStatus"),
                "privacyStatus": st.get("privacyStatus"),
                "title": items[0]["snippet"].get("title", "")}
    except Exception as e:
        return {"ok": False, "reason": str(e)}
