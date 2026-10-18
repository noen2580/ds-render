"""Lyria 3 Pro(Vertex AI)로 곡 한 개를 만든다.

확인한 사실 (2026-10-10, Google 공식 노트북 lyria3_music_generation.ipynb · Vertex AI 가격표)
- 모델: lyria-3-pro-preview(최대 약 3분 곡), lyria-3-clip-preview(30초). 위치는 global.
- 호출: generateContent, responseModalities ["AUDIO","TEXT"]. 오디오는 inlineData(base64),
  텍스트 파트에는 곡 구조나 가사가 온다. 길이는 파라미터가 아니라 프롬프트로 정한다.
- 가격: Lyria 3 Pro 곡 1개 $0.08, Lyria 3 클립 $0.04, Lyria 2(lyria-002, 30초) $0.06.
  → 3시간을 3분 곡으로 채우면 약 60곡 ≈ $4.8. ChatGPT 안의 Lyria 2(30초×360개 ≈ $21.6)보다 싸다.
- 결과물에는 SynthID 워터마크와 C2PA 정보가 들어간다.

인증은 쇼츠 Veo 와 같다(youtube_shorts/veo.py 의 _vertex_auths): 워크로드 아이덴티티/GCP_SA_KEY 토큰 →
VERTEX_API_KEY(키만으로 부르는 익스프레스 경로 포함). 모델은 LYRIA_MODEL 로 바꿀 수 있다.
"""
from __future__ import annotations

import base64
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "youtube_shorts"))

MODEL = os.environ.get("LYRIA_MODEL") or "lyria-3-pro-preview"
PRICE_USD = {"lyria-3-pro-preview": 0.08, "lyria-3-clip-preview": 0.04}
EXT = {"audio/mpeg": ".mp3", "audio/mp3": ".mp3", "audio/wav": ".wav", "audio/x-wav": ".wav",
       "audio/wave": ".wav", "audio/flac": ".flac", "audio/ogg": ".ogg", "audio/aac": ".aac", "audio/mp4": ".m4a"}


class LyriaError(RuntimeError):
    pass


def price() -> float:
    return PRICE_USD.get(MODEL, 0.08)


def endpoints(auths: list[tuple[dict, str]]) -> list[tuple[dict, str]]:
    """(헤더, URL) 시도 목록. 프로젝트가 있으면 프로젝트 경로, API 키는 익스프레스 경로도 한 번 더."""
    out = []
    for h, project in auths:
        if project:
            out.append((h, f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global"
                           f"/publishers/google/models/{MODEL}:generateContent"))
        if "x-goog-api-key" in h or not project:
            out.append((h, f"https://aiplatform.googleapis.com/v1/publishers/google/models/{MODEL}:generateContent"))
    return out


def request_body(prompt: str) -> dict:
    return {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["AUDIO", "TEXT"]}}


def parse_response(js: dict) -> tuple[bytes, str, str]:
    """(오디오 바이트, mime, 텍스트). 오디오가 없으면 LyriaError(안전 필터 차단 등)."""
    cands = js.get("candidates") or []
    if not cands:
        fb = js.get("promptFeedback") or {}
        raise LyriaError(f"후보 없음 {fb.get('blockReason') or ''}".strip())
    parts = (cands[0].get("content") or {}).get("parts") or []
    audio, mime, text = b"", "", []
    for p in parts:
        d = p.get("inlineData") or p.get("inline_data")
        if d and d.get("data") and not audio:
            audio = base64.b64decode(d["data"])
            mime = d.get("mimeType") or d.get("mime_type") or ""
        elif p.get("text"):
            text.append(p["text"])
    if not audio:
        raise LyriaError(f"오디오 없음 finishReason={cands[0].get('finishReason')}")
    return audio, mime, "\n".join(text)


def lyrics_in(text: str) -> bool:
    """텍스트 파트에 가사가 있으면 보컬이 들어간 곡이다. 구간 태그·시각 표시를 지우고 단어가 남는지 본다.
    ([[Intro]] [0.0:] 같은 표시만 있으면 기악곡)"""
    t = re.sub(r"\[\[.*?\]\]", " ", text or "")
    t = re.sub(r"\[[\d.:\s]*\]", " ", t)
    t = re.sub(r"\((?:instrumental|inst\.?)[^)]*\)", " ", t, flags=re.I)
    words = re.findall(r"[^\W\d_]{2,}", t)
    words = [w for w in words if w.lower() not in {"intro", "outro", "verse", "chorus", "bridge", "instrumental",
                                                   "interlude", "ambient", "section", "break", "end", "fade",
                                                   "build", "drop", "pre", "post", "hook", "solo"}]
    return len(words) >= 8


def generate(prompt: str, out_base: Path, client, auths: list[tuple[dict, str]] | None = None,
             retries: int = 3) -> dict:
    """곡을 out_base(확장자 없이)+확장자로 저장. {'file','mime','text','vocals'} 를 돌려준다. 실패는 LyriaError."""
    if auths is None:
        import veo
        auths = veo._vertex_auths()
    if not auths:
        raise LyriaError("Vertex 인증 없음 — VERTEX_API_KEY 또는 GCP 인증이 필요하다")
    last = ""
    for h, url in endpoints(auths):
        for attempt in range(retries):
            r = client.post(url, headers={**h, "Content-Type": "application/json"},
                            json=request_body(prompt), timeout=600)
            if r.status_code == 200:
                audio, mime, text = parse_response(r.json())
                f = out_base.with_suffix(EXT.get(mime.split(";")[0].strip().lower(), ".wav"))
                f.write_bytes(audio)
                return {"file": f.name, "mime": mime, "text": text[:4000], "vocals": lyrics_in(text)}
            last = f"{r.status_code} {r.text[:300]}"
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            break                               # 401/403/404 — 다음 인증·경로로
    raise LyriaError(f"Lyria 호출 실패: {last}")
