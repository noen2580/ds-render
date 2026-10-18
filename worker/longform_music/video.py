"""배경 영상·썸네일·최종 렌더·최종 검사.

배경은 직접 만든다(남의 영상·이미지 라이선스 문제 없음): 짙은 밤하늘 그라디언트 + 천천히 깜빡이는 별 +
은은한 달빛. 별 밝기는 루프 길이로 나누어떨어지는 주기라서 이음매 없이 반복된다.
기본은 Imagen 으로 만든 장면 이미지에 아주 느린 줌(run.background_image). 실패하면 위 밤하늘.
--background 로 직접 고른 이미지·영상을 줄 수도 있다(그때는 사용 허가를 직접 확인).

3시간을 통째로 인코딩하지 않는다: 60초 루프만 한 번 인코딩하고, 최종 파일은 그 루프를 복사로 이어
붙인다(-stream_loop, -c copy). 그래서 렌더가 몇 분이면 끝난다.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

W, H, FPS = 1920, 1080, 24
LOOP_SEC = 60
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp")
TWINKLE = 160                   # 이미지 배경 위에 반짝이는 별 개수(0 이면 끔). 상위 영상은 '살짝 움직이는' 화면(2026-10-11 조사)
ZOOM = 0.04                     # 이미지 배경은 루프 동안 4%까지 천천히 다가갔다 돌아온다(처음=끝이라 이음매 없음)


def night_sky_frames(seconds: int = 60, fps: int = FPS, w: int = W, h: int = H, seed: int = 7):
    rnd = np.random.default_rng(seed)
    y = np.linspace(0, 1, h)[:, None, None]
    top, bottom = np.array([6, 10, 28]), np.array([22, 30, 62])
    base = (top + (bottom - top) * y ** 1.4) * np.ones((1, w, 1))
    # 달빛(오른쪽 위) 은은한 번짐
    yy, xx = np.mgrid[0:h, 0:w]
    glow = np.exp(-(((xx - w * 0.78) / (w * 0.22)) ** 2 + ((yy - h * 0.22) / (h * 0.3)) ** 2))[..., None]
    base = base + glow * np.array([28, 30, 40])
    n = 420
    sx, sy = rnd.integers(0, w - 2, n), (rnd.random(n) ** 1.6 * (h * 0.8)).astype(int)
    bright = rnd.uniform(90, 230, n)
    k = rnd.integers(1, 4, n)                   # 루프 동안 1~3번 깜빡 — 정수라서 루프 끝과 처음이 같다
    phase = rnd.uniform(0, 2 * np.pi, n)
    base = np.clip(base, 0, 255).astype(np.uint8)
    total = seconds * fps
    for f in range(total):
        frame = base.copy()
        a = 0.55 + 0.45 * np.sin(2 * np.pi * k * f / total + phase)
        v = (bright * a)[:, None]
        for dy in (0, 1):
            for dx in (0, 1):
                lit = np.clip(v * (1 if dx == dy == 0 else 0.45), 0, 255).astype(np.uint8)
                frame[sy + dy, sx + dx] = np.maximum(frame[sy + dy, sx + dx], lit)
        yield frame


def twinkle_frames(seconds: int = 60, fps: int = FPS, w: int = W, h: int = H, n: int = TWINKLE, seed: int = 11):
    """검은 바탕에 반짝이는 작은 별만(이미지 위에 screen 으로 겹친다). 화면 위쪽 절반(하늘)에만, 은은하게.
    깜빡임 주기가 루프 길이로 나누어떨어져 이음매가 없다."""
    rnd = np.random.default_rng(seed)
    sx, sy = rnd.integers(0, w - 2, n), (rnd.random(n) ** 1.3 * (h * 0.5)).astype(int)
    bright = rnd.uniform(70, 190, n)
    k = rnd.integers(1, 4, n)
    phase = rnd.uniform(0, 2 * np.pi, n)
    total = seconds * fps
    for f in range(total):
        frame = np.zeros((h, w, 3), np.uint8)
        a = np.clip(np.sin(2 * np.pi * k * f / total + phase), 0, 1) ** 2      # 대부분 꺼져 있다가 잠깐 빛난다
        v = (bright * a)[:, None]
        for dy in (0, 1):
            for dx in (0, 1):
                frame[sy + dy, sx + dx] = np.clip(v * (1 if dx == dy == 0 else 0.4), 0, 255).astype(np.uint8)
        yield frame


def make_loop(out: Path, background: Path | None = None, seconds: int | None = None) -> Path:
    """1080p 루프 영상. 키프레임을 루프 시작에 두어 복사 이어 붙이기가 깨끗하다."""
    seconds = seconds or LOOP_SEC
    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-g", str(FPS * 4), "-r", str(FPS), "-an", "-movflags", "+faststart"]
    if background is None:
        p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                              "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", *enc, str(out)], stdin=subprocess.PIPE)
        for fr in night_sky_frames(seconds):
            p.stdin.write(fr.tobytes())
        p.stdin.close()
        if p.wait():
            raise RuntimeError("배경 루프 인코딩 실패")
        return out
    vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},format=yuv420p"
    is_image = background.suffix.lower() in IMAGE_EXT
    if is_image:
        # 멈춘 사진 대신 아주 느린 줌. 4K로 키운 뒤 줌해서 흔들림(정수 반올림)을 줄인다.
        n = seconds * FPS
        z = f"1+{ZOOM}*(1-cos(2*PI*on/{n}))/2"
        vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,crop={W * 2}:{H * 2},"
              f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS},format=yuv420p")
        src = ["-loop", "1", "-framerate", str(FPS), "-t", str(seconds), "-i", str(background)]
        if TWINKLE:
            fc = (f"[0:v]{vf.replace(',format=yuv420p', '')},format=gbrp[bg];[1:v]format=gbrp[st];"
                  f"[bg][st]blend=all_mode=screen,format=yuv420p[v]")
            p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", *src, "-f", "rawvideo", "-pix_fmt", "rgb24",
                                  "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-filter_complex", fc, "-map", "[v]",
                                  *enc, "-t", str(seconds), str(out)], stdin=subprocess.PIPE)
            try:
                for fr in twinkle_frames(seconds):
                    p.stdin.write(fr.tobytes())
                p.stdin.close()
            except BrokenPipeError:
                pass
            if p.wait():
                raise RuntimeError("배경 루프(별 반짝임) 인코딩 실패")
            return out
    else:
        src = ["-i", str(background)]
    subprocess.run(["ffmpeg", "-y", "-v", "error", *src, "-vf", vf, *enc, "-t", str(seconds), str(out)], check=True)
    return out


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def thumbnail(src: Path, out: Path, lines: list[str]) -> Path:
    """배경 이미지(또는 루프 영상의 한 장면)로 1280x720 JPG(유튜브 썸네일 2MB 제한 안).
    상위 수면 음악 썸네일은 글자가 없거나 2~3단어라(2026-10-11 조사) 띠 없이 큰 글자 한 줄만 올린다.
    채도·대비를 조금 올려 작은 화면에서도 장면이 살아 보이게 한다."""
    vf = ("scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,"
          "eq=saturation=1.15:contrast=1.06")
    if lines and Path(FONT).exists():
        vf += (f",drawtext=fontfile={FONT}:text='{_esc(lines[0])}':fontcolor=white:fontsize=110"
               f":x=(w-text_w)/2:y=h*0.68:borderw=4:bordercolor=black@0.55"
               f":shadowcolor=black@0.7:shadowx=4:shadowy=4")
    seek = [] if src.suffix.lower() in IMAGE_EXT else ["-ss", "2"]
    subprocess.run(["ffmpeg", "-y", "-v", "error", *seek, "-i", str(src), "-frames:v", "1", "-vf", vf,
                    "-q:v", "3", str(out)], check=True)
    return out


def render(loop: Path, audio: Path, out: Path, seconds: float) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", str(loop), "-i", str(audio),
                    "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-t", f"{seconds:.3f}",
                    "-movflags", "+faststart", str(out)], check=True)
    return out


def check(path: Path, seconds: float, tol: float = 2.0) -> dict:
    """최종 파일: 길이(영상·소리 모두), 1920x1080, H.264 + AAC 48kHz 스테레오."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration,size:stream=codec_type,codec_name,width,height,sample_rate,channels,duration",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    js = json.loads(r.stdout)
    v = next((s for s in js["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in js["streams"] if s["codec_type"] == "audio"), {})
    dur = float(js["format"]["duration"])
    problems = []
    if abs(dur - seconds) > tol:
        problems.append(f"길이 {dur:.1f}초(목표 {seconds:.0f})")
    for name, s in (("영상", v), ("소리", a)):
        if not s:
            problems.append(f"{name} 스트림 없음")
        elif s.get("duration") and abs(float(s["duration"]) - seconds) > tol:
            problems.append(f"{name} 길이 {float(s['duration']):.1f}초")
    if (v.get("width"), v.get("height")) != (W, H):
        problems.append(f"해상도 {v.get('width')}x{v.get('height')}")
    if v.get("codec_name") != "h264":
        problems.append(f"영상 코덱 {v.get('codec_name')}")
    if a.get("codec_name") != "aac" or str(a.get("sample_rate")) != "48000" or a.get("channels") != 2:
        problems.append(f"소리 {a.get('codec_name')}/{a.get('sample_rate')}/{a.get('channels')}ch")
    return {"duration": round(dur, 2), "size_mb": round(int(js["format"]["size"]) / 1e6, 1),
            "video": f"{v.get('codec_name')} {v.get('width')}x{v.get('height')}",
            "audio": f"{a.get('codec_name')} {a.get('sample_rate')}Hz {a.get('channels')}ch",
            "problems": problems, "ok": not problems}
