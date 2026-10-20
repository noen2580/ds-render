"""Veo 혼잡 재시도(2026-10-20) — Vertex 가 "high load"(code 8)로 거절하면 잠시 뒤 다시 한다(#78)."""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "worker" / "youtube_shorts"))


class _R:
    def __init__(self, status, data):
        self.status_code, self._d, self.text = status, data, str(data)

    def json(self):
        return self._d


class _Client:
    def __init__(self, errors):
        self.errors, self.submits = list(errors), 0

    def post(self, url, headers=None, json=None):
        if url.endswith(":predictLongRunning"):
            self.submits += 1
            return _R(200, {"name": f"op{self.submits}"})
        err = self.errors.pop(0) if self.errors else None
        if err:
            return _R(200, {"done": True, "error": err})
        return _R(200, {"done": True, "response": {"videos": [{"bytesBase64Encoded":
                                                               base64.b64encode(b"x" * 20_000).decode()}]}})


def _call(monkeypatch, tmp_path, errors):
    import veo
    monkeypatch.setattr(veo.time, "sleep", lambda s: None)
    monkeypatch.delenv("VEO_VERTEX_MODEL", raising=False)
    c = _Client(errors)
    got = veo._vertex_call({"x-goog-api-key": "k"}, "proj", "scene", tmp_path / "hook.mp4", 6, c)
    return got, c.submits


def test_혼잡이면_다시_해서_성공한다(monkeypatch, tmp_path):
    got, n = _call(monkeypatch, tmp_path, [{"code": 8, "message": "high load"}])
    assert got == tmp_path / "hook.mp4" and n == 2


def test_혼잡이_계속되면_정해진_횟수만_하고_포기한다(monkeypatch, tmp_path):
    import veo
    got, n = _call(monkeypatch, tmp_path, [{"code": 8}] * 5)
    assert got is None and n == veo.BUSY_RETRIES + 1


def test_다른_오류는_다시_하지_않는다(monkeypatch, tmp_path):
    got, n = _call(monkeypatch, tmp_path, [{"code": 3, "message": "invalid"}])
    assert got is None and n == 1
