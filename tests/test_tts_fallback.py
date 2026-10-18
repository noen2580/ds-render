"""2026-10-13 edge-tts 403(상품 쇼츠 #48·#49) — 실패하면 Gemini TTS 로 대신 만든다."""
import base64
import shutil
import sys
import types
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parents[1] / "worker" / "youtube_shorts"

# API 이미지에는 worker/ 가 없다(.dockerignore) — deploy.sh 게이트에서는 건너뛴다.
if not WORKER.is_dir():
    pytest.skip("worker/ 없음 (API 컨테이너)", allow_module_level=True)
if not shutil.which("ffmpeg"):
    pytest.skip("ffmpeg 없음", allow_module_level=True)

sys.path.insert(0, str(WORKER))


class _Resp:
    def __init__(self, code, data=None):
        self.status_code, self._data, self.text = code, data, "err"

    def json(self):
        return self._data


def _fake_edge(monkeypatch, fail=True):
    mod = types.ModuleType("edge_tts")

    class Communicate:
        def __init__(self, *a, **k):
            pass

        async def save(self, path):
            if fail:
                raise RuntimeError("WSServerHandshakeError: 403")
            Path(path).write_bytes(b"ID3edge")

    mod.Communicate = Communicate
    monkeypatch.setitem(sys.modules, "edge_tts", mod)
    sys.modules.pop("tts_edge", None)
    import tts_edge
    return tts_edge


def test_edge_403_falls_back_to_gemini(monkeypatch, tmp_path):
    tts_edge = _fake_edge(monkeypatch)
    import tts_gemini
    monkeypatch.setattr(tts_gemini, "_ok", None)
    monkeypatch.setattr(tts_gemini, "_vertex_auths", lambda: [])
    pcm = base64.b64encode(b"\x00\x00" * 2400).decode()
    calls = []

    def post(url, params=None, json=None, timeout=None, **k):
        calls.append(url)
        if "flash" in url:
            return _Resp(404)
        return _Resp(200, {"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "audio/L16;codec=pcm;rate=24000", "data": pcm}}]}}]})

    monkeypatch.setattr(tts_gemini.httpx, "post", post)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    out = tmp_path / "say_0.mp3"
    tts_edge.synthesize("안녕하세요", out)
    assert out.stat().st_size > 0 and len(calls) == 2 and "pro" in calls[1]


def test_edge_ok_does_not_call_gemini(monkeypatch, tmp_path):
    tts_edge = _fake_edge(monkeypatch, fail=False)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    import tts_gemini
    monkeypatch.setattr(tts_gemini.httpx, "post", lambda *a, **k: pytest.fail("Gemini 를 부르면 안 된다"))
    out = tmp_path / "a.mp3"
    tts_edge.synthesize("x", out)
    assert out.read_bytes() == b"ID3edge"


def test_no_key_reraises_edge_error(monkeypatch, tmp_path):
    tts_edge = _fake_edge(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="403"):
        tts_edge.synthesize("x", tmp_path / "a.mp3")


def test_gemini_key_blocked_falls_back_to_vertex_then_remembers(monkeypatch, tmp_path):
    """2026-10-13 14:50: GEMINI_API_KEY 가 Generative Language API 에 막혀 403 — Vertex 인증으로 넘어간다."""
    tts_edge = _fake_edge(monkeypatch)
    import tts_gemini
    import veo
    monkeypatch.setattr(tts_gemini, "_ok", None)
    monkeypatch.setattr(veo, "_vertex_on", lambda: True)
    monkeypatch.setattr(veo, "_vertex_auths", lambda: [({"Authorization": "Bearer t"}, "proj")])
    pcm = base64.b64encode(b"\x00\x00" * 2400).decode()
    calls = []

    def post(url, params=None, headers=None, json=None, timeout=None):
        calls.append(url)
        if "generativelanguage" in url:
            return _Resp(403)
        if "texttospeech" in url:
            return _Resp(200, {"audioContent": ""})
        return _Resp(200, {"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "audio/L16;codec=pcm;rate=24000", "data": pcm}}]}}]})

    monkeypatch.setattr(tts_gemini.httpx, "post", post)
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    tts_edge.synthesize("안녕하세요", tmp_path / "a.mp3")
    assert "aiplatform" in calls[-1] and "/projects/proj/" in calls[-1]
    n = len(calls)
    tts_edge.synthesize("두 번째", tmp_path / "b.mp3")
    assert len(calls) == n + 1 and "aiplatform" in calls[-1]        # 통한 경로를 바로 쓴다


def test_cloud_tts_used_when_gemini_routes_fail(monkeypatch, tmp_path):
    import subprocess
    import tts_gemini
    import veo
    monkeypatch.setattr(tts_gemini, "_ok", None)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(veo, "_vertex_on", lambda: True)
    monkeypatch.setattr(veo, "_vertex_auths", lambda: [({"x-goog-api-key": "v"}, "")])
    mp3 = tmp_path / "src.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.2",
                    str(mp3)], check=True)
    seen = {}

    def post(url, params=None, headers=None, json=None, timeout=None):
        if "texttospeech" in url:
            seen["text"] = json["input"]["text"]
            return _Resp(200, {"audioContent": base64.b64encode(mp3.read_bytes()).decode()})
        return _Resp(404)

    monkeypatch.setattr(tts_gemini.httpx, "post", post)
    out = tmp_path / "c.mp3"
    tts_gemini.synthesize('따옴표 "있는" 문장', out)
    assert out.stat().st_size > 0 and seen["text"] == '따옴표 "있는" 문장'


def test_aq_vertex_key_skips_gemini_api(monkeypatch):
    """AQ. 키(Vertex 전용)는 generativelanguage 로 부르지 않는다 — 늘 403 이다."""
    import tts_gemini
    import veo
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.xxx")
    monkeypatch.setattr(veo, "_vertex_on", lambda: True)
    monkeypatch.setattr(veo, "_vertex_auths", lambda: [({"x-goog-api-key": "AQ.xxx"}, "")])
    names = [r[0] for r in tts_gemini._routes("Kore")]
    assert names and not any(n.startswith("gemini-api") for n in names)
    assert names[0].startswith("vertex(키)/")
