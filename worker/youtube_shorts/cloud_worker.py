"""쇼츠 클라우드 워커 — GitHub Actions 에서 돈다(.github/workflows/shorts-render.yml).

PC 워커(shorts_worker.py)는 Z: 드라이브로 NAS 큐 폴더를 직접 읽었다. 클라우드는 집 안 NAS 에 못
들어오므로 같은 일을 공개 주소의 토큰 API(api/routers/worker.py)로 한다:

    claim  → 대본 JSON 받기(NAS 에서 queue/X.json → X.taking)
    produce → TTS·렌더·검사·유튜브 공개 업로드(make_explainer_short.produce, PC 와 같은 코드)
    result → 결과 JSON + 완성 mp4 를 NAS 로(done/·media/), 실패면 failed/

환경변수: WORKER_API(기본 https://track.dsportal.io/api/worker), WORKER_TOKEN, MAX_JOBS(기본 3),
          DRY_RUN=1 이면 업로드 없이 렌더·검사만 하고 작업을 큐에 되돌린다.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

import httpx

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

API = os.environ.get("WORKER_API", "https://track.dsportal.io/api/worker").rstrip("/")
TOKEN = os.environ.get("WORKER_TOKEN", "")
H = {"Authorization": f"Bearer {TOKEN}", "User-Agent": "dsportal-shorts-worker/1.0"}
MAX_JOBS = int(os.environ.get("MAX_JOBS", "3"))
DRY = os.environ.get("DRY_RUN") == "1"
DEADLINE = time.time() + 50 * 60          # 워크플로 한도(60분) 안에서 새 작업을 더 집지 않는다


def call(method: str, path: str, tries: int = 5, **kw) -> dict:
    """결과 보고가 실패하면 영상은 올라갔는데 NAS 가 모르는 상태가 된다 — 넉넉히 재시도한다."""
    last = None
    for i in range(tries):
        try:
            r = httpx.request(method, API + path, headers=H, timeout=300, **kw)
            if r.status_code < 500:
                r.raise_for_status()
                return r.json()
            last = RuntimeError(f"{r.status_code} {r.text[:200]}")
        except httpx.HTTPStatusError:
            raise
        except Exception as e:                 # noqa: BLE001
            last = e
        time.sleep(10 * (i + 1))
    raise RuntimeError(f"{path} 실패: {last}")


def report(name: str, kind: str, body: dict, video: str | None = None) -> None:
    data = {"kind": kind, "body": json.dumps(body, ensure_ascii=False)}
    if video:
        with open(video, "rb") as f:
            call("POST", f"/result/{name}", data=data, files={"video": (f"{name}.mp4", f, "video/mp4")})
    else:
        call("POST", f"/result/{name}", data=data)


def one() -> bool:
    c = call("POST", "/claim")
    if not c.get("job"):
        print("큐 비어 있음")
        return False
    name, post = c["name"], c["job"]
    print(f"== {name} 시작 — {post.get('title', '')[:40]} (남은 큐 {c.get('remaining', 0)})")
    from make_explainer_short import produce
    # 틱톡용 다시 렌더(2026-10-19): 유튜브에는 이미 올라가 있다 — 업로드 없이 렌더만 해 mp4 를 돌려준다.
    tiktok_only = bool(post.get("tiktok_only"))
    try:
        res = produce(post, upload=not DRY and not tiktok_only, privacy="public")
    except BaseException as e:                 # noqa: BLE001  (SystemExit 렌더 실패 포함)
        err = f"{type(e).__name__}: {e}"
        print(f"!! {name} 실패 — {err}")
        if DRY:
            call("POST", f"/release/{name}")
        else:
            report(name, "failed", {"error": err, "trace": traceback.format_exc()[-2000:]})
        return True
    if res["issues"]:
        print(f"!! {name} 검사 문제 — {res['issues'][:3]}")
        if DRY:
            call("POST", f"/release/{name}")
        else:
            report(name, "failed", {"error": "검사 문제: " + "; ".join(res["issues"][:5])})
        return True
    if DRY:
        print(f"== {name} 렌더·검사 통과(DRY_RUN) — 큐에 되돌림")
        call("POST", f"/release/{name}")
        return False
    if tiktok_only:
        if post.get("require_veo") and not res.get("synthetic"):
            # 움직이는 장면 없이 정지 카드만 나온 영상이 틱톡에서 지워졌다 — 옛 영상을 그대로 두게 실패로 알린다.
            print(f"!! {name} Veo 장면 없음 — 틱톡용 영상을 바꾸지 않는다")
            report(name, "failed", {"error": "Veo 장면 없음", "tiktok_only": True})
            return True
        report(name, "done", {**(post.get("keep") or {}), "tiktok_only": True,
                              **{k: res.get(k) for k in ("duration", "credit")}}, video=res["video"])
        print(f"== {name} 틱톡용 렌더 완료(유튜브 업로드 없음)")
        return True
    report(name, "done", {k: res.get(k) for k in ("video_id", "url", "privacy", "duration", "credit")},
           video=res["video"])
    print(f"== {name} 완료 — {res.get('url')}")
    return True


def main() -> None:
    if not TOKEN:
        raise SystemExit("WORKER_TOKEN 없음")
    n = 0
    while n < MAX_JOBS and time.time() < DEADLINE:
        if not one():
            break
        n += 1
    print(f"처리 {n}건")


if __name__ == "__main__":
    main()
