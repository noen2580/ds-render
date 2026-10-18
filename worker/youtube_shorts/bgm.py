"""배경음악(BGM)을 확보해서 내레이션 아래에 깔아준다.

왜 필요한가 — 우리 영상은 오디오 트랙이 내레이션 하나뿐이라, 말이 끊긴 구간이 그대로
정적으로 들린다(실측: 완성본의 오디오 스트림이 1개). 실제 쇼츠는 거의 전부 배경음이
깔려 있고, 같은 화면이어도 음악이 있고 없고의 체감 차이가 크다.

왜 ccMixter인가 — 키 없이 열려 있는 몇 안 되는 음원 API다. 다만 **기본 검색 결과는
대부분 CC BY-NC(비상업)** 이고, 우리 영상은 제휴 링크가 붙는 상업 이용이라 그건 쓸 수
없다. `lic=open`으로 질의하면 CC BY(저작자 표시)만 돌아온다 — 상업 이용이 허용되고
표시 의무만 있어서 설명란 한 줄로 해결된다.
(Pixabay 음악은 Cloudflare 403, FMA API는 404, 짤스튜디오는 유튜브 앱에서 직접
트랙을 붙이는 방식이라 API 업로드 파이프라인에 붙일 수 없다 — 전부 실측으로 확인.)

한 번 받아 `cache/bgm/`에 모아두고 계속 돌려쓴다. 매번 API를 부를 이유가 없고,
받아둔 뒤로는 네트워크 없이도 동작한다.
"""
import hashlib
import json
import logging
import random
import re
import array
import subprocess
from pathlib import Path

import httpx

log = logging.getLogger("youtube_shorts.bgm")

HERE = Path(__file__).parent
CACHE_DIR = HERE / "cache" / "bgm"
INDEX_PATH = CACHE_DIR / "index.json"
# 자체 제작 곡(2026-09-30, ACE-Step — tools/music_gen). 우리 소유라 저작자 표시가 필요 없고
# 저작권 신고 위험이 없다. 3곡 이상 있으면 ccMixter(CC BY) 대신 이쪽에서 고른다.
OWN_DIR = CACHE_DIR / "own"
OWN_INDEX = OWN_DIR / "index.json"
OWN_MIN = 3

API_URL = "https://ccmixter.org/api/query"
# lic=open — CC BY / CC0 계열만. 이걸 빼면 CC BY-NC가 섞여 들어와 상업 이용이 막힌다.
# limit을 크게 잡으면 응답이 수 MB가 되어 h11 버퍼 한계에 걸린다
# ("Receive buffer too long" — 실측: 30은 실패, 8은 성공). 8개씩 나눠 받는다.
# 태그가 결과를 크게 가른다. 처음엔 "instrumental"로 받았는데 포크·월드뮤직 계열이
# 주로 걸려서(Lost Roamin', Roman Song, sitarNsynth …) 쇼츠 배경음으로는 너무 성겼다
# — 사용자 피드백 "인트로에 가까운 단순음만 나온다".
# 편성이 두툼한 장르 태그를 돌아가며 받는다(energetic/hiphop은 결과 0건이라 뺐다).
MIN_FULLNESS = 1.5      # 이보다 얇으면 라이브러리에 넣지 않는다
TAGS = ("electronic", "beat", "funk", "upbeat", "rock", "dance")
QUERY = {"f": "json", "lic": "open"}
PAGE = 8

# 내레이션보다 한참 아래로 깔아야 말이 묻히지 않는다. -22dB면 배경으로 인지되면서도
# 나레이션을 방해하지 않는 수준(짤스튜디오 정책이 요구하는 "명확히 들리는" 수준도 만족).
_DL_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126 Safari/537.36"),
    "Referer": "https://ccmixter.org/",
}

# 내레이션보다 몇 dB 아래에 깔 것인가. **고정 게인을 쓰면 안 된다** — 트랙마다 원본
# 음량이 제각각이라(실측: 같은 라이브러리 안에서도 -12.7dB ~ -25dB) 같은 값을 걸면
# 어떤 곡은 시끄럽고 어떤 곡은 아예 안 들린다.
#
# 예전엔 -22dB 고정이었는데, 원본이 -12.7dB인 트랙에 걸리자 BGM이 -34.7dB가 되어
# 내레이션(-20.4dB)보다 14dB 아래로 내려갔다. 무음을 제거해 말이 거의 끊기지 않는
# 구간에서 14dB 아래면 폰 스피커로는 들리지 않는다(사용자 피드백: "BGM이 안 들린다").
#
# 단순히 낮추기만 해서는 안 들린다. 무음을 제거해 말이 거의 끊기지 않으므로, 아래로
# 내리면 내릴수록 그냥 사라진다(10dB 아래로 내렸을 때 블록 레벨 분포가 1.4dB밖에
# 안 움직였다 — 내레이션이 모든 구간을 덮고 있다는 뜻).
#
# 그래서 **사이드체인 더킹**을 쓴다. BGM을 5dB 아래까지 크게 깔아서 말 사이사이에
# 확실히 들리게 하고, 목소리가 나오는 순간에만 컴프레서가 자동으로 눌러준다.
# 방송에서 배경음악을 다루는 표준 방식이다.
# 더킹(ratio=3)이 3~4dB를 더 먹으므로, 여기서 1dB만 낮춰야 최종적으로
# 내레이션 대비 -4~5dB에 안착한다. 4.0으로 뒀을 때는 최종 -7.6dB라
# 여전히 약하다는 피드백을 받았다.
BGM_BELOW_NARRATION_DB = 1.0
FADE_SEC = 1.2

# 더킹 강도. **세게 걸면 안 된다** — 처음엔 ratio=8/release=400으로 잡았는데, 더킹이
# 레벨을 다시 눌러버려 최종 BGM이 내레이션 대비 -16.8dB가 됐다. 고정 -22dB로 깔았을
# 때(-14.3dB)와 사실상 같은 결과라 여전히 안 들렸다.
#
# 내레이션에 빈 구간이 14개 있지만 각각 0.16~0.26초뿐이라, release가 길면 그 틈에
# 음악이 올라오지 못한다. 실측 비교(내레이션 대비 최종 BGM 레벨):
#     ratio=8 / release=400   →  -16.8dB   안 들림
#     ratio=4 / release=250   →  -11.6dB
#     ratio=3 / release=200   →   -7.6dB   ← 채택
#     더킹 없음                →   -4.0dB   목소리와 경쟁
DUCK = "threshold=0.08:ratio=3:attack=25:release=200"


def _mean_volume(path: Path) -> float | None:
    """ffmpeg volumedetect로 평균 음량(dBFS)을 읽는다."""
    r = subprocess.run(["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True, errors="replace")
    for ln in r.stderr.splitlines():
        if "mean_volume:" in ln:
            try:
                return float(ln.split("mean_volume:")[1].strip().split()[0])
            except (IndexError, ValueError):
                return None
    return None


# ── 어디서부터 틀 것인가 ──────────────────────────────────────────────────────
#
# 트랙 0초부터 깔면 **인트로만 쓰고 영상이 끝난다.** 인트로는 대체로 가장 조용하고
# 악기도 적어서, 30~40초짜리 쇼츠가 통째로 도입부에 갇힌다.
#
# 처음엔 RMS(음량)만 보고 골랐는데 그걸로는 부족했다 — **"크지만 단순한" 구간과
# "꽉 찬 구간"을 구분하지 못한다.** 솔로 악기 하나도 RMS는 높게 나온다(사용자 피드백:
# "여전히 인트로에 가까운 단순음만 나온다").
#
# 그래서 **대역별 에너지의 기하평균**으로 고른다. 저역(베이스/드럼)·중역(코드/보컬)·
# 고역(하이햇/심벌) 셋을 각각 재고 곱한 뒤 세제곱근을 취하면, 어느 한 대역이라도
# 비어 있을 때 점수가 크게 떨어진다. 세 대역이 동시에 살아 있는 구간 = 편성이 꽉 찬
# 구간이고, 그게 우리가 원하는 "달리고 있는" 부분이다.
_PROBE_SR = 22050
_FFT = 2048
_HOP = 1024                      # 약 46ms
_BANDS = ((40, 250), (250, 2000), (2000, 8000))   # 저 / 중 / 고


def _fullness_profile(src: Path) -> tuple["np.ndarray", float]:
    """프레임별 '편성 충실도' 점수와 트랙 길이(초)."""
    import numpy as np
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(src), "-ac", "1",
         "-ar", str(_PROBE_SR), "-f", "s16le", "-"],
        capture_output=True).stdout
    x = np.frombuffer(raw[: len(raw) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    if x.size < _FFT * 4:
        return np.zeros(0, dtype=np.float32), 0.0
    n = 1 + (x.size - _FFT) // _HOP
    idx = np.arange(_FFT)[None, :] + _HOP * np.arange(n)[:, None]
    win = np.hanning(_FFT).astype(np.float32)
    spec = np.abs(np.fft.rfft(x[idx] * win, axis=1))
    freqs = np.fft.rfftfreq(_FFT, 1 / _PROBE_SR)
    bands = []
    for lo, hi in _BANDS:
        m = (freqs >= lo) & (freqs < hi)
        bands.append(spec[:, m].mean(axis=1) + 1e-9)
    # 기하평균 — 한 대역이라도 죽으면 점수가 급락한다.
    score = np.cbrt(bands[0] * bands[1] * bands[2])
    return score.astype(np.float32), x.size / _PROBE_SR


def best_offset(src: Path, duration: float) -> float:
    """영상 길이만큼의 구간 중 편성이 가장 꽉 찬 시작 지점(초)."""
    try:
        import numpy as np
        score, total = _fullness_profile(src)
    except Exception as e:
        log.warning(f"BGM 구간 분석 실패 [{src.name}]: {e}")
        return 0.0
    if score.size == 0 or total <= duration + 1:
        return 0.0
    fps = _PROBE_SR / _HOP
    win = max(int(duration * fps), 1)
    if score.size <= win:
        return 0.0
    # 이동평균 = 누적합 차분
    acc = np.concatenate(([0.0], np.cumsum(score, dtype=np.float64)))
    means = (acc[win:] - acc[:-win]) / win
    # 페이드아웃을 물지 않게 뒤쪽은 후보에서 뺀다.
    limit = max(int((total - duration - 0.5) * fps), 1)
    means = means[:limit]
    if means.size == 0:
        return 0.0
    return float(np.argmax(means) / fps)


def _load_index() -> list[dict]:
    if INDEX_PATH.exists():
        try:
            return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []


def fetch_library(limit: int = 12) -> list[dict]:
    """CC BY 음원을 내려받아 캐시에 채운다. 이미 있으면 그대로 쓴다."""
    index = _load_index()
    have = {t["id"] for t in index}
    if len(index) >= limit:
        return index

    tracks: list[dict] = []
    for tag in TAGS:
        for offset in (0, PAGE):
            try:
                r = httpx.get(API_URL,
                              params={**QUERY, "tags": tag, "limit": str(PAGE),
                                      "offset": str(offset)},
                              headers={"User-Agent": "dsportal-shorts/1.0"}, timeout=45)
                r.raise_for_status()
                page = r.json()
            except Exception as e:
                log.warning(f"ccMixter 조회 실패({tag}, offset={offset}): {e}")
                break
            if not page:
                break
            tracks.extend(page)
        if len(tracks) >= limit * 3:
            break

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for t in tracks:
        if len(index) >= limit:
            break
        lic = t.get("license_name", "")
        # 방어적으로 한 번 더 확인한다 — lic=open이 뚫리면 비상업 음원이 섞인다.
        if "noncommercial" in lic.lower() or "nc" in (t.get("license_url", "").split("/")[-2:] or [""])[0]:
            continue
        mp3 = next((f for f in t.get("files", [])
                    if str(f.get("file_name", "")).lower().endswith(".mp3")), None)
        if not mp3:
            continue
        tid = str(t.get("upload_id"))
        if tid in have:
            continue
        dest = CACHE_DIR / f"{tid}.mp3"
        try:
            # ccMixter는 Referer가 없으면 mp3 직접 요청을 403으로 막는다(실측:
            # UA만 보내면 403, Referer를 같이 보내면 200). API 조회는 안 막힌다.
            with httpx.stream("GET", mp3["download_url"], timeout=180,
                              headers=_DL_HEADERS, follow_redirects=True) as resp:
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
        except Exception as e:
            dest.unlink(missing_ok=True)
            log.warning(f"BGM 다운로드 실패 [{t.get('upload_name')}]: {e}")
            continue
        # 편성이 얇은 트랙은 아예 담지 않는다 — 최적 구간을 골라도 "단순음"으로 들린다
        # (실측: 같은 라이브러리 안에서 최적 구간 충실도가 0.5 ~ 8.2로 16배 차이 났다).
        try:
            prof, _ = _fullness_profile(dest)
            fullness = float(prof.mean()) if prof.size else 0.0
        except Exception:
            fullness = 0.0
        if fullness < MIN_FULLNESS:
            log.info(f"BGM 제외(편성 얇음 {fullness:.2f}): {t.get('upload_name')}")
            dest.unlink(missing_ok=True)
            continue
        index.append({
            "id": tid,
            "file": dest.name,
            "fullness": round(fullness, 3),
            "title": t.get("upload_name", ""),
            "artist": t.get("user_name", ""),
            "license": lic,
            "license_url": t.get("license_url", ""),
            "page": t.get("file_page_url") or t.get("upload_page_url", ""),
        })
        have.add(tid)
        log.info(f"BGM 확보: {t.get('upload_name')} / {t.get('user_name')} ({lic})")

    INDEX_PATH.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
    return index


def _own_index() -> list[dict]:
    try:
        return json.loads(OWN_INDEX.read_text(encoding="utf-8")) if OWN_INDEX.exists() else []
    except (json.JSONDecodeError, OSError):
        return []


def register_own(wav_dir: Path) -> list[dict]:
    """tools/music_gen 이 만든 wav 를 라이브러리에 넣는다 — -16 LUFS 로 맞춘 mp3 로 저장."""
    OWN_DIR.mkdir(parents=True, exist_ok=True)
    index = {t["id"]: t for t in _own_index()}
    for wav in sorted(Path(wav_dir).glob("*.wav")):
        tid = wav.stem
        dest = OWN_DIR / f"{tid}.mp3"
        if not dest.exists():
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                            "-ar", "44100", "-b:a", "192k", str(dest)], check=True)
        meta = {}
        mj = wav.with_suffix(".json")
        if mj.exists():
            meta = json.loads(mj.read_text(encoding="utf-8"))
        index[tid] = {"id": tid, "file": dest.name, "title": tid, "artist": "DSPORTAL",
                      "license": "own", "own": True, "prompt": meta.get("prompt", ""),
                      "model": meta.get("model", "")}
    out = sorted(index.values(), key=lambda t: t["id"])
    OWN_INDEX.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def pick(seed: int) -> dict | None:
    """글마다 다른 트랙을 고른다(같은 글은 항상 같은 트랙 — 재렌더 재현성)."""
    own = _own_index()
    index = own if len(own) >= OWN_MIN else _load_index()
    if not index:
        index = fetch_library()
    if not index:
        return None
    # 얇은 트랙은 fetch 단계에서 이미 걸렀으므로(MIN_FULLNESS) 전부 후보로 쓴다.
    # 상위 절반으로 좁혔더니 9개 글 중 4개가 같은 곡을 받았다.
    #
    # seed를 그대로 % 하면 안 된다. 호출부의 crc32는 비슷한 제목("2026년 X 추천 TOP 5")에
    # 대해 하위 비트가 상관돼서, 실측상 9개 중 6개가 같은 나머지를 냈다.
    # md5로 한 번 더 섞어 분포를 고른다.
    mixed = int(hashlib.md5(str(seed).encode()).hexdigest()[:8], 16)
    return index[mixed % len(index)]


def mix(narration: Path, out_path: Path, track: dict, duration: float,
        workdir: Path) -> bool:
    """내레이션 + BGM을 합쳐 out_path에 쓴다. 실패하면 False(호출부는 원본 유지)."""
    src = (OWN_DIR if track.get("own") else CACHE_DIR) / track["file"]
    if not src.exists():
        return False
    offset = best_offset(src, duration)
    fade_start = max(duration - FADE_SEC, 0.0)

    # 고른 구간을 먼저 잘라낸다. -ss와 -stream_loop을 한 번에 쓰면 루프가 파일 처음으로
    # 돌아가는지 seek 지점으로 돌아가는지가 ffmpeg 버전에 따라 달라서, 두 단계로 나눈다.
    seg = workdir / "bgm_seg.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-stream_loop", "-1", "-ss", f"{offset:.3f}", "-i", str(src),
         "-t", f"{duration:.3f}", "-ac", "2", "-ar", "48000", str(seg)],
        capture_output=True, check=False,
    )
    if not seg.exists() or seg.stat().st_size == 0:
        return False
    log.info(f"BGM 구간: {offset:.1f}초부터 {duration:.1f}초 사용")

    # 내레이션과 BGM의 실제 음량을 각각 재서 상대 게인을 계산한다.
    nar_db = _mean_volume(narration)
    bgm_db = _mean_volume(seg)
    if nar_db is None or bgm_db is None:
        gain = -18.0          # 측정 실패 시 보수적인 기본값
    else:
        gain = (nar_db - BGM_BELOW_NARRATION_DB) - bgm_db
    gain = max(min(gain, 0.0), -30.0)   # 증폭은 하지 않고, 지나친 감쇠도 막는다
    log.info(f"BGM 게인 {gain:+.1f}dB (내레이션 {nar_db}dB, BGM {bgm_db}dB)")

    # 내레이션을 둘로 나눠 하나는 믹스에, 하나는 더킹의 사이드체인 입력으로 쓴다.
    filt = (
        f"[0:a]asplit=2[nar][key];"
        f"[1:a]volume={gain:.2f}dB,"
        f"afade=t=in:st=0:d={FADE_SEC},"
        f"afade=t=out:st={fade_start:.3f}:d={FADE_SEC}[bgv];"
        f"[bgv][key]sidechaincompress={DUCK}[duck];"
        f"[nar][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
    )
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(narration), "-i", str(seg),
             "-filter_complex", filt, "-map", "[a]", "-c:a", "aac", "-b:a", "192k",
             str(out_path)],
            capture_output=True, check=True,
        )
    except subprocess.CalledProcessError as e:
        log.warning(f"BGM 믹싱 실패: {e.stderr.decode('utf-8', 'replace')[-200:]}")
        return False
    return True


def credit(track: dict) -> str:
    """설명란에 넣을 저작자 표시 — CC BY는 표시가 의무다. 자체 제작 곡은 표시할 것이 없다."""
    if track.get("own"):
        return ""
    return (f"음악: {track['title']} — {track['artist']} "
            f"({track['license']}, {track['page']})")
