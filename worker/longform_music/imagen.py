"""Imagen(Vertex AI)으로 영상 배경·썸네일에 쓸 16:9 이미지 한 장을 만든다.

- 호출: {model}:predict, instances[0].prompt, parameters.aspectRatio "16:9". 결과는 predictions[0].bytesBase64Encoded.
- 모델: imagen-4.0-generate-001(이미지 1장 약 $0.04), 없으면 imagen-3.0-generate-002. IMAGEN_MODEL 로 바꿀 수 있다.
- 인증은 Lyria 와 같다(veo._vertex_auths): 토큰이면 프로젝트 경로(us-central1), 키면 익스프레스 경로도 시도.
- 사람은 넣지 않는다(personGeneration dont_allow). 결과물에는 SynthID 워터마크가 들어간다.
- Imagen 이 막히면 Gemini 이미지 모델(gemini-2.5-flash-image, generateContent, global)로 한 번 더.
  2026-10-10: dsportal 프로젝트는 결제가 꺼져 403, API 키 프로젝트에는 Imagen 이 없어 404 였다.
  Lyria 는 같은 키·global·generateContent 로 됐다.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path

MODELS = [os.environ["IMAGEN_MODEL"]] if os.environ.get("IMAGEN_MODEL") else ["imagen-4.0-generate-001",
                                                                              "imagen-3.0-generate-002"]
GEMINI_MODELS = [os.environ["GEMINI_IMAGE_MODEL"]] if os.environ.get("GEMINI_IMAGE_MODEL") else [
    "gemini-2.5-flash-image"]
PRICE_USD = 0.04                # Imagen 4 표준·Gemini 2.5 Flash Image 모두 장당 약 $0.04
LOC = "us-central1"


class ImagenError(RuntimeError):
    pass


def endpoints(auths: list[tuple[dict, str]], model: str) -> list[tuple[dict, str]]:
    out = []
    for h, project in auths:
        if project:
            out.append((h, f"https://{LOC}-aiplatform.googleapis.com/v1/projects/{project}/locations/{LOC}"
                           f"/publishers/google/models/{model}:predict"))
        if "x-goog-api-key" in h or not project:
            out.append((h, f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:predict"))
    return out


def gemini_endpoints(auths: list[tuple[dict, str]], model: str) -> list[tuple[dict, str]]:
    out = []
    for h, project in auths:
        if project:
            out.append((h, f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global"
                           f"/publishers/google/models/{model}:generateContent"))
        if "x-goog-api-key" in h or not project:
            out.append((h, f"https://aiplatform.googleapis.com/v1/publishers/google/models/{model}:generateContent"))
    return out


def gemini_body(prompt: str) -> dict:
    return {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "16:9"}}}


def gemini_image(js: dict) -> bytes | None:
    for c in js.get("candidates") or []:
        for p in (c.get("content") or {}).get("parts") or []:
            d = p.get("inlineData") or p.get("inline_data")
            if d and d.get("data") and str(d.get("mimeType") or d.get("mime_type") or "image").startswith("image"):
                return base64.b64decode(d["data"])
    return None


def request_body(prompt: str) -> dict:
    return {"instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1, "aspectRatio": "16:9", "personGeneration": "dont_allow"}}


def generate(prompt: str, out: Path, client, auths: list[tuple[dict, str]]) -> dict:
    """이미지 한 장을 out(.png)에 저장. 모든 경로가 실패하면 ImagenError."""
    errors = []
    for model in MODELS:
        for h, url in endpoints(auths, model):
            r = client.post(url, headers={**h, "Content-Type": "application/json"}, json=request_body(prompt),
                            timeout=180)
            if r.status_code != 200:
                errors.append(f"{model} {r.status_code}: {r.text[:160]}")
                continue
            preds = r.json().get("predictions") or []
            data = next((p.get("bytesBase64Encoded") for p in preds if p.get("bytesBase64Encoded")), None)
            if not data:
                errors.append(f"{model} 이미지 없음(안전 필터?)")
                continue
            out.write_bytes(base64.b64decode(data))
            return {"file": out.name, "model": model, "prompt": prompt}
    for model in GEMINI_MODELS:
        for h, url in gemini_endpoints(auths, model):
            r = client.post(url, headers={**h, "Content-Type": "application/json"}, json=gemini_body(prompt),
                            timeout=180)
            if r.status_code != 200:
                errors.append(f"{model} {r.status_code}: {r.text[:160]}")
                continue
            img = gemini_image(r.json())
            if not img:
                errors.append(f"{model} 이미지 없음")
                continue
            out.write_bytes(img)
            return {"file": out.name, "model": model, "prompt": prompt}
    raise ImagenError("; ".join(errors)[:600] or "인증 없음")
