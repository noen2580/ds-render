"""Gemini TTS — edge-tts 가 막혔을 때 쓰는 예비 음성(2026-10-13).

2026-10-12 오후부터 마이크로소프트 읽어주기 서버가 edge-tts 연결을 403 으로 거절해 상품 쇼츠
#48·#49 가 에셋 단계에서 실패했다(SLA 없는 비공식 경로라 언제든 생길 수 있다). 렌더 워커에는
이미 Veo 용 GEMINI_API_KEY 가 있으니 그 키로 Gemini 음성 생성을 부른다.

응답은 24kHz 16bit 모노 PCM(base64)이라 ffmpeg 로 요청한 확장자(mp3·wav)로 바꾼다.
모델은 GEMINI_TTS_MODEL(쉼표로 여러 개) → 기본 목록 순서로 시도한다.
그다음 Vertex Gemini 음성, Cloud Text-to-Speech(Chirp 3 HD) 순."""
import base64
import os
import re
import subprocess
import tempfile
from pathlib import Path

import httpx

DEFAULT_MODELS = ("gemini-2.5-flash-preview-tts", "gemini-2.5-pro-preview-tts")
VERTEX_MODELS = ("gemini-2.5-flash-tts", "gemini-2.5-flash-preview-tts", "gemini-2.5-pro-tts")
DEFAULT_VOICE = os.environ.get("GEMINI_TTS_VOICE") or "Kore"
CLOUD_VOICE = os.environ.get("CLOUD_TTS_VOICE") or "ko-KR-Chirp3-HD-Kore"
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
CLOUD_TTS = "https://texttospeech.googleapis.com/v1/text:synthesize"

# 2026-10-13 14:50 회차: GEMINI_API_KEY 가 Generative Language API 에 막혀(403, 키 API 제한) 대체도 실패했다.
# 그래서 Veo·Lyria 가 이미 쓰는 Vertex 인증(워크로드 아이덴티티·VERTEX_API_KEY)으로 Vertex Gemini 음성과
# Cloud Text-to-Speech(Chirp 3 HD)도 차례로 시도한다. 한 번 통한 경로는 기억해 다음 장면부터 바로 쓴다.
_ok: str | None = None


def _vertex_auths() -> list[tuple[dict, str]]:
    try:
        import veo
        return veo._vertex_auths() if veo._vertex_on() else []
    except Exception as e:                                   # noqa: BLE001
        print(f"  Vertex 인증 준비 실패: {type(e).__name__}: {e}")
        return []


def available() -> bool:
    if os.environ.get("GEMINI_API_KEY"):
        return True
    try:
        import veo
        return veo._vertex_on()
    except Exception:                                        # noqa: BLE001
        return False


def _models() -> list[str]:
    env = [m.strip() for m in (os.environ.get("GEMINI_TTS_MODEL") or "").split(",") if m.strip()]
    return env + [m for m in DEFAULT_MODELS if m not in env]


def _rate(mime: str) -> int:
    m = re.search(r"rate=(\d+)", mime or "")
    return int(m.group(1)) if m else 24000


def _routes(voice: str) -> list[tuple]:
    """(이름, url, headers, params, body, kind) — kind 'gemini'(PCM) 또는 'cloud'(MP3)."""
    gem = {"contents": [{"role": "user", "parts": [{"text": "{text}"}]}],
           "generationConfig": {"responseModalities": ["AUDIO"],
                                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    out = []
    key = os.environ.get("GEMINI_API_KEY")
    # "AQ." 로 시작하는 키는 Vertex(에이전트 플랫폼) 전용이라 Gemini API(generativelanguage)는 늘 403 이다
    # (2026-10-13 확인: 렌더 워커의 GEMINI_API_KEY 가 영상 전용 AQ 키). 그런 키는 아래 Vertex 경로에서만 쓴다.
    if key and not key.startswith("AQ."):
        out += [(f"gemini-api/{m}", API.format(model=m), {}, {"key": key}, gem, "gemini") for m in _models()]
    auths = _vertex_auths()
    for h, project in auths:
        how = "키" if "x-goog-api-key" in h else "토큰"
        bases = []
        if project:
            bases.append(f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global/publishers/google/models/")
        if "x-goog-api-key" in h or not project:
            bases.append("https://aiplatform.googleapis.com/v1/publishers/google/models/")
        out += [(f"vertex({how})/{m}", b + f"{m}:generateContent", h, {}, gem, "gemini")
                for b in bases for m in VERTEX_MODELS]
    # Cloud Text-to-Speech: Gemini 음성(같은 목소리) → Chirp 3 HD 순
    clouds = [(f"gemini-2.5-flash-tts/{voice}",
               {"languageCode": "ko-KR", "name": voice, "modelName": "gemini-2.5-flash-tts"}),
              (CLOUD_VOICE, {"languageCode": "ko-KR", "name": CLOUD_VOICE})]
    for h, project in auths:
        how = "키" if "x-goog-api-key" in h else "토큰"
        hh = dict(h, **({"x-goog-user-project": project} if project and "Authorization" in h else {}))
        for label, v in clouds:
            body = {"input": {"text": "{text}"}, "voice": v, "audioConfig": {"audioEncoding": "MP3"}}
            out.append((f"cloud-tts({how})/{label}", CLOUD_TTS, hh, {}, body, "cloud"))
    return out


def _fill(body: dict, text: str) -> dict:
    import json
    return json.loads(json.dumps(body).replace('"{text}"', json.dumps(text)))


def _convert(data: bytes, args: list[str], out_path: Path) -> None:
    with tempfile.NamedTemporaryFile(suffix=".raw", delete=False) as f:
        f.write(data)
        raw = f.name
    try:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-i", raw, str(out_path)], check=True)
    finally:
        os.unlink(raw)


def _try(route: tuple, text: str, out_path: Path, timeout: float) -> str | None:
    """성공하면 None, 실패하면 오류 한 줄."""
    name, url, headers, params, body, kind = route
    try:
        r = httpx.post(url, params=params or None, headers=headers or None, json=_fill(body, text), timeout=timeout)
        if r.status_code != 200:
            return f"{name}: HTTP {r.status_code} {r.text[:120]}"
        js = r.json()
        if kind == "cloud":
            mp3 = base64.b64decode(js["audioContent"])
            if not mp3:
                return f"{name}: 빈 음성"
            _convert(mp3, ["-f", "mp3"], out_path)
            return None
        part = js["candidates"][0]["content"]["parts"][0]["inlineData"]
        pcm = base64.b64decode(part["data"])
        if not pcm:
            return f"{name}: 빈 음성"
        _convert(pcm, ["-f", "s16le", "-ar", str(_rate(part.get("mimeType"))), "-ac", "1"], out_path)
        return None
    except (KeyError, IndexError, ValueError, httpx.HTTPError, subprocess.CalledProcessError) as e:
        return f"{name}: {type(e).__name__} {str(e)[:120]}"


def synthesize(text: str, out_path: Path, voice: str = DEFAULT_VOICE, timeout: float = 90) -> None:
    global _ok
    routes = _routes(voice)
    if not routes:
        raise RuntimeError("GEMINI_API_KEY·Vertex 인증 없음 — 예비 음성을 쓸 수 없다")
    if _ok:
        routes = [r for r in routes if r[0] == _ok] + [r for r in routes if r[0] != _ok]
    errors = []
    for route in routes:
        err = _try(route, text, out_path, timeout)
        if err is None:
            if _ok != route[0]:
                print(f"   예비 음성 경로: {route[0]}")
            _ok = route[0]
            return
        errors.append(err)
    raise RuntimeError("예비 음성 실패 — " + " | ".join(errors))
