"""곡 자동 검사와 3시간 오디오 조립.

검사(곡마다) — 수면 음악에서 문제가 되는 것만 본다.
- 너무 짧음(60초 미만), 중간 무음(3초 이상 -60dBFS 아래), 1초 단위 음량이 갑자기 튐(12dB 이상),
  전체적으로 너무 큼/작음, 같은 파일 중복. 보컬(가사)은 lyria.lyrics_in 이 생성 때 표시한다.
조립 — 곡마다 음량을 맞추고(loudnorm -20 LUFS) 겹쳐 잇기(acrossfade)로 이은 뒤 정확히 목표 길이로 자른다.
곡이 모자라면 같은 곡을 순서를 바꿔 한 번 더 쓰고, 그 사실을 보고서에 남긴다.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import numpy as np

SR = 8000                       # 검사용으로만 낮춰서 읽는다
MIN_SEC = 60
SILENCE_DB = -60.0
SILENCE_RUN = 3
JUMP_DB = 12.0
EDGE_SEC = 15                   # 시작·끝 페이드 구간은 무음·튐 검사에서 뺀다(Lyria 곡은 도입·마무리가 길다)
SMOOTH = 3                      # 급변은 3초 평균끼리 비교 — 빗방울 하나·건반 하나에 걸리지 않게
QC_VERSION = 2                  # 검사 기준을 바꾸면 올린다 → 이미 만든 곡을 다시 검사(재생성·재과금 없음)
TARGET_LUFS = -20


def ffprobe_duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return float(json.loads(r.stdout)["format"]["duration"])


def _pcm(path: Path) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32)


def rms_per_second(x: np.ndarray) -> np.ndarray:
    n = len(x) // SR
    if n == 0:
        return np.array([])
    blocks = x[: n * SR].reshape(n, SR).astype(np.float64)
    rms = np.sqrt((blocks ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9))


def analyze(path: Path) -> dict:
    x = _pcm(path)
    dur = len(x) / SR
    db = rms_per_second(x)
    core = db[EDGE_SEC:-EDGE_SEC] if len(db) > 2 * EDGE_SEC + 2 else db
    problems = []
    if dur < MIN_SEC:
        problems.append(f"짧음 {dur:.0f}초")
    run = longest = 0
    for v in core:
        run = run + 1 if v < SILENCE_DB else 0
        longest = max(longest, run)
    if longest >= SILENCE_RUN:
        problems.append(f"중간 무음 {longest}초")
    sm = np.convolve(core, np.ones(SMOOTH) / SMOOTH, mode="valid") if len(core) >= SMOOTH else core
    jump = float(np.max(np.abs(sm[SMOOTH:] - sm[:-SMOOTH]))) if len(sm) > SMOOTH else 0.0
    if jump >= JUMP_DB:
        problems.append(f"음량 급변 {jump:.1f}dB")
    level = float(20 * np.log10(max(np.sqrt(np.mean(x.astype(np.float64) ** 2)), 1e-9))) if len(x) else -120.0
    if level < -50:
        problems.append(f"너무 작음 {level:.0f}dBFS")
    peak = float(np.max(np.abs(x))) if len(x) else 0.0
    return {"version": QC_VERSION, "duration": round(dur, 2), "rms_db": round(level, 1), "max_jump_db": round(jump, 1),
            "longest_silence": int(longest), "peak": round(peak, 3),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "problems": problems}


def sequence(tracks: list[dict], target: float, xfade: float) -> list[dict]:
    """목표 길이를 채울 곡 순서. 한 바퀴로 모자라면 순서를 한 칸씩 돌려 다시 쓴다(바로 반복 방지)."""
    if not tracks:
        raise ValueError("쓸 곡이 없다")
    seq, total, rnd = [], 0.0, 0
    while total < target:
        order = tracks[rnd % len(tracks):] + tracks[: rnd % len(tracks)] if rnd else list(tracks)
        if rnd and seq and order[0]["id"] == seq[-1]["id"]:
            order = order[1:] + order[:1]
        for t in order:
            seq.append(t)
            total += t["duration"] - (xfade if len(seq) > 1 else 0)
            if total >= target:
                break
        rnd += 1
    return seq


def normalize(src: Path, dst: Path) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
                    "-af", f"loudnorm=I={TARGET_LUFS}:TP=-2:LRA=7", "-ar", "48000", "-ac", "2", str(dst)], check=True)


def assemble(files: list[Path], out: Path, target: float, xfade: float = 8.0,
             fade_in: float = 10.0, fade_out: float = 30.0) -> list[float]:
    """files 를 겹쳐 이어 target 초짜리 AAC(m4a)로 만든다. 각 곡이 시작하는 시각(초) 목록을 돌려준다(챕터용)."""
    durs = [ffprobe_duration(f) for f in files]
    starts, t = [], 0.0
    for i, d in enumerate(durs):
        starts.append(round(t, 2))
        t += d - xfade
    tmp = []
    if len(files) > CHUNK:
        # 곡이 많으면(6시간 이상 ≈ 140곡) 한 번에 이으면 러너 메모리가 바닥난다(2026-10-12 sleep-003 러너 종료).
        # CHUNK 곡씩 먼저 이어 FLAC 으로 만든 뒤 묶음끼리 같은 길이로 겹쳐 잇는다 — 이음 시각은 같다.
        groups = [files[i:i + CHUNK] for i in range(0, len(files), CHUNK)]
        for gi, g in enumerate(groups):
            part = out.with_name(f"{out.stem}.part{gi:02d}.flac")
            _crossfade(g, part, xfade, ["-c:a", "flac"])
            tmp.append(part)
        files = tmp
    graph_tail = (f"atrim=0:{target},asetpts=N/SR/TB,afade=t=in:st=0:d={fade_in},"
                  f"afade=t=out:st={target - fade_out}:d={fade_out}")
    _crossfade(files, out, xfade, ["-c:a", "aac", "-b:a", "256k"], graph_tail)
    for f in tmp:
        f.unlink(missing_ok=True)
    return [s for s in starts if s < target]


CHUNK = 24


def _crossfade(files: list[Path], out: Path, xfade: float, codec: list[str], tail: str = "") -> None:
    inputs = []
    for f in files:
        inputs += ["-i", str(f)]
    if len(files) == 1:
        chain, last = "", "[0:a]"
    else:
        parts, last = [], "[0:a]"
        for i in range(1, len(files)):
            lab = f"[x{i}]"
            parts.append(f"{last}[{i}:a]acrossfade=d={xfade}:c1=tri:c2=tri{lab}")
            last = lab
        chain = ";".join(parts) + ";"
    graph = f"{chain}{last}{tail or 'anull'}[out]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[out]",
                    "-ar", "48000", *codec, str(out)], check=True)
