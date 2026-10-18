"""제목·설명 번역(유튜브 localizations) — 해외 시청자가 자기 언어로 검색해도 찾고, 자기 언어 제목을 보게 한다.

- 유튜브는 시청자 언어에 맞는 번역 제목·설명을 보여 주고 그 언어 검색에도 쓴다(Studio '자막 > 제목·설명' 과 같은 것).
- Gemini(gemini-2.5-flash, Lyria 와 같은 키·global·generateContent)로 한 번에 번역한다. 영상당 1회, 몇 센트 이하.
- 의학적 주장(치료·불면증 치료 등)은 번역에서도 넣지 않는다. 타임스탬프 줄은 그대로 둔다(챕터).
"""
from __future__ import annotations

import json
import os

MODEL = os.environ.get("LOCALIZE_MODEL", "gemini-2.5-flash")
# 수면 음악 수요가 큰 언어권(조회수 상위 채널의 시청 지역 기준) — 영어는 기본 언어라 뺀다
LANGS = {"es": "Spanish", "pt": "Portuguese (Brazil)", "de": "German", "fr": "French", "it": "Italian",
         "ja": "Japanese", "ko": "Korean", "id": "Indonesian", "hi": "Hindi", "tr": "Turkish"}


class LocalizeError(RuntimeError):
    pass


def prompt(title: str, description: str, langs: dict) -> str:
    return (
        "Translate this YouTube sleep-music video title and description for native viewers in each language below. "
        "Write natural titles a native speaker would search for (use the common local words for sleep music, "
        "rain/ocean/forest/space sounds, relaxing, fall asleep). Rules: title at most 100 characters; keep '#N' "
        "series numbers and '|' or '•' separators; keep every timestamp line (like 1:02:03 Name) exactly as is "
        "except you may translate the name after the timestamp; keep hashtags in English; never add medical or "
        "health claims (no 'cure', 'treat', 'therapy', 'heal insomnia'); keep the AI-music disclosure meaning.\n"
        f"Languages (code: name): {json.dumps(langs, ensure_ascii=False)}\n"
        'Answer only JSON: {"<code>": {"title": "...", "description": "..."}, ...}\n\n'
        f"TITLE:\n{title}\n\nDESCRIPTION:\n{description}")


def endpoints(auths: list[tuple[dict, str]]) -> list[tuple[dict, str]]:
    out = []
    for h, project in auths:
        if project:
            out.append((h, f"https://aiplatform.googleapis.com/v1/projects/{project}/locations/global"
                           f"/publishers/google/models/{MODEL}:generateContent"))
        if "x-goog-api-key" in h or not project:
            out.append((h, f"https://aiplatform.googleapis.com/v1/publishers/google/models/{MODEL}:generateContent"))
    return out


TITLE_CHARS, DESC_BYTES = 100, 5000          # 유튜브 한도: 제목 100자, 설명 5000바이트(글자 수 아님 — 힌디어·일본어는 한 글자 3바이트)


def clean_title(t: str) -> str:
    return t.replace("<", "").replace(">", "").strip()[:TITLE_CHARS]


def clean_description(d: str, limit: int = DESC_BYTES) -> str:
    """'<' '>' 는 유튜브가 거절한다. 5000바이트를 넘으면 줄 단위로 자른다(타임스탬프 줄이 반쯤 잘리지 않게)."""
    d = d.replace("<", "").replace(">", "").strip()
    if len(d.encode()) <= limit:
        return d
    out, size = [], 0
    for line in d.split("\n"):
        n = len(line.encode()) + 1
        if size + n > limit:
            break
        out.append(line)
        size += n
    return "\n".join(out).strip() or d.encode()[:limit].decode(errors="ignore")


def parse(js: dict, langs: dict) -> dict:
    text = "".join(p.get("text", "") for c in js.get("candidates") or []
                   for p in (c.get("content") or {}).get("parts") or [])
    try:
        raw = json.loads(text[text.find("{"):text.rfind("}") + 1])
    except ValueError as e:
        raise LocalizeError(f"JSON 아님: {text[:120]}") from e
    out = {}
    for code in langs:
        v = raw.get(code) or {}
        t, d = str(v.get("title", "")).strip(), str(v.get("description", "")).strip()
        if t and d:
            out[code] = {"title": clean_title(t), "description": clean_description(d)}
    if not out:
        raise LocalizeError("번역이 비었다")
    return out


def translate(title: str, description: str, client, auths: list[tuple[dict, str]], langs: dict | None = None) -> dict:
    """{언어코드: {title, description}}. 모든 경로가 실패하면 LocalizeError."""
    langs = langs or LANGS
    body = {"contents": [{"role": "user", "parts": [{"text": prompt(title, description, langs)}]}],
            "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 60000,
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    errors = []
    for h, url in endpoints(auths):
        r = client.post(url, headers={**h, "Content-Type": "application/json"}, json=body, timeout=300)
        if r.status_code != 200:
            errors.append(f"{r.status_code}: {r.text[:160]}")
            continue
        try:
            return parse(r.json(), langs)
        except LocalizeError as e:
            errors.append(str(e))
    raise LocalizeError("; ".join(errors)[:600] or "인증 없음")


def for_video(title: str, description: str) -> dict:
    """업로드용 — 실패해도 업로드는 막지 않는다(빈 dict)."""
    if os.environ.get("LONGFORM_LOCALIZE", "1") == "0":
        return {}
    import httpx
    import veo
    try:
        with httpx.Client(follow_redirects=True) as c:
            loc = translate(title, description, c, veo._vertex_auths())
        print(f"번역: {', '.join(loc)}")
        return loc
    except Exception as e:                      # noqa: BLE001
        print(f"번역 실패 — 영어로만 올림: {e}")
        return {}
