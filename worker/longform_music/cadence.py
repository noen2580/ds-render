"""정기 제작(주 2편) — 표준 라이브러리만 쓴다(워크플로 설정 단계에서 의존성 설치 전에 불린다).

한 주에 한 테마, 월요일에 홀수 번째·목요일에 짝수 번째 편을 만든다. 짝수 번째가 올라가면 run.py autocompile 이
앞 편과 묶어 6시간 모음을 붙인다. 테마별 마지막 번호는 state/state.json(Actions 캐시 longform-state-*)에 둔다.
캐시가 없으면 SEED(2026-10-15 기준으로 이미 올린 번호)에서 시작한다.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SCHEDULE = [("rain", "sleep-rain"), ("ocean", "sleep-ocean"), ("sleep", "sleep"),
            ("forest", "sleep-forest"), ("space", "sleep-space")]
SEED = {"sleep": 4, "rain": 2, "ocean": 2, "forest": 2, "space": 2}   # 2026-10-18 ds-render 로 옮길 때 기준(캐시가 새로 시작한다)


def state_file() -> Path:
    return Path(os.environ.get("LONGFORM_STATE", Path(__file__).parent / "state")) / "state.json"


def load_state() -> dict:
    f = state_file()
    return {**SEED, **(json.loads(f.read_text()) if f.exists() else {})}


def mark(job: str) -> dict | None:
    """올린 작업 번호를 남긴다(rain-003 → rain: 3). 모음(-6h-)·번호 없는 작업은 건너뛴다."""
    m = re.fullmatch(r"(.+)-(\d{3})", job)
    if not m or m[1].endswith("-6h"):
        return None
    st = load_state()
    st[m[1]] = max(int(st.get(m[1], 0)), int(m[2]))
    f = state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(st, indent=1, sort_keys=True) + "\n")
    return st


def next_job(state: dict, week: int, weekday: int) -> dict | None:
    """월(0)·목(3)이면 이번 주 테마의 다음 작업, 아니면 None."""
    if weekday not in (0, 3):
        return None
    prefix, category = SCHEDULE[week % len(SCHEDULE)]
    n = int(state.get(prefix, 0)) + 1
    if weekday == 0 and n % 2 == 0:             # 월요일은 홀수로 시작해야 목요일 편과 짝이 맞는다
        n += 1
    return {"job": f"{prefix}-{n:03d}", "category": category, "hours": 3, "max_cost": 9, "upload": True}
