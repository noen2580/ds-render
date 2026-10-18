"""유튜브 비공개 업로드 — 쇼츠와 같은 OAuth 자격증명(youtube_shorts/credentials/youtube_oauth.json)을 쓴다.

이 모듈은 **비공개(private)로만** 올린다. 공개·예약은 Somi 가 스튜디오에서 검수 후 직접 바꾼다.
쇼츠 업로더(youtube_upload.upload)를 그대로 쓰지 않는 이유: 그쪽은 카테고리 26·한국어·'유료 프로모션'
표시가 기본이라 음악 영상과 맞지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "youtube_shorts"))


def chapters(names: list[str], starts: list[float]) -> str:
    """설명란 챕터. 유튜브 규칙: 00:00 으로 시작, 3개 이상, 각 10초 이상."""
    lines, last = [], -999.0
    for name, s in zip(names, starts):
        if s - last < 10:
            continue
        h, m, sec = int(s // 3600), int(s % 3600 // 60), int(s % 60)
        stamp = f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
        lines.append(f"{stamp if lines else '00:00'} {name}")
        last = s
    return "\n".join(lines) if len(lines) >= 3 else ""


# 오디오 언어는 보내지 않는다: 'zxx'(언어 없음)는 API 가 400 invalidVideoMetadata 로 거절한다(2026-10-15 확인).


def build_body(preset: dict, description: str, title: str, tags: list[str] | None = None,
               localizations: dict | None = None) -> dict:
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags or [t for t in preset["tags"] if "{" not in t],
            "categoryId": preset["category_id"],
            "defaultLanguage": preset["language"],
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
            "license": "youtube",
            "embeddable": True,
            # AI 로 만든 사실적 음악 — 유튜브 '변경되거나 합성된 콘텐츠' 고지 대상
            "containsSyntheticMedia": True,
        },
    }
    if localizations:
        body["localizations"] = localizations
    return body


def upload_private(video: Path, body: dict, thumbnail: Path | None = None) -> dict:
    assert body["status"]["privacyStatus"] == "private", "이 업로더는 비공개만 올린다"
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    import youtube_upload

    yt = build("youtube", "v3", credentials=youtube_upload._load_credentials())
    from googleapiclient.errors import HttpError

    def insert(b):
        media = MediaFileUpload(str(video), chunksize=64 * 1024 * 1024, resumable=True, mimetype="video/mp4")
        req = yt.videos().insert(part=",".join(k for k in ("snippet", "status", "localizations") if k in b),
                                 body=b, media_body=media)
        resp = None
        while resp is None:
            status, resp = req.next_chunk()
            if status:
                print(f"  업로드 {status.progress() * 100:.0f}%")
        return resp

    loc = body.get("localizations") or {}
    try:
        resp = insert(body)
        loc_result = {"localizations": len(loc)}
    except HttpError as e:
        # 번역 하나가 유튜브 한도에 걸리면 업로드 전체가 거절된다(400 invalidVideoMetadata, 2026-10-15).
        # 번역 없이 올리고, 번역은 언어별로 따로 넣는다 — 번역 때문에 영상이 안 올라가는 일은 없게.
        if e.resp.status != 400 or not loc:
            raise
        print(f"번역 포함 업로드 거절 — 번역 없이 올린다: {e}")
        resp = insert({k: v for k, v in body.items() if k != "localizations"})
        try:
            ok, bad = update_localized(yt, resp["id"], body["snippet"], loc)
            loc_result = {"localizations": len(ok), "rejected_languages": bad}
        except Exception as e2:                 # noqa: BLE001 — 영상은 이미 올라갔다. 번역만 빠진 채로 둔다
            loc_result = {"localizations": 0, "localize_error": str(e2)[:200]}
    vid = resp["id"]
    thumb = None
    if thumbnail and thumbnail.exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumbnail), mimetype="image/jpeg")).execute()
            thumb = "ok"
        except Exception as e:                  # noqa: BLE001 — 썸네일은 채널 인증 전이면 실패한다
            thumb = f"실패: {e}"
    verified = youtube_upload._verify(yt, vid, "private")
    return {"video_id": vid, "url": f"https://youtu.be/{vid}", "studio": f"https://studio.youtube.com/video/{vid}/edit",
            "thumbnail": thumb, "verified": verified, **loc_result}


RETRY_SEC = 10


def add_to_playlist(video_id: str, title: str, description: str = "") -> dict:
    """채널의 재생목록(title)에 영상을 넣는다. 없으면 비공개 재생목록을 만든다(공개 전환은 Somi 가 스튜디오에서)."""
    from googleapiclient.discovery import build
    import youtube_upload

    yt = build("youtube", "v3", credentials=youtube_upload._load_credentials())
    pid, token = None, None
    while pid is None:
        r = yt.playlists().list(part="snippet", mine=True, maxResults=50, pageToken=token).execute()
        pid = next((p["id"] for p in r.get("items", []) if p["snippet"]["title"] == title), None)
        token = r.get("nextPageToken")
        if not token:
            break
    created = False
    if pid is None:
        pid = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": title, "description": description, "defaultLanguage": "en"},
            "status": {"privacyStatus": "private"}}).execute()["id"]
        created = True
    import time
    from googleapiclient.errors import HttpError
    for attempt in range(5):                    # 막 만든 재생목록·막 올린 영상은 잠깐 409 SERVICE_UNAVAILABLE 을 준다(2026-10-12)
        try:
            yt.playlistItems().insert(part="snippet", body={
                "snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
            break
        except HttpError as e:
            if e.resp.status not in (409, 500, 503) or attempt == 4:
                raise
            time.sleep(RETRY_SEC * (attempt + 1))
    print(f"재생목록 '{title}'에 넣음{'(새로 만듦, 비공개)' if created else ''}")
    return {"id": pid, "title": title, "created": created,
            "url": f"https://www.youtube.com/playlist?list={pid}"}


def _yt():
    from googleapiclient.discovery import build
    import youtube_upload
    return build("youtube", "v3", credentials=youtube_upload._load_credentials())


def channel_videos(yt) -> list[dict]:
    """이 채널에 올린 영상 전부(snippet, status, localizations)."""
    ch = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, tok = [], None
    while True:
        r = yt.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=50, pageToken=tok).execute()
        ids += [i["contentDetails"]["videoId"] for i in r.get("items", [])]
        tok = r.get("nextPageToken")
        if not tok:
            break
    out = []
    for i in range(0, len(ids), 50):
        out += yt.videos().list(part="snippet,status,localizations", id=",".join(ids[i:i + 50])).execute()["items"]
    return out


def update_localized(yt, video_id: str, snippet: dict, loc: dict) -> tuple[dict, list[str]]:
    """제목·설명 번역(localizations)을 넣는다. 유튜브는 언어 하나라도 한도를 넘으면 전체를 거절(400)하므로,
    그때는 언어를 하나씩 더해 가며 받아 주는 것만 남긴다. (받은 번역, 거절된 언어 코드) 를 돌려준다."""
    from googleapiclient.errors import HttpError

    def put(lz):
        yt.videos().update(part="snippet,localizations" if lz else "snippet",
                           body={"id": video_id, "snippet": snippet, **({"localizations": lz} if lz else {})}).execute()
    try:
        put(loc)
        return loc, []
    except HttpError as e:
        if e.resp.status != 400 or not loc:
            raise
    ok, bad = {}, []
    for code, v in loc.items():
        try:
            put({**ok, code: v})
            ok[code] = v
        except HttpError as e:
            if e.resp.status != 400:
                raise
            bad.append(code)
    if not ok:
        raise RuntimeError(f"번역이 모두 거절됨: {', '.join(bad)}")
    return ok, bad


MIN_LOCALIZATIONS = 5          # 이보다 적으면 번역이 안 된 영상으로 본다


def localize_existing(localize_fn, apply: bool, yt=None) -> list[dict]:
    """이미 올린 영상에 번역 제목·설명과 '언어 없음' 오디오를 넣는다(공개 여부는 건드리지 않는다).
    apply 가 아니면 상태만 보고한다. localize_fn(title, description) -> localizations."""
    yt = yt or _yt()
    rows = []
    for v in channel_videos(yt):
        sn = v["snippet"]
        row = {"id": v["id"], "title": sn["title"], "privacy": v["status"]["privacyStatus"],
               "audio": sn.get("defaultAudioLanguage"), "localizations": len(v.get("localizations") or {})}
        have = v.get("localizations") or {}
        if apply and len(have) < MIN_LOCALIZATIONS:
            # 기본 언어(en) 하나만 있는 영상이 많다 — 번역이 모자라면 새로 만들어 기존 것과 합친다
            loc = {**have, **localize_fn(sn["title"], sn.get("description", ""))}
            nsn = {k: sn[k] for k in ("title", "description", "tags", "categoryId", "defaultAudioLanguage") if k in sn}
            nsn.update(defaultLanguage=sn.get("defaultLanguage") or "en")
            try:
                ok, bad = update_localized(yt, v["id"], nsn, loc)
            except Exception as e:              # noqa: BLE001 — 한 영상이 실패해도 나머지는 계속, 보고서에 남긴다
                row.update(error=str(e)[:200])
                if not any(r.get("updated") for r in rows):
                    raise                       # 첫 영상부터 거절되면 공통 문제 — 할당량 낭비 전에 멈춘다
            else:
                row.update(updated=True, localizations=len(ok), rejected=bad)
        rows.append(row)
    return rows


def playlists_status(yt=None) -> list[dict]:
    yt = yt or _yt()
    out, tok = [], None
    while True:
        r = yt.playlists().list(part="snippet,status", mine=True, maxResults=50, pageToken=tok).execute()
        out += [{"title": p["snippet"]["title"], "privacy": p["status"]["privacyStatus"]} for p in r.get("items", [])]
        tok = r.get("nextPageToken")
        if not tok:
            break
    return out


def channel_status(yt=None) -> dict:
    """채널 기본 언어·국가·키워드·번역 상태(읽기만)."""
    yt = yt or _yt()
    ch = yt.channels().list(part="snippet,brandingSettings,localizations", mine=True).execute()["items"][0]
    b = ch.get("brandingSettings", {}).get("channel", {})
    return {"title": ch["snippet"]["title"], "country": b.get("country"), "defaultLanguage": b.get("defaultLanguage"),
            "keywords": b.get("keywords", ""), "localizations": sorted((ch.get("localizations") or {}).keys())}
