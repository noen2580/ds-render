"""정보 전달형 쇼츠 한 편 — 대본(JSON) → 장면별 TTS → 매니페스트 → Remotion 렌더 → 품질 검사 → (선택) 업로드.

왜 새 경로인가 (2026-09-28)
---------------------------
기존 캐릭터 쇼츠(make_character_short.py)는 35초 내내 로봇이 화면 가운데 서서 블로그
문장을 읽었다. 무음으로 보면 아무것도 알 수 없었고, 자막은 두 어절 조각이었다.
이 경로는 **장면이 곧 정보**다: 훅 질문 → 판단 기준 3개 → 조건별 결론 → 프로필 안내.

입력은 NAS 의 `tools/export_shorts_post.py` 가 만든 JSON 하나다(대본 포함). 대본은 NAS
의 AI 라우터가 블로그 본문에 **실제로 있는 내용만**으로 쓴다(`modules/content/shorts_script.py`).

업로드 기본값은 **비공개(private)** 다. 품질 검사와 장면 모음(sheet)을 사람이 보고
공개로 바꾼다 — 자동 공개는 영상 완성도를 확인한 뒤에 켠다.

사용:
    python make_explainer_short.py --post-json tmp/post_700.json            # 렌더 + 검사
    python make_explainer_short.py --post-json tmp/post_700.json --upload   # + 비공개 업로드
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
REMOTION = HERE.parent / "remotion_shorts"
PUBLIC = REMOTION / "public"
UPLOADED = HERE / "uploaded"

FPS = 30
GAP = 0.35            # 장면 사이 숨
TAIL = 1.4            # 마지막 장면 뒤 여운(CTA 가 읽힐 시간)
MAX_TOTAL = 58.0      # 쇼츠 인식 한도(60초) 안쪽
CAPTION_MAX = 17      # 자막 한 줄 글자 수 — 이보다 길면 다음 줄로 넘긴다
NL = chr(10)          # 자막 줄바꿈(한 큐에 최대 두 줄)
VOICE = "ko-KR-SunHiNeural"
RATE = "+4%"          # 정보 전달형은 기본(-8%)보다 살짝 빠르게 — 늘어지면 이탈한다


def _resolve(exe: str) -> str:
    return shutil.which(exe) or shutil.which(exe + ".cmd") or exe


def run(cmd: list, cwd: Path | None = None) -> None:
    cmd = [_resolve(str(cmd[0]))] + [str(c) for c in cmd[1:]]
    r = subprocess.run(cmd, cwd=cwd)
    if r.returncode != 0:
        raise SystemExit(f"실패(exit {r.returncode}): {' '.join(cmd[:4])}")


def _duration(path: Path) -> float:
    out = subprocess.run([_resolve("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def scenes_from_script(script: dict) -> list[dict]:
    out = [{"type": "hook", "index": 0, **script["hook"]}]
    out += [{"type": "point", "index": i + 1, **p} for i, p in enumerate(script["points"])]
    out += [{"type": "answer", "index": 0, **script["answer"]},
            {"type": "cta", "index": 0, **script["cta"]}]
    return out


def split_caption(text: str, max_len: int = CAPTION_MAX) -> list[str]:
    """문장 → 자막 줄. 구두점에서 먼저 끊고, 긴 구간은 어절 경계에서 max_len 안으로 나눈다.
    두 어절 조각("하나만 보고") 같은 짧은 줄이 나오지 않게 짧은 꼬리는 앞 줄에 붙인다."""
    parts = [p.strip() for p in re.split(r"(?<=[.?!,])\s+", text.strip()) if p.strip()]
    lines: list[str] = []
    for part in parts:
        cur = ""
        for w in part.split():
            if cur and len(cur) + 1 + len(w) > max_len:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            lines.append(cur)
    merged: list[str] = []
    for ln in lines:
        if merged and len(ln) <= 5 and len(merged[-1]) + 1 + len(ln) <= max_len + 4:
            merged[-1] = f"{merged[-1]} {ln}"
        else:
            merged.append(ln)
    return merged


MIN_CUE = 0.7  # qa() 는 0.6초 미만 자막을 실패로 본다 — "거예요." 같은 짧은 꼬리가 걸렸었다.


def _ensure_min_cue(durs: list[float], floor: float = MIN_CUE) -> list[float]:
    """짧은 자막 큐에 가장 긴 큐의 시간을 빌려줘 최소 노출 시간을 보장한다(총합 유지)."""
    out = list(durs)
    for i, d in enumerate(out):
        if d < floor:
            j = max(range(len(out)), key=lambda k: out[k])
            need = floor - d
            if j != i and out[j] - need >= floor:
                out[j] -= need
                out[i] = floor
    return out


def job_key(post: dict) -> str:
    """출력 폴더·파일 이름. 블로그 쇼츠(post id)와 상품 쇼츠(번호)가 같은 숫자를 쓸 수 있어 접두어로 나눈다."""
    return f"pr_{int(post['id'])}" if post.get("kind") == "product" else f"ex_{int(post['id'])}"


# 모든 쇼츠 화면 하단에 작게 — 공정위 추천·보증 심사지침은 영상 **안에서** 알리라고 한다(설명란만으론 부족).
DISCLOSURE = "쿠팡 파트너스 활동으로 수수료를 받을 수 있어요"


def build_assets(post: dict, out_dir: Path, voice: str, rate: str) -> dict:
    import tts_edge
    import bgm as bgm_lib

    out_dir.mkdir(parents=True, exist_ok=True)
    rel = out_dir.relative_to(PUBLIC).as_posix()
    script = post["shorts_script"]
    scenes = scenes_from_script(script)

    # 1) 장면별 TTS → 길이 측정 → 무음 패딩을 붙여 이어 붙인다.
    t = 0.0
    seg_files = []
    for i, sc in enumerate(scenes):
        wav = out_dir / f"say_{i}.mp3"
        tts_edge.synthesize(sc["say"], wav, voice=voice, rate=rate)
        say_dur = _duration(wav)
        pad = TAIL if sc["type"] == "cta" else GAP
        sc["_say"] = say_dur
        sc["start"], sc["duration"] = round(t, 3), round(say_dur + pad, 3)
        padded = out_dir / f"seg_{i}.wav"
        run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-af", f"apad=pad_dur={pad}",
             "-ar", "44100", "-ac", "2", padded])
        seg_files.append(padded)
        t += say_dur + pad
    total = round(t, 3)
    if total > MAX_TOTAL:
        raise SystemExit(f"길이 {total:.1f}s > {MAX_TOTAL}s — 대본을 줄여야 한다")

    lst = out_dir / "concat.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in seg_files), encoding="utf-8")
    narration = out_dir / "narration.m4a"
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
         "-c:a", "aac", "-b:a", "192k", narration], cwd=out_dir)

    # 2) BGM — 기존 모듈 재사용(글마다 고정 트랙, 내레이션 아래로 덕킹).
    audio_name, credit = narration.name, ""
    track = bgm_lib.pick(int(post["id"]))
    if track:
        mixed = out_dir / "mix.m4a"
        if bgm_lib.mix(narration, mixed, track, total, out_dir):
            audio_name, credit = mixed.name, bgm_lib.credit(track)

    # 2-1) 음량 — 쇼츠 권장 -14 LUFS(피크 -1.5dB)로 맞춘다. 첫 판은 평균 -19dB 라
    #      다른 영상 사이에서 작게 들렸다.
    loud = out_dir / "final.m4a"
    run(["ffmpeg", "-v", "error", "-y", "-i", out_dir / audio_name,
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "44100", "-c:a", "aac", "-b:a", "192k", loud])
    audio_name = loud.name

    # 3) 대표 상품 사진 — 블로그 쇼츠는 훅에만, 상품 쇼츠는 모든 장면에(아래 매니페스트).
    hero = ""
    try:
        products = json.loads(post.get("product_data") or "[]")
    except Exception:
        products = []
    for p in products[:3]:
        url = p.get("productImage") or p.get("image")
        if not url:
            continue
        try:
            import httpx
            r = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            (out_dir / "hero.jpg").write_bytes(r.content)
            hero = f"{rel}/hero.jpg"
            break
        except Exception as e:
            print(f"  상품 사진 받기 실패: {e}")

    # 3-1) 상품 쇼츠 훅 장면 — Veo 로 '불편한 상황' 클립(상품은 나오지 않는다). 실패하면 사진만으로 간다.
    is_product = post.get("kind") == "product"
    hook_video = ""
    if is_product and script.get("hook_scene"):
        import veo
        if veo.enabled():
            got = veo.generate(script["hook_scene"], out_dir / "hook.mp4",
                               seconds=veo.clip_seconds(scenes[0]["duration"]))
            hook_video = f"{rel}/hook.mp4" if got else ""

    # 4) 자막 큐 — 한 번에 **두 줄까지** 보여 준다(한 줄씩 넘기면 문장이 중간에 잘린다).
    #    장면 안에서 글자 수 비율로 시간을 나눈다.
    cues = []
    for sc in scenes:
        one = split_caption(sc["say"])
        lines = [NL.join(one[i:i + 2]) for i in range(0, len(one), 2)]
        n = sum(len(x.replace(NL, "")) for x in lines) or 1
        durs = [sc["_say"] * len(ln.replace(NL, "")) / n for ln in lines]
        durs = _ensure_min_cue(durs)
        c = sc["start"] + 0.05
        for ln, d in zip(lines, durs):
            cues.append({"text": ln, "start": round(c, 3), "end": round(c + d, 3)})
            c += d

    code = f"#{int(post['code'])}" if is_product else ""
    manifest = {
        "kind": "explainer", "postId": int(post["id"]), "fps": FPS, "width": 1080, "height": 1920,
        "disclosure": DISCLOSURE,
        "totalDuration": total, "audio": f"{rel}/{audio_name}",
        "category": (script.get("meta") or {}).get("category") or post.get("product_category") or "",
        "scenes": [{"type": sc["type"], "index": sc["index"], "start": sc["start"],
                    "duration": sc["duration"],
                    "headline": sc["screen"]["headline"], "sub": sc["screen"].get("sub", ""),
                    "highlight": sc.get("keyword_highlight") or "",
                    # 상품 쇼츠는 **모든 장면**에 상품 사진을 둔다(2026-10-06: 상위 5% 쇼핑 쇼츠는 처음부터
                    # 끝까지 상품이 화면에 있다. 글자 카드만 이어지면 무엇을 파는 영상인지 잊힌다).
                    # 블로그 쇼츠는 훅에만 — 기준 장면에 무관한 상품을 띄우면 오해를 산다.
                    **({"image": hero} if hero and (sc["type"] == "hook" or is_product) else {}),
                    **({"label": "포인트"} if is_product and sc["type"] == "point" else {}),
                    **({"video": hook_video} if hook_video and sc["type"] == "hook" else {}),
                    **({"code": code, "name": post.get("short_name") or ""}
                       if is_product and sc["type"] == "cta" else {}),
                    **({"options": sc["options"]} if sc.get("options") else {})}
                   for sc in scenes],
        "cues": cues,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"manifest": manifest, "credit": credit, "synthetic": bool(hook_video)}


def qa(manifest: dict, video: Path, sheet: Path) -> list[str]:
    """자동 품질 검사 + 장면 모음 이미지. 문제 목록을 돌려준다(비어 있으면 통과)."""
    issues = []
    dur = _duration(video)
    if not (15 <= dur <= 59):
        issues.append(f"길이 {dur:.1f}s")
    if abs(dur - manifest["totalDuration"]) > 0.5:
        issues.append(f"렌더 길이 {dur:.1f}s ≠ 매니페스트 {manifest['totalDuration']:.1f}s")
    for c in manifest["cues"]:
        if any(len(x) > CAPTION_MAX + 6 for x in c["text"].split(NL)):
            issues.append(f"자막 과다 길이: {c['text']}")
        if c["end"] - c["start"] < 0.6:
            issues.append(f"자막 너무 짧게 지나감({c['end'] - c['start']:.2f}s): {c['text']}")
    for s in manifest["scenes"]:
        if len(s["headline"]) > 16:
            issues.append(f"헤드라인 과다 길이: {s['headline']}")
    # 장면마다 중간 프레임 한 장씩 → 한 장으로 모은다(사람이 훑어보는 용도).
    tmp = sheet.parent / (sheet.stem + "_frames")
    tmp.mkdir(exist_ok=True)
    frames = []
    for i, s in enumerate(manifest["scenes"]):
        at = s["start"] + min(s["duration"] * 0.6, s["duration"] - 0.4)
        fp = tmp / f"{i}.png"
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", video, "-frames:v", "1",
             "-vf", "scale=360:640", fp])
        frames.append(fp)
    inputs = sum([["-i", str(p)] for p in frames], [])
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex",
         f"{''.join(f'[{i}:v]' for i in range(len(frames)))}hstack=inputs={len(frames)}", sheet])
    return issues


# 도메인 인지도(2026-10-15) — ds-commerce modules/content/brand.LINE 과 같은 문구. 워커는 그 모듈 없이 돈다.
BRAND_LINE = "📖 고르는 기준·비교 정리는 dsportal.io"


def product_meta(post: dict, script: dict, linkinbio_url: str, credit: str) -> tuple[str, str, list]:
    """상품 쇼츠 제목·설명란·태그. 설명란 URL 은 클릭되지 않으므로 번호 안내가 핵심이다."""
    code = int(post["code"])
    cat = (post.get("product_category") or "").split("/")[0]
    hook = script["hook"]["screen"]["headline"]
    title = f"{hook} | #{code} {post.get('short_name') or cat}"[:95]
    lines = [
        script["hook"]["say"].rstrip("."),
        "",
        f"▸ 영상 속 상품: {post.get('name', '')[:80]}",
        f"▸ 채널 프로필 링크에서 #{code} 번을 찾으세요 — {linkinbio_url}#{code}",
        BRAND_LINE,
        "",
        "이 영상은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.",
        "가격·재고·할인은 시점에 따라 달라질 수 있습니다.",
    ]
    if credit:
        lines += ["", credit]
    tags_cat = [t for t in re.split(r"[/·\s]+", post.get("product_category") or "") if t]
    lines += ["", " ".join(f"#{t}" for t in (["살림템", "쿠팡추천", "생활꿀템"] + tags_cat)[:6])]
    tags = ["살림템", "쿠팡추천", "생활용품", "추천템", "Shorts"] + tags_cat
    return title, NL.join(lines), tags


def produce(post: dict, upload: bool = False, privacy: str = "private",
            voice: str = VOICE, rate: str = RATE,
            linkinbio_url: str = "https://track.dsportal.io/link/youtube/") -> dict:
    """한 편을 끝까지 만든다. 워커(shorts_worker.py)와 CLI 가 같이 쓴다.
    반환: {post_id, video, sheet, issues, duration, [video_id, url, privacy]}"""
    pid = int(post["id"])
    key = job_key(post)
    out_dir = PUBLIC / key
    print(f"[1/3] 에셋 — {key}")
    built = build_assets(post, out_dir, voice, rate)
    manifest = built["manifest"]

    print(f"[2/3] 렌더 — {manifest['totalDuration']:.1f}s")
    props = out_dir / "props.json"
    props.write_text(json.dumps({"manifest": manifest}, ensure_ascii=False), encoding="utf-8")
    video = REMOTION / "out" / f"{key}.mp4"
    run(["npx", "remotion", "render", "src/index.ts", "Explainer", video,
         f"--props={props}", "--codec", "h264", "--crf", "17", "--overwrite",
         # 클라우드(GitHub Actions, 2코어)는 기본값(코어 절반)이면 한 편에 15분 — 전부 쓴다.
         *([f"--concurrency={os.environ['REMOTION_CONCURRENCY']}"] if os.environ.get("REMOTION_CONCURRENCY") else [])],
        cwd=REMOTION)

    sheet = REMOTION / "out" / f"{key}_sheet.jpg"
    issues = qa(manifest, video, sheet)
    print(f"[3/3] 검사 — {'통과' if not issues else '문제 ' + str(len(issues)) + '건'}")
    for x in issues:
        print("   -", x)
    print(f"   영상: {video}")
    print(f"   장면 모음: {sheet}")
    out = {"post_id": pid, "video": str(video), "sheet": str(sheet), "issues": issues,
           "duration": manifest["totalDuration"],
           # CC BY 곡이면 저작자 표시가 의무다 — 교차 게시(Threads·릴스·틱톡) 캡션에도 붙도록 NAS 로 넘긴다.
           "credit": built["credit"]}
    if not upload or issues:
        return out

    # 같은 글을 두 번 올리지 않는다 — 워커가 재시도하거나 사람이 다시 돌려도.
    mark = UPLOADED / (f"{key}.json" if post.get("kind") == "product" else f"post_{pid}_explainer.json")
    if mark.exists():
        prev = json.loads(mark.read_text(encoding="utf-8"))
        print("이미 업로드됨:", prev.get("url"))
        return {**out, **{k: prev.get(k) for k in ("video_id", "url", "privacy")}}

    import make_shorts as ms
    import youtube_upload
    script = post["shorts_script"]
    hook = script["hook"]["screen"]["headline"]
    category = manifest["category"]
    if post.get("kind") == "product":
        title, desc, tags = product_meta(post, script, linkinbio_url, built["credit"])
        # AI 로 만든 사실적 장면이 들어가면 유튜브 '변경되거나 합성된 콘텐츠' 표시가 의무다.
        res = youtube_upload.upload(video, title=title, description=desc, tags=tags, privacy=privacy,
                                    synthetic=built.get("synthetic", False))
        UPLOADED.mkdir(exist_ok=True)
        mark.write_text(json.dumps({**res, "privacy": privacy, "kind": "product"}, ensure_ascii=False),
                        encoding="utf-8")
        print("업로드:", res.get("url"), f"({privacy})")
        return {**out, "video_id": res.get("video_id"), "url": res.get("url"), "privacy": privacy}
    desc = ms._youtube_description(
        hook=script["hook"]["say"], category=category,
        products=ms._extract_products_from_post(post.get("html_content") or ""), hero_link="",
        blog_url=post.get("permalink") or "", linkinbio_url=linkinbio_url,
        duration=manifest["totalDuration"], credits=[built["credit"]] if built["credit"] else [])
    res = youtube_upload.upload(video, title=ms._youtube_title(hook, category), description=desc,
                                tags=ms._search_keywords(category) + ["Shorts"], privacy=privacy)
    UPLOADED.mkdir(exist_ok=True)
    mark.write_text(json.dumps({**res, "privacy": privacy, "kind": "explainer"}, ensure_ascii=False),
                    encoding="utf-8")
    print("업로드:", res.get("url"), f"({privacy})")
    return {**out, "video_id": res.get("video_id"), "url": res.get("url"), "privacy": privacy}


def main():
    ap = argparse.ArgumentParser(description="정보 전달형 쇼츠 생성")
    ap.add_argument("--post-json", required=True)
    ap.add_argument("--voice", default=VOICE)
    ap.add_argument("--rate", default=RATE)
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    ap.add_argument("--linkinbio-url", default="https://track.dsportal.io/link/youtube/")
    a = ap.parse_args()
    post = json.loads(Path(a.post_json).read_text(encoding="utf-8"))
    r = produce(post, a.upload, a.privacy, a.voice, a.rate, a.linkinbio_url)
    if a.upload and r["issues"]:
        raise SystemExit("검사 문제가 있어 업로드하지 않았다 — 고친 뒤 다시 실행")


if __name__ == "__main__":
    main()
