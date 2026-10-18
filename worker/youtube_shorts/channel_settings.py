"""유튜브 채널 프로필(설명·키워드·국가·언어)을 보고 바꾼다.

    python channel_settings.py            # 현재 값과 channel_profile.json 의 차이만 보여준다
    python channel_settings.py --apply    # 차이를 실제 채널에 반영한다

채널에 공개적으로 바로 보이는 변경이라 기본은 보기만 한다. 반영하려면 --apply 를 줘야 한다.
brandingSettings 는 통째로 덮어쓰는 API 라서, 현재 값을 읽어 바꿀 칸만 고친 뒤 되돌려 보낸다
(그대로 보내지 않으면 채널 제목·예고편 등 다른 칸이 지워진다).

API 로 못 바꾸는 것(스튜디오에서 직접): 채널 이름·핸들, 프로필 사진, 연락처 이메일,
채널 단위 '아동용 아님' 설정, 수익창출 신청."""
import argparse
import json
import shlex
import sys
from pathlib import Path

from googleapiclient.discovery import build

from youtube_upload import _load_credentials

PROFILE_PATH = Path(__file__).parent / "channel_profile.json"


def keywords_to_str(words: list[str]) -> str:
    """API 의 keywords 는 공백 구분 문자열이다. 공백이 든 키워드는 따옴표로 묶는다."""
    return " ".join(f'"{w}"' if " " in w else w for w in words)


def keywords_from_str(s: str) -> list[str]:
    try:
        return shlex.split(s or "")
    except ValueError:
        return (s or "").split()


def desired_changes(current: dict, profile: dict) -> dict:
    """현재 brandingSettings.channel 과 프로필을 비교해 바뀌는 칸만 {칸: (현재, 목표)} 로 돌려준다."""
    want = {
        "description": profile.get("description"),
        "keywords": keywords_to_str(profile["keywords"]) if profile.get("keywords") else None,
        "country": profile.get("country"),
        "defaultLanguage": profile.get("defaultLanguage"),
    }
    out = {}
    for k, v in want.items():
        if v is None:
            continue
        cur = current.get(k)
        if k == "keywords":
            if keywords_from_str(cur or "") == keywords_from_str(v):
                continue
        elif (cur or "") == v:
            continue
        out[k] = (cur, v)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="차이를 실제 채널에 반영")
    ap.add_argument("--profile", default=str(PROFILE_PATH))
    args = ap.parse_args()

    profile = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    youtube = build("youtube", "v3", credentials=_load_credentials())
    r = youtube.channels().list(part="snippet,brandingSettings,status,statistics", mine=True).execute()
    items = r.get("items") or []
    if not items:
        sys.exit("이 계정에 연결된 채널이 없습니다.")
    ch = items[0]
    branding = ch.get("brandingSettings") or {}
    current = branding.get("channel") or {}
    st, stats = ch.get("status") or {}, ch.get("statistics") or {}

    print(f"채널: {ch['snippet'].get('title')} ({ch.get('id')}) {ch['snippet'].get('customUrl', '')}")
    print(f"구독자 {stats.get('subscriberCount')} · 조회수 {stats.get('viewCount')} · 영상 {stats.get('videoCount')}")
    print(f"아동용 설정: {st.get('madeForKids')} · 공개 상태: {st.get('privacyStatus')} · "
          f"장편 업로드: {st.get('longUploadsStatus')}")

    changes = desired_changes(current, profile)
    if not changes:
        print("\n바꿀 내용 없음 — 이미 프로필과 같습니다.")
        return
    for k, (cur, new) in changes.items():
        print(f"\n[{k}]\n  현재: {cur!r}\n  변경: {new!r}")

    if not args.apply:
        print("\n(보기만 했습니다. 반영하려면 --apply)")
        return

    new_channel = {**current, **{k: new for k, (_cur, new) in changes.items()}}
    youtube.channels().update(
        part="brandingSettings",
        body={"id": ch["id"], "brandingSettings": {**branding, "channel": new_channel}},
    ).execute()
    print("\n반영했습니다. 다시 실행하면 '바꿀 내용 없음'이 나와야 합니다.")


if __name__ == "__main__":
    main()
