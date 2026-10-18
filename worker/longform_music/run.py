"""3시간 음악 영상 반자동 제작 — 기획 → Lyria 생성·자동 검사 → 오디오 조립 → 1080p 렌더·검사 → 비공개 업로드.

    python longform_music/run.py all --job sleep-001                 # 업로드 없이 끝까지(파일·보고서만)
    python longform_music/run.py all --job sleep-001 --upload        # 비공개 업로드까지
    python longform_music/run.py all --job pilot --hours 0.17 --max-cost 0.5   # 시험(곡 몇 개, 10분)
    python longform_music/run.py review --job sleep-001 --reject t004,t017      # 사람이 뺄 곡 지정 후
    python longform_music/run.py all --job sleep-001                 # 다시 돌리면 모자란 만큼만 새로 만든다
    python longform_music/run.py compile --job sleep-long-001 --from sleep-001,sleep-002 --hours 6
    python longform_music/run.py all --job sleep-long-001 --upload   # 모은 곡으로 긴 영상(Lyria 비용 0)

작업 폴더(기본 longform_music/out/<job>, LONGFORM_OUT 로 변경)의 manifest.json 이 상태의 원본이다.
이미 만든 곡은 다시 만들지 않으므로 실패한 단계부터 이어서 돌릴 수 있다. 과금은 --max-cost(달러)를
넘기 전에 멈춘다. 결과와 검수 체크리스트는 report.md 에 쓴다.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent / "youtube_shorts"))   # veo._vertex_auths — Lyria 를 안 부르는 실행에서도 필요

import audio  # noqa: E402
import presets  # noqa: E402
import video  # noqa: E402

EST_TRACK_SEC = 150             # Lyria 3 Pro 곡 길이 가정(최대 약 3분, 실제로는 더 짧은 곡도 나온다)
XFADE = 8.0
FAIL_STREAK = 12                # 연달아 이만큼 실패하면 멈춘다(Lyria 는 곡의 절반 가까이를 finishReason=OTHER 로 거절하기도 한다)
DEAD_LEAD = 3                   # 한 악기가 이만큼 실패하고 성공이 없으면 그 악기 곡은 건너뛴다


def job_dir(job: str) -> Path:
    root = Path(os.environ.get("LONGFORM_OUT") or HERE / "out")
    d = root / job
    (d / "tracks").mkdir(parents=True, exist_ok=True)
    return d


def load(d: Path) -> dict:
    return json.loads((d / "manifest.json").read_text(encoding="utf-8"))


def save(d: Path, m: dict) -> None:
    tmp = d / "manifest.json.tmp"
    tmp.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(d / "manifest.json")


def approved(m: dict) -> list[dict]:
    return [t for t in m["tracks"] if t.get("status") == "approved"]


def covered(m: dict) -> float:
    ok = approved(m)
    return sum(t["duration"] for t in ok) - XFADE * max(0, len(ok) - 1)


def cmd_plan(a) -> dict:
    d = job_dir(a.job)
    if (d / "manifest.json").exists():
        m = load(d)
        print(f"기존 기획 사용: {len(m['tracks'])}곡, 목표 {m['target_sec']}초")
        return m
    target = round(a.hours * 3600)
    count = a.tracks or math.ceil(target / (EST_TRACK_SEC - XFADE) * 1.2) + 1
    if a.seed is None:                          # 작업마다 다른 곡 구성(같은 틀 반복 방지)
        import zlib
        a.seed = zlib.crc32(a.job.encode()) % 10000
    m = {"job": a.job, "category": a.category, "target_sec": target, "seed": a.seed,
         "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "spent_usd": 0.0,
         "tracks": presets.plan_tracks(a.category, count, a.seed)}
    save(d, m)
    print(f"기획: {count}곡(여유 포함), 목표 {target}초")
    return m


def cmd_compile(a) -> dict:
    """이미 만든 작업들(--from sleep-001,sleep-002)의 승인 곡을 모아 더 긴 새 작업을 만든다 — Lyria 비용 0.
    곡이 목표 길이를 다 채울 때만 만든다(같은 곡 반복 없이). --hours 0 이면 모은 곡으로 채울 수 있는 만큼(시간 단위 내림).
    배경·썸네일·제목은 새 작업 이름으로 새로 정해진다. 이미 만든 작업이면 그대로 둔다(이어서 실행)."""
    import random
    import shutil
    import zlib
    d = job_dir(a.job)
    if (d / "manifest.json").exists():
        m = load(d)
        print(f"기존 모음 작업 사용: {len(m['tracks'])}곡, 목표 {m['target_sec']}초")
        return m
    srcs = [x for x in (a.sources or "").split(",") if x]
    if not srcs or a.job in srcs:
        raise SystemExit("--from 에 다른 작업 이름을 쉼표로 준다")
    pool, seen = [], set()
    for i, src in enumerate(srcs):
        sd = job_dir(src)
        if not (sd / "manifest.json").exists():
            raise SystemExit(f"{src}: 곡 기록이 없다(캐시가 지워졌거나 이름이 틀림)")
        for t in approved(load(sd)):
            sha = (t.get("qc") or {}).get("sha256")
            if sha in seen or not (sd / "tracks" / t["file"]).exists():
                continue
            seen.add(sha)
            tid = f"{chr(97 + i)}{t['id']}"         # 작업마다 앞 글자(a, b, …)를 붙여 겹치지 않게
            shutil.copy2(sd / "tracks" / t["file"], d / "tracks" / f"{tid}{Path(t['file']).suffix}")
            pool.append({**t, "id": tid, "file": f"{tid}{Path(t['file']).suffix}", "source": src})
    random.Random(zlib.crc32(a.job.encode())).shuffle(pool)
    for i in range(1, len(pool)):                   # 같은 악기가 붙어 나오면 뒤의 다른 곡과 자리를 바꾼다
        if pool[i]["name"].split(" & ")[0] == pool[i - 1]["name"].split(" & ")[0]:
            for j in range(i + 1, len(pool)):
                if pool[j]["name"].split(" & ")[0] != pool[i - 1]["name"].split(" & ")[0]:
                    pool[i], pool[j] = pool[j], pool[i]
                    break
    m = {"job": a.job, "category": a.category, "target_sec": 0, "seed": 0, "sources": srcs, "spent_usd": 0.0,
         "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "tracks": pool}
    have = covered(m)
    target = round(a.hours * 3600) if a.hours > 0 else int(have // 3600) * 3600
    if target <= 0 or have < target:
        raise SystemExit(f"곡이 모자라다: 모은 곡 {len(pool)}개로 {have / 3600:.2f}시간, 목표 {target / 3600:.2f}시간 "
                         "— 작업을 더 넣거나 길이를 줄인다")
    m["target_sec"] = target
    save(d, m)
    print(f"모음: {', '.join(srcs)}에서 {len(pool)}곡({have / 3600:.2f}시간) → {target / 3600:g}시간 영상")
    return m


def pair_job(job: str) -> tuple[str, str] | None:
    """짝수 번째 작업이면 (앞 작업, 6시간 모음 작업 이름). rain-002 → (rain-001, rain-6h-001), rain-004 → (rain-003, rain-6h-002)."""
    import re
    mt = re.fullmatch(r"(.+)-(\d{3})", job)
    if not mt or mt[1].endswith("-6h") or int(mt[2]) % 2:
        return None
    n = int(mt[2])
    return f"{mt[1]}-{n - 1:03d}", f"{mt[1]}-6h-{n // 2:03d}"


def cmd_autocompile(a) -> dict | None:
    """테마별로 영상이 2편 모이면(짝수 번째 작업을 올린 뒤) 두 작업의 곡을 모아 긴 모음 영상을 만들어 비공개로 올린다 — Lyria 비용 0.
    앞 작업이 없거나(캐시 없음) 어느 쪽이든 이미 모음 작업이면 건너뛴다."""
    pair = pair_job(a.job)
    if not pair:
        print(f"{a.job}: 짝수 번째 작업이 아니라 모음 영상은 건너뛴다")
        return None
    prev, auto = pair
    for j in (prev, a.job):
        if not (job_dir(j) / "manifest.json").exists():
            print(f"{j}: 곡 기록이 없어 모음 영상은 건너뛴다")
            return None
        if load(job_dir(j)).get("sources"):
            print(f"{j}: 이미 모음 작업이라 다시 모으지 않는다")
            return None
    print(f"테마 모음: {prev} + {a.job} → {auto}")
    b = argparse.Namespace(**{**vars(a), "job": auto, "sources": f"{prev},{a.job}", "hours": 0.0,
                              "category": load(job_dir(a.job))["category"]})
    cmd_compile(b)
    return cmd_all(b)


def cmd_generate(a) -> dict:
    import httpx
    import lyria
    d = job_dir(a.job)
    m = load(d)
    if m.get("sources"):
        raise SystemExit("모음 작업(compile)은 새 곡을 만들지 않는다 — 곡이 모자라면 --from 에 작업을 더 넣어 새로 모은다")
    client = httpx.Client(timeout=600, follow_redirects=True)
    import veo
    auths = veo._vertex_auths()
    seen: set = set()
    for t in m["tracks"]:                       # 검사 기준이 바뀌었으면 이미 만든 곡을 다시 검사한다
        if t.get("file") and t.get("status") in ("approved", "rejected") and not t.get("review"):
            if (t.get("qc") or {}).get("version") != audio.QC_VERSION:
                judge(d, m, t, seen)
            else:
                seen.add(t["qc"]["sha256"])
    fresh = {t["id"]: t for t in presets.plan_tracks(m["category"], len(m["tracks"]), m["seed"])}
    for t in m["tracks"]:                       # 아직 안 만든 곡은 지금 프리셋 문구로(문구를 고치면 바로 반영)
        if not t.get("status") and t["id"] in fresh:
            t.update(name=fresh[t["id"]]["name"], prompt=fresh[t["id"]]["prompt"])
    save(d, m)

    def lead(t):
        return t["name"].split(" & ")[0]

    def skip_dead_leads():
        """Lyria 가 특정 악기 문구를 계속 거절하면(finishReason=OTHER) 그 악기 곡은 건너뛴다."""
        for name in {lead(t) for t in m["tracks"]}:
            ts = [t for t in m["tracks"] if lead(t) == name]
            if sum(t.get("status") == "failed" for t in ts) >= DEAD_LEAD and not any(t.get("file") for t in ts):
                for t in ts:
                    if not t.get("status"):
                        t["status"], t["error"] = "skipped", f"{name}: Lyria 가 계속 거절"
                print(f"  {name} 곡은 건너뜀(연속 거절)")

    def one(t):
        try:
            got = lyria.generate(t["prompt"], d / "tracks" / t["id"], client, auths)
            return t, got, None
        except Exception as e:                  # noqa: BLE001 — 한 곡 실패는 기록하고 다음 곡
            return t, None, f"{type(e).__name__}: {e}"

    streak = 0
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        while covered(m) < m["target_sec"]:
            if streak >= FAIL_STREAK:
                print(f"생성이 {streak}번 연달아 실패 — 멈춤(로그의 실패 이유 확인)")
                break
            skip_dead_leads()
            todo = [t for t in m["tracks"] if not t.get("status")]
            if not todo:                        # 탈락이 많아 기획이 바닥나면 같은 규칙으로 5곡 더 기획한다
                more = presets.plan_tracks(m["category"], len(m["tracks"]) + 5, m["seed"])[len(m["tracks"]):]
                m["tracks"] += more
                print(f"  기획 {len(more)}곡 추가")
                skip_dead_leads()
                todo = [t for t in more if not t.get("status")]
                if not todo:
                    continue
            room = int((a.max_cost - m["spent_usd"]) // lyria.price())
            if room <= 0:
                print(f"비용 한도 ${a.max_cost} 도달 — 멈춤")
                break
            batch = todo[: min(a.workers, room)]
            for t, got, err in pool.map(one, batch):
                if err:
                    t["status"], t["error"] = "failed", err[:500]
                    print(f"  {t['id']} 실패: {err[:200]}")
                    streak += 1
                    if "인증 없음" in err or " 403 " in f" {err} " or "401" in err:
                        save(d, m)
                        raise SystemExit("인증·권한 오류 — 멈춘다")
                    continue
                streak = 0
                m["spent_usd"] = round(m["spent_usd"] + lyria.price(), 2)
                t.update(file=got["file"], mime=got["mime"], text=got["text"], vocals=got["vocals"])
                judge(d, m, t, seen)
            save(d, m)
    print(f"승인 {len(approved(m))}곡, 이어 붙인 길이 {covered(m):.0f}/{m['target_sec']}초, 누적 ${m['spent_usd']}")
    write_report(d, m)
    return m


def judge(d: Path, m: dict, t: dict, seen: set) -> None:
    """곡 하나 자동 검사 → approved/rejected. 가사 의심은 탈락시키지 않고 표시만 한다:
    Lyria 는 기악곡에도 곡 설명·구조 텍스트를 돌려줘서 텍스트만으로는 보컬을 가릴 수 없다(2026-10-10 시험에서
    6곡 모두 걸림). 보컬은 사람이 들어서 확인하고 review --reject 로 뺀다."""
    qc = audio.analyze(d / "tracks" / t["file"])
    if qc["sha256"] in seen:
        qc["problems"].append("중복 파일")
    seen.add(qc["sha256"])
    qc["notes"] = ["가사 의심(들어서 확인)"] if t.get("vocals") else []
    t["qc"], t["duration"] = qc, qc["duration"]
    t["status"] = "rejected" if qc["problems"] else "approved"
    m.pop("assembled", None)                    # 곡이 바뀌었으니 다시 조립한다
    print(f"  {t['id']} {t['name']}: {qc['duration']:.0f}초 {t['status']} {', '.join(qc['problems'] + qc['notes'])}")


def cmd_review(a) -> dict:
    d = job_dir(a.job)
    m = load(d)
    rej = set(filter(None, (a.reject or "").split(",")))
    app = set(filter(None, (a.approve or "").split(",")))
    for t in m["tracks"]:
        if t["id"] in rej:
            t["status"], t["review"] = "rejected", "사람이 뺌"
        elif t["id"] in app and t.get("file"):
            t["status"], t["review"] = "approved", "사람이 승인"
    m.pop("assembled", None)
    m.pop("final", None)
    save(d, m)
    write_report(d, m)
    print(f"승인 {len(approved(m))}곡, 길이 {covered(m):.0f}/{m['target_sec']}초 — 다시 all 을 돌리면 이어서 만든다")
    return m


def cmd_visuals(a) -> dict:
    """배경·썸네일만 새로 만들어 다시 올릴 준비. 곡·조립은 그대로, 이전 업로드는 기록만 남긴다(영상 삭제는 사람이)."""
    d = job_dir(a.job)
    m = load(d)
    for f in ("loop.mp4", "background.png", "thumbnail.jpg", "final.mp4"):
        (d / f).unlink(missing_ok=True)
    for k in ("final", "image", "background"):
        m.pop(k, None)
    if m.get("upload"):
        m.setdefault("previous_uploads", []).append(m.pop("upload"))
    m["need_image"] = True
    save(d, m)
    print("배경·썸네일을 다시 만든다 — 다음 all 에서 새 비공개 영상으로 올린다")
    return m


def cmd_reupload(a) -> dict:
    """같은 영상을 다시 올릴 준비(예: 채널 인증 전에 '너무 길다'로 처리 실패). 이전 업로드는 기록만 남긴다."""
    d = job_dir(a.job)
    m = load(d)
    if m.get("upload"):
        m.setdefault("previous_uploads", []).append(m.pop("upload"))
    save(d, m)
    print("다음 all 에서 새 비공개 영상으로 다시 올린다")
    return m


def cmd_assemble(a) -> dict:
    d = job_dir(a.job)
    m = load(d)
    ok = approved(m)
    seq = audio.sequence(ok, m["target_sec"], XFADE)
    norm = d / "norm"
    norm.mkdir(exist_ok=True)
    for t in ok:
        dst = norm / f"{t['id']}.wav"
        if not dst.exists():
            audio.normalize(d / "tracks" / t["file"], dst)
    starts = audio.assemble([norm / f"{t['id']}.wav" for t in seq], d / "audio.m4a", m["target_sec"], XFADE)
    m["assembled"] = {"order": [t["id"] for t in seq[: len(starts)]], "starts": starts,
                      "repeats": max(0, len(starts) - len({t["id"] for t in seq[: len(starts)]}))}
    if m["assembled"]["repeats"]:
        print(f"  곡이 모자라 {m['assembled']['repeats']}곡을 한 번 더 썼다")
    save(d, m)
    for f in norm.glob("*.wav"):                # 디스크 절약 — 다시 조립하면 새로 만든다
        f.unlink()
    write_report(d, m)
    return m


def cmd_render(a) -> dict:
    d = job_dir(a.job)
    m = load(d)
    preset = presets.CATEGORIES[m["category"]]
    loop = d / "loop.mp4"
    bg = Path(a.background) if getattr(a, "background", None) else None
    if bg:
        m["background"] = str(bg)
        m.pop("image", None)
    elif not loop.exists():
        bg = background_image(d, m)
        if bg is None and m.get("need_image"):
            save(d, m)
            raise SystemExit("배경 이미지를 만들지 못했다 — 같은 화면으로 다시 올리지 않고 멈춘다")
    m.pop("need_image", None)
    if not loop.exists() or bg:
        video.make_loop(loop, bg)
    m.setdefault("background", "자체 제작(밤하늘 루프)")
    thumb_text = presets.variant(m["category"], m["job"])[1]
    m["title"] = presets.title(m["category"], m["job"])
    video.thumbnail(bg if bg and bg.suffix.lower() in video.IMAGE_EXT else loop, d / "thumbnail.jpg", thumb_text)
    out = d / "final.mp4"
    video.render(loop, d / "audio.m4a", out, m["target_sec"])
    m["final"] = video.check(out, m["target_sec"])
    save(d, m)
    write_report(d, m)
    print(f"최종 검사: {'통과' if m['final']['ok'] else '문제 ' + ', '.join(m['final']['problems'])}")
    return m


def background_image(d: Path, m: dict) -> Path | None:
    """배경·썸네일 이미지를 Imagen 으로 한 장 만든다(이미 있으면 그대로). 실패하면 None → 자체 제작 밤하늘."""
    img = d / "background.png"
    if img.exists():
        return img
    if os.environ.get("LONGFORM_IMAGEN", "1") == "0":
        return None
    import httpx
    import imagen
    import veo
    prompt = presets.background_prompt(m["category"], m["job"])
    try:
        with httpx.Client(follow_redirects=True) as c:
            got = imagen.generate(prompt, img, c, veo._vertex_auths())
    except imagen.ImagenError as e:
        print(f"배경 이미지 생성 실패 — 자체 제작 밤하늘로: {e}")
        return None
    m["image"] = {**got, "usd": imagen.PRICE_USD}
    m["background"] = f"Imagen({got['model']}): {prompt}"
    print(f"배경 이미지: {got['model']}")
    return img


def description(m: dict) -> str:
    preset = presets.CATEGORIES[m["category"]]
    names = {t["id"]: t["name"] for t in m["tracks"]}
    import upload
    ch = upload.chapters([names[i] for i in m["assembled"]["order"]], m["assembled"]["starts"])
    visuals = (f"Background image generated with Google AI ({m['image']['model']})." if m.get("image")
               else "Visuals made by us.")
    head = preset["description_head"].replace("{duration}", presets.duration_words(m["target_sec"])) \
        .replace("{sound}", preset["sound"])
    return "\n".join(filter(None, [head, ch and "Tracklist\n" + ch,
                                   preset["description_disclosure"] + visuals + "\n", preset.get("hashtags", "")]))


def cmd_upload(a) -> dict:
    import upload
    d = job_dir(a.job)
    m = load(d)
    if not (m.get("final") or {}).get("ok"):
        raise SystemExit("최종 검사를 통과하지 않아 올리지 않는다")
    if m.get("upload"):
        print(f"이미 올림: {m['upload']['url']}")
        return m
    preset = presets.CATEGORIES[m["category"]]
    import localize
    title, desc = m.get("title") or presets.title(m["category"], m["job"]), description(m)
    body = upload.build_body(preset, desc, title, presets.tags(m["category"], m["target_sec"]),
                             localize.for_video(title, desc))
    m["upload"] = upload.upload_private(d / "final.mp4", body, d / "thumbnail.jpg")
    if preset.get("playlist"):
        try:
            m["upload"]["playlist"] = upload.add_to_playlist(m["upload"]["video_id"], *preset["playlist"])
        except Exception as e:                  # noqa: BLE001 — 재생목록 실패로 업로드를 되돌리지 않는다
            m["upload"]["playlist"] = f"실패: {e}"
            print(f"재생목록 넣기 실패: {e}")
    save(d, m)
    write_report(d, m)
    print(f"비공개 업로드: {m['upload']['url']}")
    return m


def cmd_seo(a) -> dict:
    """검색·해외 노출 점검: 채널 설정·영상 공개 상태·번역 여부·재생목록 공개 여부를 보고한다.
    --apply 면 번역이 없는 영상에 번역 제목·설명(10개 언어)과 '언어 없음' 오디오를 넣는다. 공개 전환은 하지 않는다."""
    import localize
    import upload
    yt = upload._yt()
    rep = {"channel": upload.channel_status(yt),
           "videos": upload.localize_existing(localize.for_video, a.apply, yt),
           "playlists": upload.playlists_status(yt)}
    lines = ["# 검색·해외 노출 점검", "", f"채널: {json.dumps(rep['channel'], ensure_ascii=False)}", "",
             "| 영상 | 공개 | 오디오 언어 | 번역 수 | 이번에 고침 | 거절·오류 |", "|---|---|---|---|---|---|"]
    lines += [f"| [{v['title'][:60]}](https://youtu.be/{v['id']}) | {v['privacy']} | {v['audio']} | "
              f"{v['localizations']} | {'예' if v.get('updated') else ''} | "
              f"{', '.join(v.get('rejected') or []) or v.get('error', '')[:80]} |" for v in rep["videos"]]
    lines += ["", "| 재생목록 | 공개 |", "|---|---|"] + [f"| {p['title']} | {p['privacy']} |" for p in rep["playlists"]]
    text = "\n".join(lines)
    print(text)
    out = Path(os.environ.get("LONGFORM_OUT", Path(__file__).parent / "out")) / "seo-report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    return rep


def cmd_mark(a) -> dict | None:
    """정기 제작용: 올린 작업의 테마별 번호를 남긴다."""
    import cadence
    st = cadence.mark(a.job)
    print(f"테마별 번호: {st}")
    return st


def cmd_playlist(a) -> dict:
    """이미 올린 영상을 이 작업 카테고리의 재생목록에 넣는다(재생목록 기능 전에 올린 영상용)."""
    import upload
    d = job_dir(a.job)
    m = load(d)
    if not m.get("upload"):
        raise SystemExit("아직 올리지 않았다")
    if isinstance(m["upload"].get("playlist"), dict):
        print(f"이미 재생목록에 있음: {m['upload']['playlist']['title']}")
        return m
    m["upload"]["playlist"] = upload.add_to_playlist(m["upload"]["video_id"],
                                                     *presets.CATEGORIES[m["category"]]["playlist"])
    save(d, m)
    write_report(d, m)
    return m


def cmd_all(a) -> dict:
    m = cmd_plan(a)
    if covered(m) < m["target_sec"]:
        m = cmd_generate(a)
    if not approved(m):
        raise SystemExit("승인된 곡이 없다")
    if covered(m) < m["target_sec"] * 0.5:
        raise SystemExit(f"곡이 목표의 절반도 안 된다({covered(m):.0f}초) — 반복이 너무 많아져서 멈춘다")
    if not m.get("assembled") or not (job_dir(a.job) / "audio.m4a").exists():
        m = cmd_assemble(a)
    m = cmd_render(a)
    if a.upload:
        m = cmd_upload(a)
    return m


CHECKLIST = [
    "Lyria(Google Cloud) 생성형 AI 약관·금지 사용 정책 확인 — 결과물 상업 이용 가능, 타인 저작물 모방 프롬프트 없음",
    "배경 영상·이미지 출처 확인(기본값은 자체 제작 밤하늘)",
    "스튜디오에서 처음·중간 몇 곳·끝 들어보기 — 보컬, 튀는 소리, 반복감, 이음매",
    "스튜디오 '저작권' 검사 결과 확인(Content ID 주장 없음)",
    "'변경되거나 합성된 콘텐츠' 표시 켜짐 확인(업로드 때 자동 설정)",
    "제목·설명·챕터·썸네일 확인",
    "채널 성격 확인 — 쇼핑 쇼츠 채널과 따로 운영할지",
    "공개 전환은 스튜디오에서 직접(이 도구는 비공개로만 올린다)",
]


def write_report(d: Path, m: dict) -> None:
    rows = []
    for t in m["tracks"]:
        if not t.get("status"):
            continue
        qc = t.get("qc") or {}
        rows.append(f"| {t['id']} | {t['name']} | {t['status']} | {qc.get('duration', '')} | {qc.get('rms_db', '')} "
                    f"| {qc.get('max_jump_db', '')} | {', '.join(qc.get('problems', []) + qc.get('notes', [])) or t.get('error', '')[:80]} |")
    lines = [f"# {m['job']} — {m['category']} {m['target_sec'] / 3600:.2f}시간", "",
             f"- 승인 {len(approved(m))}곡 / 생성 {sum(1 for t in m['tracks'] if t.get('file'))}곡, "
             f"이어 붙인 길이 {covered(m):.0f}/{m['target_sec']}초",
             f"- Lyria 비용(추정) ${m['spent_usd']}"
             + (f" + 배경 이미지 ${m['image']['usd']}" if m.get("image") else "")]
    if m.get("assembled"):
        lines.append(f"- 조립: {len(m['assembled']['order'])}곡, 반복 사용 {m['assembled']['repeats']}곡")
    if m.get("final"):
        f = m["final"]
        lines.append(f"- 최종 파일: {f['duration']}초, {f['video']}, {f['audio']}, {f['size_mb']}MB — "
                     f"{'검사 통과' if f['ok'] else '문제: ' + ', '.join(f['problems'])}")
        lines.append(f"- 배경: {m.get('background')}")
    if m.get("upload"):
        u = m["upload"]
        lines.append(f"- 비공개 업로드: {u['url']} (스튜디오 {u['studio']}), 썸네일 {u.get('thumbnail')}")
        pl = u.get("playlist")
        if pl:
            lines.append(f"- 재생목록: {pl['title']} {pl['url']}" if isinstance(pl, dict) else f"- 재생목록: {pl}")
    for u in m.get("previous_uploads", []):
        lines.append(f"- 이전 업로드(스튜디오에서 지울 것): {u['url']}")
    lines += ["", "## 곡별 자동 검사", "", "| 곡 | 이름 | 상태 | 길이(초) | 음량(dBFS) | 최대 급변(dB) | 문제 |",
              "|---|---|---|---|---|---|---|", *rows, ""]
    texts = [f"- **{t['id']}** {' '.join(t['text'].split())[:300]}" for t in m["tracks"] if t.get("text")]
    if texts:
        lines += ["## Lyria 가 돌려준 텍스트(가사가 있으면 보컬 곡)", "", *texts, ""]
    lines += ["## 공개 전 검수", ""]
    lines += [f"- [ ] {c}" for c in CHECKLIST]
    (d / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["compile", "autocompile", "seo", "mark", "plan", "generate", "review", "visuals", "reupload", "assemble", "render", "upload", "playlist", "all"])
    p.add_argument("--job", required=True)
    p.add_argument("--category", default="sleep", choices=sorted(presets.CATEGORIES))
    p.add_argument("--hours", type=float, default=3.0)
    p.add_argument("--tracks", type=int, default=0, help="기획 곡 수(기본: 길이에서 계산 + 20%% 여유)")
    p.add_argument("--seed", type=int, default=None, help="곡 구성 시드(기본: 작업 이름에서)")
    p.add_argument("--max-cost", type=float, default=8.0, help="이 작업의 Lyria 누적 비용 한도(달러)")
    p.add_argument("--workers", type=int, default=3)
    p.add_argument("--background", help="배경 이미지·영상(사용 허가 확인한 것). 없으면 자체 제작")
    p.add_argument("--upload", action="store_true", help="all 끝에 비공개 업로드")
    p.add_argument("--reject", help="review: 뺄 곡 id(쉼표)")
    p.add_argument("--from", dest="sources", help="compile: 곡을 모을 작업 이름(쉼표)")
    p.add_argument("--apply", action="store_true", help="seo: 번역이 없는 영상에 번역·오디오 언어를 넣는다")
    p.add_argument("--approve", help="review: 자동 검사에서 빠졌지만 쓸 곡 id(쉼표)")
    a = p.parse_args(argv)
    return globals()[f"cmd_{a.cmd}"](a)


if __name__ == "__main__":
    main()
