import sys
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parents[1] / "worker" / "youtube_shorts"

# API 이미지에는 worker/ 가 없다(.dockerignore) — deploy.sh 게이트에서는 건너뛴다.
if not WORKER.is_dir():
    pytest.skip("worker/ 없음 (API 컨테이너)", allow_module_level=True)

sys.path.insert(0, str(WORKER))


def test_짧은_자막_큐는_최소_시간을_보장한다():
    from make_explainer_short import MIN_CUE, _ensure_min_cue
    out = _ensure_min_cue([3.0, 0.59])
    assert all(d >= MIN_CUE for d in out)
    assert abs(sum(out) - 3.59) < 1e-9
