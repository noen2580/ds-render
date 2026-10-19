"""틱톡용 다시 렌더(2026-10-19) — 유튜브 업로드 없이 렌더만, Veo 장면이 없으면 영상을 바꾸지 않는다."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "worker" / "youtube_shorts"))


def _run(monkeypatch, synthetic):
    import cloud_worker as cw
    calls, uploads = [], []
    job = {"id": 62, "code": 62, "kind": "product", "title": "가습기", "tiktok_only": True, "require_veo": True,
           "keep": {"video_id": "yt1", "url": "https://youtu.be/yt1", "privacy": "public"}}
    monkeypatch.setattr(cw, "call", lambda m, path, **kw: {"name": "prod_62", "job": job} if path == "/claim" else {})
    monkeypatch.setattr(cw, "report", lambda name, kind, body, video=None: calls.append((kind, body, video)))

    def produce(post, upload, privacy):
        uploads.append(upload)
        return {"issues": [], "video": "/tmp/pr_62.mp4", "duration": 30, "credit": "", "synthetic": synthetic}
    monkeypatch.setitem(sys.modules, "make_explainer_short", types.SimpleNamespace(produce=produce))
    assert cw.one() is True
    return calls, uploads


def test_renders_without_upload_and_keeps_youtube_info(monkeypatch):
    calls, uploads = _run(monkeypatch, synthetic=True)
    assert uploads == [False]
    kind, body, video = calls[0]
    assert kind == "done" and video == "/tmp/pr_62.mp4"
    assert body["tiktok_only"] and body["url"] == "https://youtu.be/yt1" and body["video_id"] == "yt1"


def test_no_veo_scene_is_reported_as_failed(monkeypatch):
    calls, _ = _run(monkeypatch, synthetic=False)
    assert calls == [("failed", {"error": "Veo 장면 없음", "tiktok_only": True}, None)]
