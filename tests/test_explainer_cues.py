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


def test_상품쇼츠_제목에_번호_해시태그를_쓰지_않는다():
    import make_explainer_short as mes
    post = {"code": 61, "short_name": "문풍지 테이프", "name": "문풍지 외풍차단 테이프 5m",
            "product_category": "생활용품/욕실"}
    script = {"hook": {"screen": {"headline": "찬바람 새는 창문"}, "say": "겨울마다 창문 틈 찬바람 걱정이라면."}}
    title, desc, _ = mes.product_meta(post, script, "https://x/link/", "")
    assert "#61" not in title and title.startswith("찬바람 새는 창문 | 문풍지 테이프 61번")
    tags = [w for w in desc.split() if w.startswith("#") and not w[1:].isdigit()]
    assert tags[:3] == ["#Shorts", "#생활용품", "#쿠팡추천"] and len(tags) == 3
    assert desc.splitlines()[1].startswith("문풍지 테이프")
