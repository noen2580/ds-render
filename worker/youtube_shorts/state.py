"""숏폼 업로드 상태 로컬 JSON 파일 관리 — 같은 글을 중복 처리하지 않기 위함."""
import json
from pathlib import Path

STATE_PATH = Path(__file__).parent / "state" / "published.json"


def load() -> dict:
    if not STATE_PATH.exists():
        return {}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def get(post_id: int) -> dict | None:
    return load().get(str(post_id))


def record(post_id: int, entry: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = load()
    data[str(post_id)] = entry
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
