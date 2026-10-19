"""상품 쇼츠 훅 장면 — Veo(Gemini API)로 '불편한 상황' 4~6초 클립을 만든다.

왜 (2026-10-06)
---------------
상위 5% 쇼핑 쇼츠는 첫 1~3초에 움직이는 장면이 있다. 우리 영상은 글자 카드와 상품 사진뿐이라
"시연 장면이 없다"가 가장 큰 격차였다. 남의 영상(중국 사이트 등)은 저작권·재사용 콘텐츠 위험이
크고, AI 가 상품을 작동시키면 허위 시연이 된다. 그래서 **상품이 나오지 않는 불편 장면**만 만든다
(막힌 배수구, 벌어진 신발 밑창 …). 상품은 그대로 쿠팡 실제 사진으로 보여 준다.

규칙
- 프롬프트에 상품·브랜드·글자·로고·포장·얼굴을 넣지 않게 꼬리 문장을 붙인다.
- 실패(키 없음·쿼터·크레딧 소진·타임아웃)는 전부 None — 영상은 지금 방식(사진)으로 계속 만든다.
- 이 클립을 쓴 영상은 유튜브 업로드 때 '합성 콘텐츠'로 표시한다(make_explainer_short.produce).

호출 경로 두 가지 (2026-10-07)
- **Vertex AI**(우선): 제미나이 프로젝트(gen-lang-client-0948415395)를 깃헙 시크릿 GEMINI_API_KEY 로 부른다
  (2026-10-19 Somi — dsportal-491115 는 결제가 꺼져 있어 쓰지 않는다).
  인증은 ① 워크로드 아이덴티티(권장, 키 파일 없음 — 워크플로의 google-github-actions/auth 가
  GOOGLE_APPLICATION_CREDENTIALS 를 만든다) 또는 GCP_SA_KEY(서비스 계정 JSON) ② VERTEX_API_KEY
  (프로젝트는 VERTEX_API_KEY_PROJECT) — 앞의 것이 실패하면(결제 꺼짐 등) 다음 것을 시도한다.
  VERTEX_PROJECT(없으면 JSON 의 project_id), VERTEX_LOCATION(기본 us-central1),
  VEO_VERTEX_MODEL(없으면 VERTEX_MODELS 를 앞에서부터 — 404 면 다음 모델).
  소리는 끈다(generateAudio=false) — 내레이션·BGM 을 따로 깔고, 소리 없는 쪽이 싸다.
- **Gemini API**(예비): GEMINI_API_KEY, VEO_MODEL(기본 veo-3.1-lite-generate-preview).
VEO_OFF=1 이면 둘 다 끈다.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import httpx

API = "https://generativelanguage.googleapis.com/v1beta/"
DEFAULT_MODEL = "veo-3.1-lite-generate-preview"
SAFETY = ("Realistic vertical smartphone footage of an everyday home moment. Show only the problem situation. "
          "No products, no product packaging, no brand names, no logos, no text or captions on screen, "
          "no faces (hands and objects only), natural indoor light, steady handheld camera. "
          "The main subject fills the frame and is instantly recognizable at a glance, "
          "shown next to a hand or body part for scale. Small objects keep their real material and color "
          "(no metallic sheen unless they are metal) and sit on a light, contrasting surface.")
VERTEX_MODELS = ("veo-3.1-fast-generate-001", "veo-3.1-fast-generate-preview", "veo-3.0-fast-generate-001")
POLL_EVERY = 10
TIMEOUT = 6 * 60


def _vertex_on() -> bool:
    return bool(os.environ.get("GCP_SA_KEY") or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
                or os.environ.get("VERTEX_API_KEY"))


def enabled() -> bool:
    return (_vertex_on() or bool(os.environ.get("GEMINI_API_KEY"))) and os.environ.get("VEO_OFF") != "1"


def full_prompt(scene: str) -> str:
    return f"{scene.strip().rstrip('.')}. {SAFETY}"


def clip_seconds(hook_duration: float) -> int:
    """Veo 길이는 4·6·8초. 훅 장면보다 짧으면 끝에서 화면이 비므로 그보다 긴 것 중 가장 짧은 값."""
    for s in (4, 6, 8):
        if hook_duration <= s:
            return s
    return 8


def generate(scene: str, out: Path, seconds: int = 4, client: httpx.Client | None = None) -> Path | None:
    """클립을 out 에 저장하고 경로를 돌려준다. Vertex AI 를 먼저, 안 되면 Gemini API. 어떤 실패든 None."""
    if not (scene and scene.strip()) or os.environ.get("VEO_OFF") == "1":
        return None
    c = client or httpx.Client(timeout=120, follow_redirects=True)
    try:
        got = None
        if _vertex_on():
            try:
                got = _vertex(scene, out, seconds, c)
            except Exception as e:              # noqa: BLE001 — Vertex 가 안 되면 Gemini API 로 한 번 더
                print(f"  Veo(Vertex) 실패: {type(e).__name__}: {e}")
        if not got and os.environ.get("GEMINI_API_KEY"):
            got = _gemini(scene, out, seconds, c)
        return got
    except Exception as e:                      # noqa: BLE001 — 실패해도 영상은 사진으로 계속 만든다
        print(f"  Veo 실패: {type(e).__name__}: {e}")
        return None
    finally:
        if client is None:
            c.close()


def _vertex_auths() -> list[tuple[dict, str]]:
    """시도할 (헤더, 프로젝트) 목록. 서비스 계정 JSON 또는 워크로드 아이덴티티(ADC) 토큰 → API 키 순.
    API 키는 키를 만든 프로젝트로 불러야 해서 VERTEX_API_KEY_PROJECT(없으면 VERTEX_PROJECT)를 쓴다."""
    out: list[tuple[dict, str]] = []
    project = os.environ.get("VERTEX_PROJECT", "").strip()     # 붙여 넣을 때 딸려 온 줄바꿈이 주소를 깨뜨렸다(2026-10-19)
    raw = os.environ.get("GCP_SA_KEY", "")
    if raw or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        try:
            import google.auth
            from google.auth.transport.requests import Request
            from google.oauth2 import service_account
            scopes = ["https://www.googleapis.com/auth/cloud-platform"]
            if raw:
                info = json.loads(raw)
                cred = service_account.Credentials.from_service_account_info(info, scopes=scopes)
                tok_project = project or info.get("project_id", "")
            else:
                cred, adc_project = google.auth.default(scopes=scopes)
                tok_project = project or adc_project or ""
            cred.refresh(Request())
            out.append(({"Authorization": f"Bearer {cred.token}"}, tok_project))
        except Exception as e:                  # noqa: BLE001 — 토큰이 안 되면 API 키로
            print(f"  Veo(Vertex) 토큰 실패: {type(e).__name__}: {e}")
    # API 키(에이전트 플랫폼 전용으로 제한된 키 포함). 프로젝트를 안 주면 키만으로 부르는
    # 익스프레스 경로(global, 프로젝트 없음)를 쓴다. GEMINI_API_KEY 도 같은 식으로 한 번 시도한다.
    seen = set()
    for k in (os.environ.get("VERTEX_API_KEY", "").strip(), os.environ.get("GEMINI_API_KEY", "").strip()):
        if k and k not in seen:
            seen.add(k)
            out.append(({"x-goog-api-key": k}, os.environ.get("VERTEX_API_KEY_PROJECT", "").strip() or project))
    return out


def _vertex(scene: str, out: Path, seconds: int, c, image: dict | None = None) -> Path | None:
    for h, project in _vertex_auths():
        tries = [project]
        if "x-goog-api-key" in h and project:
            tries.append("")                    # 키는 프로젝트 경로가 막히면 익스프레스 경로로 한 번 더
        for p in tries:
            try:
                got = _vertex_call(h, p, scene, out, seconds, c, image)
            except Exception as e:              # noqa: BLE001 — 한 경로가 깨져도 다음 경로를 시도한다
                print(f"  Veo(Vertex) 실패: {type(e).__name__}: {e}")
                got = None
            if got:
                return got
    return None


def _vertex_call(h: dict, project: str, scene: str, out: Path, seconds: int, c,
                 image: dict | None = None) -> Path | None:
    loc = os.environ.get("VERTEX_LOCATION") or "us-central1"
    if project:
        base = f"https://{loc}-aiplatform.googleapis.com/v1/projects/{project}/locations/{loc}/publishers/google/models/"
    elif "x-goog-api-key" in h:
        base = "https://aiplatform.googleapis.com/v1/publishers/google/models/"   # 익스프레스(키만)
    else:
        print("  Veo(Vertex) 프로젝트 없음 — VERTEX_PROJECT 를 넣어야 한다")
        return None
    h = {**h, "Content-Type": "application/json"}
    inst = {"prompt": scene, "image": image} if image else {"prompt": full_prompt(scene)}
    body = {"instances": [inst],
            "parameters": {"aspectRatio": "9:16", "durationSeconds": seconds, "sampleCount": 1,
                           "generateAudio": False}}
    models = [os.environ["VEO_VERTEX_MODEL"]] if os.environ.get("VEO_VERTEX_MODEL") else list(VERTEX_MODELS)
    name = model = ""
    for model in models:
        r = c.post(f"{base}{model}:predictLongRunning", headers=h, json=body)
        if r.status_code == 404:
            print(f"  Veo(Vertex) 모델 없음: {model}")
            continue
        if r.status_code != 200:
            via = "키" if "x-goog-api-key" in h else "토큰"
            print(f"  Veo(Vertex·{via}) 요청 실패 {r.status_code}: {r.text[:300]}")
            return None
        name = r.json().get("name", "")
        break
    if not name:
        return None
    deadline = time.time() + TIMEOUT
    op: dict = {}
    while time.time() < deadline:
        op = c.post(f"{base}{model}:fetchPredictOperation", headers=h, json={"operationName": name}).json()
        if op.get("done"):
            break
        time.sleep(POLL_EVERY)
    if not op.get("done"):
        print("  Veo(Vertex) 시간 초과")
        return None
    if op.get("error"):
        print(f"  Veo(Vertex) 오류: {str(op['error'])[:300]}")
        return None
    videos = (op.get("response") or {}).get("videos") or []
    b64 = (videos[0] if videos else {}).get("bytesBase64Encoded")
    if not b64:
        print(f"  Veo(Vertex) 결과 없음(안전 필터일 수 있음): {str(op.get('response'))[:300]}")
        return None
    data = base64.b64decode(b64)
    if len(data) < 10_000:
        print(f"  Veo(Vertex) 영상이 너무 작음 {len(data)}B")
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    via = "키" if "x-goog-api-key" in h else "토큰"
    print(f"  Veo 훅 장면 {seconds}s (Vertex·{via} {model}) → {out.name}")
    return out


def _gemini(scene: str, out: Path, seconds: int, c) -> Path | None:
    key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("VEO_MODEL") or DEFAULT_MODEL
    h = {"x-goog-api-key": key, "Content-Type": "application/json"}
    r = c.post(f"{API}models/{model}:predictLongRunning", headers=h,
               json={"instances": [{"prompt": full_prompt(scene)}],
                     "parameters": {"aspectRatio": "9:16", "durationSeconds": seconds}})
    if r.status_code != 200:
        print(f"  Veo 요청 실패 {r.status_code}: {r.text[:200]}")
        return None
    name = r.json().get("name")
    deadline = time.time() + TIMEOUT
    op: dict = {}
    while name and time.time() < deadline:
        op = c.get(f"{API}{name}", headers=h).json()
        if op.get("done"):
            break
        time.sleep(POLL_EVERY)
    if not op.get("done"):
        print("  Veo 시간 초과")
        return None
    if op.get("error"):
        print(f"  Veo 오류: {str(op['error'])[:200]}")
        return None
    samples = ((op.get("response") or {}).get("generateVideoResponse") or {}).get("generatedSamples") or []
    uri = ((samples[0] if samples else {}).get("video") or {}).get("uri")
    if not uri:
        print(f"  Veo 결과 없음(안전 필터일 수 있음): {str(op.get('response'))[:200]}")
        return None
    v = c.get(uri, headers={"x-goog-api-key": key})
    if v.status_code != 200 or len(v.content) < 10_000:
        print(f"  Veo 영상 받기 실패 {v.status_code}")
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(v.content)
    print(f"  Veo 훅 장면 {seconds}s ({model}) → {out.name}")
    return out


# 공식 상품 사진 → 짧은 상품 컷(이미지→영상). 상품이 '작동'하거나 '쓰이는' 모습은 만들지 않는다 —
# AI 가 지어낸 시연은 허위 광고가 된다. 카메라만 움직이고 상품은 사진 그대로 둔다.
PRODUCT_PROMPT = ("Use the attached product photo as the exact reference. The product stays still and unchanged; "
                  "only the camera moves: a slow, smooth half orbit around the product at the same distance, so its full "
                  "outline and silhouette are easy to recognize. The entire product stays fully inside the frame from the "
                  "first to the last frame, centered, never cropped; no zoom-in, no close-up. Soft studio key light and a "
                  "subtle rim light on a clean seamless background, premium commercial look, vertical 9:16 framing. "
                  "Keep the product's shape, colors, parts, proportions and any printed text exactly as in the photo. "
                  "Do not open, use, operate or animate the product. No hands, no people, no extra products, "
                  "no added text or logos, no cuts.")


def _pad_vertical(src: Path) -> bytes:
    """정사각 상품 사진을 9:16 캔버스 가운데에 놓는다(흰 바탕) — Veo 가 위아래를 지어내지 않게.
    워커에는 PIL 이 없어서 ffmpeg 로 한다(렌더에 이미 쓴다)."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "pad.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf",
                        "pad=w='max(iw,ceil(ih*9/16/2)*2)':h='ceil(max(iw,ih*9/16)*16/9/2)*2'"
                        ":x='(ow-iw)/2':y='(oh-ih)/2':color=white", "-q:v", "2", str(out)],
                       check=True, capture_output=True)
        return out.read_bytes()


def product_clip(photo: Path, out: Path, seconds: int = 6, client: httpx.Client | None = None) -> Path | None:
    """상품 사진으로 카메라만 움직이는 상품 컷을 만든다. Vertex 만 지원. 어떤 실패든 None."""
    if os.environ.get("VEO_OFF") == "1" or not _vertex_on() or not Path(photo).exists():
        return None
    c = client or httpx.Client(timeout=120, follow_redirects=True)
    try:
        img = {"bytesBase64Encoded": base64.b64encode(_pad_vertical(Path(photo))).decode(), "mimeType": "image/jpeg"}
        return _vertex(PRODUCT_PROMPT, out, seconds, c, image=img)
    except Exception as e:                      # noqa: BLE001
        print(f"  Veo 상품 컷 실패: {type(e).__name__}: {e}")
        return None
