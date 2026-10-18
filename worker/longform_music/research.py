"""조회수가 높은 장시간(수면) 음악 영상의 구조를 모아 분석한다 — 우리 영상 형식을 정하는 근거.

    python longform_music/research.py --out longform_music/research/2026-10-11 [--gemini 10]

1) YouTube Data API(search.list → videos.list → channels.list)로 검색어 여러 개의 1시간 넘는 영상을 모은다.
   조회수, 하루 평균 조회수, 길이, 제목 형식, 설명(챕터·문구), 태그, 채널 구독자.
2) 길이대·제목 단어·썸네일별로 하루 평균 조회수를 비교해 summary.md 를 쓴다.
3) 상위 영상 썸네일을 한 장으로 모은다(thumbs_*.jpg).
4) --gemini N: 상위 N개 영상의 처음 2분·1시간 지점을 Gemini 가 직접 보고 화면·소리 구성을 적는다
   (Vertex generateContent, fileData 에 유튜브 주소 — 공개 영상만).

인증: 업로드와 같은 OAuth 토큰(youtube 권한, search.list 는 호출당 100 쿼터). Gemini 는 VERTEX_API_KEY.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "youtube_shorts"))

QUERIES = [
    "sleep music", "deep sleep music", "relaxing sleep music", "12 hours sleep music", "10 hours sleep music",
    "8 hours sleep music", "3 hours sleep music", "sleep music for insomnia", "fall asleep fast music",
    "sleep music rain sounds", "piano sleep music", "delta waves sleep music", "healing sleep music",
    "sleep music black screen",
]
WORDS = {  # 제목에 들어 있으면 표시 — 하루 조회수와 비교
    "rain": r"\brain", "piano": r"piano", "delta": r"delta", "insomnia": r"insomnia",
    "fall_asleep": r"fall (?:a)?sleep|fall into", "instantly": r"instant|fast|quick|in \d+ min|under \d+",
    "black_screen": r"black screen|dark screen|screen off", "healing": r"heal", "stress": r"stress|anxiety",
    "hz": r"\d{3} ?hz", "relax": r"relax", "calm": r"calm", "meditation": r"meditat", "ocean": r"ocean|wave",
    "space": r"space|cosmic|galaxy|star", "night": r"night|moon", "baby": r"baby|lullab",
    "hours": r"\d+\s*(?:hours?|hrs?)\b", "deep_sleep": r"deep sleep", "emoji": r"[\U0001F300-\U0001FAFF☀-➿]",
    "pipe": r"\|", "caps_word": r"\b[A-Z]{4,}\b",
}


def iso_seconds(s: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def chapters(desc: str) -> int:
    return len(re.findall(r"(?m)^\s*\(?(?:\d{1,2}:)?\d{1,2}:\d{2}\)?\s+\S", desc or ""))


def features(v: dict, subs: dict, now: datetime) -> dict:
    sn, st, cd = v["snippet"], v.get("statistics", {}), v["contentDetails"]
    title = sn.get("title", "")
    pub = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
    age = max((now - pub).days, 1)
    views = int(st.get("viewCount", 0))
    sec = iso_seconds(cd.get("duration", ""))
    row = {
        "id": v["id"], "url": f"https://youtu.be/{v['id']}", "title": title, "channel": sn.get("channelTitle", ""),
        "subs": subs.get(sn.get("channelId"), 0), "published": sn["publishedAt"][:10], "age_days": age,
        "hours": round(sec / 3600, 2), "views": views, "views_per_day": round(views / age),
        "likes": int(st.get("likeCount", 0) or 0), "comments": int(st.get("commentCount", 0) or 0),
        "title_len": len(title), "tags": len(sn.get("tags") or []), "desc_len": len(sn.get("description") or ""),
        "chapters": chapters(sn.get("description", "")), "lang": sn.get("defaultAudioLanguage", ""),
        "thumb": ((sn.get("thumbnails") or {}).get("high") or {}).get("url", ""),
        "desc_head": " ".join((sn.get("description") or "").split())[:300],
    }
    for k, rx in WORDS.items():
        row[f"w_{k}"] = int(bool(re.search(rx, title, re.I if k not in ("caps_word",) else 0)))
    return row


def collect(yt, queries: list[str], per_query: int = 50) -> list[dict]:
    ids: list[str] = []
    for q in queries:
        for order in ("viewCount", "relevance"):
            r = yt.search().list(part="id", q=q, type="video", videoDuration="long", maxResults=per_query,
                                 order=order, relevanceLanguage="en", safeSearch="none").execute()
            ids += [i["id"]["videoId"] for i in r.get("items", []) if i["id"].get("videoId")]
            time.sleep(0.2)
    ids = list(dict.fromkeys(ids))
    vids = []
    for i in range(0, len(ids), 50):
        vids += yt.videos().list(part="snippet,contentDetails,statistics", id=",".join(ids[i:i + 50])).execute()["items"]
    ch = list({v["snippet"]["channelId"] for v in vids})
    subs = {}
    for i in range(0, len(ch), 50):
        for c in yt.channels().list(part="statistics", id=",".join(ch[i:i + 50])).execute()["items"]:
            subs[c["id"]] = int(c["statistics"].get("subscriberCount", 0) or 0)
    now = datetime.now(timezone.utc)
    return [features(v, subs, now) for v in vids]


def median(xs):
    xs = [x for x in xs if x is not None]
    return int(statistics.median(xs)) if xs else 0


BUCKETS = [(1, 2.5, "1~2.5시간"), (2.5, 4, "3시간대"), (4, 7.5, "4~7시간"), (7.5, 9, "8시간대"),
           (9, 11, "10시간대"), (11, 13, "12시간대"), (13, 999, "13시간 이상")]


def summarize(rows: list[dict]) -> tuple[dict, str]:
    rows = [r for r in rows if r["hours"] >= 1]
    vpd = sorted(r["views_per_day"] for r in rows)
    top_cut = vpd[int(len(vpd) * 0.9)] if vpd else 0
    top = [r for r in rows if r["views_per_day"] >= top_cut]
    by_len = []
    for lo, hi, name in BUCKETS:
        b = [r for r in rows if lo <= r["hours"] < hi]
        by_len.append({"length": name, "videos": len(b), "median_views_per_day": median([r["views_per_day"] for r in b]),
                       "median_views": median([r["views"] for r in b]), "share_of_top10pct": sum(1 for r in top if lo <= r["hours"] < hi)})
    words = []
    for k in WORDS:
        w = [r["views_per_day"] for r in rows if r[f"w_{k}"]]
        wo = [r["views_per_day"] for r in rows if not r[f"w_{k}"]]
        if len(w) >= 5 and len(wo) >= 5:
            words.append({"word": k, "videos": len(w), "median_with": median(w), "median_without": median(wo),
                          "lift": round(median(w) / max(median(wo), 1), 2),
                          "top10pct_share": round(sum(r[f"w_{k}"] for r in top) / max(len(top), 1), 2)})
    words.sort(key=lambda x: -x["lift"])
    s = {"videos": len(rows), "top10pct_views_per_day_cut": top_cut,
         "median_hours_all": round(statistics.median([r["hours"] for r in rows]), 1) if rows else 0,
         "median_hours_top10pct": round(statistics.median([r["hours"] for r in top]), 1) if top else 0,
         "median_title_len_top": median([r["title_len"] for r in top]),
         "chapters_share_top": round(sum(1 for r in top if r["chapters"] >= 3) / max(len(top), 1), 2),
         "by_length": by_len, "title_words": words}
    md = [f"# 장시간 수면 음악 — 유튜브 상위 영상 분석 ({datetime.now(timezone.utc):%Y-%m-%d})", "",
          f"- 1시간 넘는 영상 {len(rows)}개(검색어 {len(QUERIES)}개 × 조회수순·관련도순)",
          f"- 상위 10% 기준: 하루 조회수 {top_cut:,} 이상 ({len(top)}개)",
          f"- 길이 중앙값: 전체 {s['median_hours_all']}시간, 상위 10% {s['median_hours_top10pct']}시간",
          f"- 상위 10% 제목 길이 중앙값 {s['median_title_len_top']}자, 챕터 3개 이상 {int(s['chapters_share_top'] * 100)}%", "",
          "## 길이대별", "", "| 길이 | 영상 | 하루 조회수 중앙값 | 조회수 중앙값 | 상위 10% 개수 |", "|---|---|---|---|---|"]
    md += [f"| {b['length']} | {b['videos']} | {b['median_views_per_day']:,} | {b['median_views']:,} | {b['share_of_top10pct']} |"
           for b in by_len]
    md += ["", "## 제목 단어별(하루 조회수 중앙값, 있음/없음)", "", "| 단어 | 영상 | 있음 | 없음 | 배수 | 상위 10% 중 비율 |",
           "|---|---|---|---|---|---|"]
    md += [f"| {w['word']} | {w['videos']} | {w['median_with']:,} | {w['median_without']:,} | {w['lift']} | {int(w['top10pct_share'] * 100)}% |"
           for w in words]
    md += ["", "## 하루 조회수 상위 40개", "", "| # | 하루 조회수 | 조회수 | 길이 | 채널(구독자) | 제목 |", "|---|---|---|---|---|---|"]
    for i, r in enumerate(sorted(rows, key=lambda r: -r["views_per_day"])[:40], 1):
        md.append(f"| {i} | {r['views_per_day']:,} | {r['views']:,} | {r['hours']} | {r['channel']} ({r['subs']:,}) | "
                  f"[{r['title'][:90].replace('|', '/')}]({r['url']}) |")
    return s, "\n".join(md) + "\n"


def contact_sheet(rows: list[dict], out: Path, n: int = 30, cols: int = 5) -> Path | None:
    """썸네일 n개를 번호를 붙여 한 장으로(번호 = summary.md 상위 표 순서)."""
    import httpx
    tmp = out.parent / f".{out.stem}"
    tmp.mkdir(exist_ok=True)
    k = 0
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        for r in rows[:n]:
            u = r["thumb"] or f"https://i.ytimg.com/vi/{r['id']}/hqdefault.jpg"
            try:
                resp = c.get(u)
                if resp.status_code == 200:
                    (tmp / f"{k:03d}.jpg").write_bytes(resp.content)
                    k += 1
            except Exception:  # noqa: BLE001
                continue
    if not k:
        return None
    rows_n = (k + cols - 1) // cols
    vf = (f"scale=480:270:force_original_aspect_ratio=increase,crop=480:270,"
          f"drawtext=text='%{{eif\\:n+1\\:d}}':x=8:y=8:fontsize=34:fontcolor=yellow:box=1:boxcolor=black@0.6,"
          f"tile={cols}x{rows_n}:padding=4:color=black")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-start_number", "0", "-i", str(tmp / "%03d.jpg"), "-vf", vf,
                    "-frames:v", "1", "-q:v", "3", str(out)], check=True)
    for f in tmp.glob("*.jpg"):
        f.unlink()
    tmp.rmdir()
    return out


GEMINI_PROMPT = """You are analysing a long YouTube sleep/relaxing music video for a producer who wants to copy what works.
You see two clips: the first 2 minutes, and about 1 hour in (if the video is that long).
Answer ONLY with JSON:
{"visual_type": "static image | slow animated loop | live footage | black/dark screen | slideshow | other",
 "visual_subject": "what is shown",
 "motion": "none | subtle (rain, stars, flicker) | camera move | strong",
 "on_screen_text": "text shown on screen during playback, or none",
 "intro": "what happens in the first 30 seconds (logo, voice, text, fade in...)",
 "audio": "instruments / nature sounds / binaural etc",
 "voice": "any speech or singing? where?",
 "changes_at_1h": "how picture or sound differs at ~1 hour (e.g. screen goes dark, same loop)",
 "brightness": "bright | medium | dark | very dark",
 "colour_palette": "main colours",
 "what_makes_it_work": "one sentence"}"""


def gemini_analyse(rows: list[dict], client, auths, model: str = "gemini-2.5-flash") -> list[dict]:
    out = []
    for r in rows:
        parts = [{"fileData": {"fileUri": f"https://www.youtube.com/watch?v={r['id']}", "mimeType": "video/*"},
                  "videoMetadata": {"startOffset": "0s", "endOffset": "120s", "fps": 0.5}}]
        if r["hours"] >= 1.2:
            parts.append({"fileData": {"fileUri": f"https://www.youtube.com/watch?v={r['id']}", "mimeType": "video/*"},
                          "videoMetadata": {"startOffset": "3600s", "endOffset": "3660s", "fps": 0.5}})
        body = {"contents": [{"role": "user", "parts": [*parts, {"text": GEMINI_PROMPT}]}],
                "generationConfig": {"responseMimeType": "application/json", "mediaResolution": "MEDIA_RESOLUTION_LOW"}}
        got, err = None, ""
        for h, project in auths:
            urls = []
            if project:
                urls.append(f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global"
                            f"/publishers/google/models/{model}:generateContent")
            if "x-goog-api-key" in h or not project:
                urls.append(f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent")
            for u in urls:
                resp = client.post(u, headers={**h, "Content-Type": "application/json"}, json=body, timeout=300)
                if resp.status_code == 200:
                    try:
                        txt = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                        got = json.loads(txt)
                    except Exception as e:  # noqa: BLE001
                        err = f"parse {e}"
                        continue
                    break
                err = f"{resp.status_code} {resp.text[:200]}"
            if got:
                break
        out.append({"id": r["id"], "title": r["title"], "views_per_day": r["views_per_day"], "hours": r["hours"],
                    **(got or {"error": err})})
        print(f"  gemini {r['id']}: {'ok' if got else err[:120]}")
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", required=True)
    p.add_argument("--gemini", type=int, default=0, help="상위 몇 개를 Gemini 로 직접 볼지")
    p.add_argument("--queries", default="", help="쉼표로 검색어(기본 목록 대신)")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    from googleapiclient.discovery import build
    import youtube_upload
    yt = build("youtube", "v3", credentials=youtube_upload._load_credentials())
    queries = [q.strip() for q in a.queries.split(",") if q.strip()] or QUERIES
    rows = collect(yt, queries)
    rows.sort(key=lambda r: -r["views_per_day"])
    with open(out / "videos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    s, md = summarize(rows)
    long_rows = [r for r in rows if r["hours"] >= 1]
    contact_sheet(long_rows, out / "thumbs_top30_by_views_per_day.jpg")
    contact_sheet(sorted(long_rows, key=lambda r: -r["views"]), out / "thumbs_top30_by_views.jpg")
    if a.gemini:
        import httpx
        import veo
        with httpx.Client(follow_redirects=True) as c:
            g = gemini_analyse([r for r in long_rows if r["hours"] >= 2.5][: a.gemini], c, veo._vertex_auths())
        (out / "gemini.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
        md += "\n## Gemini 가 직접 본 상위 영상(처음 2분 · 1시간 지점)\n\n"
        for x in g:
            md += f"- **{x['title'][:80]}** ({x['hours']}h, 하루 {x['views_per_day']:,}): " + \
                  ", ".join(f"{k}={v}" for k, v in x.items() if k not in ("id", "title", "views_per_day", "hours")) + "\n"
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "summary.md").write_text(md, encoding="utf-8")
    print(md[:3000])


if __name__ == "__main__":
    main()
