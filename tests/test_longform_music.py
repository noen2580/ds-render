"""3시간 음악 영상 파이프라인 — Lyria·유튜브를 부르지 않고 기획·검사·조립·렌더·업로드 본문을 확인한다.
ffmpeg 로 만든 사인파를 곡 대신 쓰고, 목표 길이를 몇 분으로 줄여 끝까지 돌린다."""
import base64
import importlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "worker"
LM = ROOT / "longform_music"


@pytest.fixture
def mods(monkeypatch, tmp_path):
    if not LM.is_dir():                                                      # API 컨테이너에는 worker/ 가 없다
        pytest.skip("worker/ 없음 (API 컨테이너)")
    pytest.importorskip("numpy")
    pytest.importorskip("httpx")
    for p in (str(LM), str(ROOT / "youtube_shorts")):
        if p not in sys.path:
            sys.path.insert(0, p)
    monkeypatch.setenv("LONGFORM_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("LONGFORM_IMAGEN", "0")                               # 이미지 생성은 따로 시험
    monkeypatch.setenv("LONGFORM_LOCALIZE", "0")                             # 번역도 따로 시험
    import audio, imagen, lyria, presets, run, upload, video
    return SimpleNamespace(audio=audio, imagen=imagen, lyria=lyria, presets=presets, run=run, upload=upload,
                           video=video)


def need_ffmpeg():
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg 없음")


def tone(path: Path, sec: float, freq=220, gap=None, loud_at=None):
    """사인파 곡. gap=(시작,길이) 무음, loud_at=초 — 그 뒤 6초를 크게."""
    expr = f"0.1*sin(2*PI*{freq}*t)"
    if gap:
        expr = f"if(between(t,{gap[0]},{gap[0] + gap[1]}),0,{expr})"
    if loud_at is not None:
        expr = f"if(between(t,{loud_at},{loud_at + 6}),0.9*sin(2*PI*{freq}*t),{expr})"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={sec}",
                    "-ac", "2", str(path)], check=True)
    return path


def test_plan_varies_and_is_stable(mods):
    a = mods.presets.plan_tracks("sleep", 70, seed=3)
    assert len(a) == 70 and len({t["id"] for t in a}) == 70
    assert a == mods.presets.plan_tracks("sleep", 70, seed=3)                 # 다시 돌려도 같은 기획
    assert len({t["prompt"] for t in a}) > 40                                 # 곡마다 다르다
    for x, y in zip(a, a[1:]):
        lx, tx = x["name"].split(" & ")
        ly, ty = y["name"].split(" & ")
        assert lx != ly or tx != ty
    assert all("no vocals" in t["prompt"] and "no drums" in t["prompt"].lower() for t in a)


def test_lyrics_detection(mods):
    assert not mods.lyria.lyrics_in("[[Intro]] [0.0:] [[Verse]] [32.5:] [[Outro]] [150.0:]")
    assert not mods.lyria.lyrics_in("")
    assert mods.lyria.lyrics_in("[[Verse]] [0.0:] Close your eyes and drift away tonight, "
                                "the stars are falling softly on your pillow")


class _R:
    def __init__(self, code, js=None):
        self.status_code, self._js, self.text = code, js or {}, json.dumps(js or {})

    def json(self):
        return self._js


class _C:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, headers, json))
        return self.replies.pop(0)


def ok_reply(data=b"RIFFfake", mime="audio/wav", text="[[Intro]] [0.0:]"):
    return _R(200, {"candidates": [{"content": {"parts": [
        {"text": text}, {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}}]}}]})


def test_generate_request_retry_and_save(mods, tmp_path, monkeypatch):
    monkeypatch.setattr(mods.lyria.time, "sleep", lambda s: None)
    c = _C([_R(429), ok_reply(b"ID3mp3", "audio/mpeg")])
    got = mods.lyria.generate("calm", tmp_path / "t001", c, [({"x-goog-api-key": "k"}, "proj")])
    assert got["file"] == "t001.mp3" and (tmp_path / "t001.mp3").read_bytes() == b"ID3mp3"
    assert got["vocals"] is False
    url, h, body = c.calls[0]
    assert url == ("https://aiplatform.googleapis.com/v1/projects/proj/locations/global"
                   "/publishers/google/models/lyria-3-pro-preview:generateContent")
    assert body["generationConfig"]["responseModalities"] == ["AUDIO", "TEXT"]
    assert body["contents"][0]["parts"][0]["text"] == "calm"


def test_generate_falls_back_to_express_then_fails(mods, tmp_path):
    c = _C([_R(403), ok_reply()])
    got = mods.lyria.generate("p", tmp_path / "t002", c, [({"x-goog-api-key": "k"}, "proj")])
    assert got["file"] == "t002.wav"
    assert c.calls[1][0] == "https://aiplatform.googleapis.com/v1/publishers/google/models/lyria-3-pro-preview:generateContent"
    with pytest.raises(mods.lyria.LyriaError):
        mods.lyria.generate("p", tmp_path / "t003", _C([_R(200, {"candidates": [{"finishReason": "SAFETY"}]})]),
                            [({"Authorization": "Bearer x"}, "proj")])


def test_analyze_flags_silence_and_jumps(mods, tmp_path):
    need_ffmpeg()
    good = mods.audio.analyze(tone(tmp_path / "a.wav", 70))
    assert good["problems"] == [] and 69 < good["duration"] < 71
    assert any("무음" in p for p in mods.audio.analyze(tone(tmp_path / "b.wav", 70, gap=(30, 5)))["problems"])
    assert any("급변" in p for p in mods.audio.analyze(tone(tmp_path / "c.wav", 70, loud_at=30))["problems"])
    assert mods.audio.analyze(tone(tmp_path / "e.wav", 70, loud_at=5))["problems"] == []    # 도입부(페이드)는 안 본다
    assert any("짧음" in p for p in mods.audio.analyze(tone(tmp_path / "d.wav", 20))["problems"])


def test_sequence_repeats_without_back_to_back(mods):
    ts = [{"id": f"t{i}", "duration": 100.0} for i in range(3)]
    seq = mods.audio.sequence(ts, 500, 8)
    assert sum(t["duration"] for t in seq) - 8 * (len(seq) - 1) >= 500
    assert all(x["id"] != y["id"] for x, y in zip(seq, seq[1:]))


def test_chapters_and_private_body(mods):
    ch = mods.upload.chapters(["A", "B", "C", "D"], [0, 142.0, 3700.5, 3705])
    assert ch.splitlines() == ["00:00 A", "02:22 B", "1:01:40 C"]                # 10초 안쪽 챕터는 뺀다
    assert mods.upload.chapters(["A", "B"], [0, 100]) == ""                     # 3개 미만이면 없음
    title, _ = mods.presets.variant("sleep", "sleep-002")
    body = mods.upload.build_body(mods.presets.SLEEP, "desc", title)
    assert body["snippet"]["title"] == title and not any("{" in t for t in body["snippet"]["tags"])
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["containsSyntheticMedia"] is True
    assert body["status"]["selfDeclaredMadeForKids"] is False
    assert body["snippet"]["categoryId"] == "10"
    with pytest.raises(AssertionError):
        mods.upload.upload_private(Path("x.mp4"), {**body, "status": {"privacyStatus": "public"}})


def test_title_variants(mods):
    vs = mods.presets.SLEEP["variants"]
    assert all(len(t) <= 100 and not t[:2].isdigit() for t, _ in vs)          # 제목 앞에 "N Hours" 를 두지 않는다
    assert all(len(words) <= 1 and all(len(w.split()) <= 3 for w in words) for _, words in vs)
    assert mods.presets.variant("sleep", "a") == mods.presets.variant("sleep", "a")
    assert len({mods.presets.variant("sleep", f"j{i}")[0] for i in range(30)}) > 3
    assert len(",".join(mods.presets.SLEEP["tags"])) < 450                    # 유튜브 태그 합계 500자 제한


def test_end_to_end_short_job(mods, tmp_path, monkeypatch):
    need_ffmpeg()
    monkeypatch.setattr(mods.video, "LOOP_SEC", 3)
    calls = []

    def fake_generate(prompt, out_base, client, auths=None, retries=3):
        n = len(calls)
        calls.append(prompt)
        f = out_base.with_suffix(".wav")
        if n == 1:
            tone(f, 70, gap=(30, 5))                                            # 두 번째 곡은 검사에서 빠진다
        else:
            tone(f, 70, freq=200 + 20 * n)
        return {"file": f.name, "mime": "audio/wav", "text": "", "vocals": False}

    monkeypatch.setattr(mods.lyria, "generate", fake_generate)
    veo = importlib.import_module("veo")
    monkeypatch.setattr(veo, "_vertex_auths", lambda: [({"x-goog-api-key": "k"}, "")])
    args = ["--job", "t", "--hours", str(150 / 3600), "--tracks", "6", "--max-cost", "1", "--workers", "1"]
    m = mods.run.main(["all", *args])
    st = [t.get("status") for t in m["tracks"]]
    assert st[:4] == ["approved", "rejected", "approved", "approved"] and st[4] is None   # 길이 채우면 멈춘다
    assert m["spent_usd"] == pytest.approx(0.32)
    assert m["final"]["ok"], m["final"]
    assert m["final"]["video"] == "h264 1920x1080" and m["final"]["audio"] == "aac 48000Hz 2ch"
    d = tmp_path / "out" / "t"
    assert (d / "thumbnail.jpg").stat().st_size > 1000
    report = (d / "report.md").read_text(encoding="utf-8")
    assert "검사 통과" in report and "중간 무음" in report and "- [ ]" in report
    assert len(m["assembled"]["starts"]) == 3 and m["assembled"]["repeats"] == 0
    desc = mods.run.description(m)
    assert desc.count("\n00:00 ") == 1 and "Lyria" in desc

    # 사람이 한 곡을 빼면 모자란 만큼 새로 만들고 다시 조립한다
    m = mods.run.main(["review", "--job", "t", "--reject", "t003"])
    assert "assembled" not in m
    m = mods.run.main(["all", *args])
    assert m["tracks"][4]["status"] == "approved" and m["final"]["ok"]
    assert "t003" not in m["assembled"]["order"]


def _approved_job(mods, job, base_freq):
    mods.run.main(["plan", "--job", job, "--hours", str(100 / 3600), "--tracks", "2"])
    d = mods.run.job_dir(job)
    m = mods.run.load(d)
    for i, t in enumerate(m["tracks"]):
        tone(d / "tracks" / f"{t['id']}.wav", 70, freq=base_freq + 40 * i)
        t.update(file=f"{t['id']}.wav", vocals=False, text="", status="rejected", qc={"problems": [], "sha256": job + str(i)})
    mods.run.save(d, m)
    return mods.run.main(["generate", "--job", job, "--max-cost", "0"])        # 다시 검사 → 승인


def test_compile_longer_video_from_existing_tracks(mods, monkeypatch):
    """곡이 충분하면 이미 만든 작업들의 곡을 모아 더 긴 영상을 만든다 — Lyria 를 부르지 않는다."""
    need_ffmpeg()
    monkeypatch.setattr(mods.video, "LOOP_SEC", 3)
    monkeypatch.setattr(mods.lyria, "generate", lambda *a, **k: pytest.fail("모음 작업은 새 곡을 만들지 않는다"))
    veo = importlib.import_module("veo")
    monkeypatch.setattr(veo, "_vertex_auths", lambda: [])
    assert len(mods.run.approved(_approved_job(mods, "s-001", 300))) == 2
    assert len(mods.run.approved(_approved_job(mods, "s-002", 500))) == 2
    with pytest.raises(SystemExit, match="곡이 모자라다"):                   # 4곡 ≈ 256초로 300초는 못 채운다
        mods.run.main(["compile", "--job", "long-001", "--from", "s-001,s-002", "--hours", str(300 / 3600)])
    m = mods.run.main(["compile", "--job", "long-001", "--from", "s-001,s-002", "--hours", str(200 / 3600)])
    assert m["spent_usd"] == 0 and m["sources"] == ["s-001", "s-002"] and len(m["tracks"]) == 4
    assert {t["id"] for t in m["tracks"]} == {"at001", "at002", "bt001", "bt002"}
    m = mods.run.main(["all", "--job", "long-001", "--hours", "0"])
    assert m["final"]["ok"] and m["assembled"]["repeats"] == 0 and m["spent_usd"] == 0
    assert m["title"].endswith(" #1")                                        # 시리즈 번호
    with pytest.raises(SystemExit):
        mods.run.main(["compile", "--job", "x", "--from", "s-001", "--hours", "0"])   # 1시간도 못 채움


def test_autocompile_pairs_theme_jobs(mods, monkeypatch):
    """테마 영상이 2편 모이면(짝수 번째) 두 작업을 6시간 모음으로 — 홀수·모음 작업·앞 작업 없음은 건너뛴다."""
    assert mods.run.pair_job("rain-002") == ("rain-001", "rain-6h-001")
    assert mods.run.pair_job("ocean-004") == ("ocean-003", "ocean-6h-002")
    assert mods.run.pair_job("rain-001") is None and mods.run.pair_job("rain-6h-002") is None
    assert mods.run.pair_job("pilot") is None
    calls = []
    monkeypatch.setattr(mods.run, "cmd_compile", lambda b: calls.append(("compile", b.job, b.sources, b.hours, b.category)))
    monkeypatch.setattr(mods.run, "cmd_all", lambda b: calls.append(("all", b.job, b.upload)) or {"job": b.job})
    for job, extra in (("r-001", {}), ("r-002", {}), ("c-001", {}), ("c-002", {"sources": ["x"]})):
        d = mods.run.job_dir(job)
        mods.run.save(d, {"job": job, "category": "sleep-rain", "target_sec": 10800, "tracks": [], **extra})
    assert mods.run.main(["autocompile", "--job", "r-001", "--upload"]) is None             # 홀수 번째
    assert mods.run.main(["autocompile", "--job", "c-002", "--upload"]) is None             # 모음 작업
    assert mods.run.main(["autocompile", "--job", "z-002", "--upload"]) is None             # 기록 없음
    assert not calls
    assert mods.run.main(["autocompile", "--job", "r-002", "--upload"]) == {"job": "r-6h-001"}
    assert calls == [("compile", "r-6h-001", "r-001,r-002", 0.0, "sleep-rain"), ("all", "r-6h-001", True)]


def test_description_and_tags_follow_length(mods):
    m = {"category": "sleep", "target_sec": 12 * 3600, "tracks": [], "assembled": {"order": [], "starts": []}}
    desc = mods.run.description(m)
    assert desc.startswith("Twelve hours of calm") and "#sleepmusic" in desc and 1000 < len(desc) < 5000
    assert "not a medical treatment" in desc
    assert "12 hours sleep music" in mods.presets.tags("sleep", 12 * 3600)
    assert mods.presets.title("sleep", "sleep-002").endswith(" #2") and len(mods.presets.title("sleep", "sleep-002")) <= 100


def test_themes_differ_and_fit_youtube_limits(mods):
    P = mods.presets
    assert {"sleep-rain", "sleep-ocean", "sleep-forest", "sleep-space"} <= set(P.CATEGORIES)
    titles = set()
    for k, c in P.CATEGORIES.items():
        for i in range(1, 6):
            t = P.title(k, f"x-{i:03d}")
            assert len(t) <= 100 and "{" not in t
            titles.add(t)
        assert len(",".join(P.tags(k, 3 * 3600))) < 450
        assert c["playlist"][0] and P.background_prompt(k, "x") != P.background_prompt("sleep", "x") or k == "sleep"
        desc = mods.run.description({"category": k, "target_sec": 3 * 3600, "tracks": [],
                                     "assembled": {"order": [], "starts": []}})
        assert c["sound"] in desc and "{" not in desc
        assert all(t["prompt"].count("no vocals") == 1 for t in P.plan_tracks(k, 10, 1))
    assert len(titles) >= 10


def test_playlist_reuses_existing_or_creates_private(mods, monkeypatch):
    calls = []

    class Q:
        def __init__(self, name, ret):
            self.name, self.ret = name, ret

        def __getattr__(self, method):
            def f(**kw):
                calls.append((self.name, method, kw))
                return SimpleNamespace(execute=lambda: self.ret(method, kw))
            return f

    existing = []
    yt = SimpleNamespace(
        playlists=lambda: Q("playlists", lambda m, kw: {"items": existing} if m == "list" else {"id": "PLnew"}),
        playlistItems=lambda: Q("items", lambda m, kw: {"id": "i"}))
    import googleapiclient.discovery
    monkeypatch.setattr(googleapiclient.discovery, "build", lambda *a, **k: yt)
    yu = importlib.import_module("youtube_upload")
    monkeypatch.setattr(yu, "_load_credentials", lambda: None)
    got = mods.upload.add_to_playlist("vid1", "Rain Sleep Music", "d")
    assert got["created"] and got["id"] == "PLnew"
    ins = [c for c in calls if c[:2] == ("playlists", "insert")][0][2]["body"]
    assert ins["status"]["privacyStatus"] == "private"
    existing.append({"id": "PLold", "snippet": {"title": "Rain Sleep Music"}})
    calls.clear()
    got = mods.upload.add_to_playlist("vid2", "Rain Sleep Music")
    assert not got["created"] and got["id"] == "PLold"
    assert not any(c[:2] == ("playlists", "insert") for c in calls)
    item = [c for c in calls if c[0] == "items"][0][2]["body"]["snippet"]
    assert item["playlistId"] == "PLold" and item["resourceId"]["videoId"] == "vid2"

    # 막 만든 재생목록은 잠깐 409 SERVICE_UNAVAILABLE — 다시 시도한다
    from googleapiclient.errors import HttpError
    fails = [HttpError(SimpleNamespace(status=409, reason="aborted"), b"{}")]

    def flaky(m, kw):
        if fails:
            raise fails.pop()
        return {"id": "i"}
    yt.playlistItems = lambda: Q("items", flaky)
    monkeypatch.setattr(mods.upload, "RETRY_SEC", 0)
    assert mods.upload.add_to_playlist("vid3", "Rain Sleep Music")["id"] == "PLold" and not fails


def test_assemble_in_chunks_matches_single_pass(mods, tmp_path, monkeypatch):
    """곡이 많으면 묶음으로 나눠 잇는다(러너 메모리). 길이·이음 시각은 한 번에 이을 때와 같다."""
    need_ffmpeg()
    files = [tone(tmp_path / f"{i}.wav", 20 + i, freq=200 + 30 * i) for i in range(7)]
    target = sum(20 + i for i in range(7)) - 8 * 6 - 5
    one = mods.audio.assemble(files, tmp_path / "one.m4a", target)
    monkeypatch.setattr(mods.audio, "CHUNK", 3)
    many = mods.audio.assemble(files, tmp_path / "many.m4a", target)
    assert one == many and len(many) == 7
    assert abs(mods.audio.ffprobe_duration(tmp_path / "many.m4a") - target) < 0.2
    assert not list(tmp_path.glob("*.part*"))


def test_cost_cap_stops(mods, monkeypatch):
    need_ffmpeg()
    monkeypatch.setattr(mods.lyria, "generate", lambda *a, **k: pytest.fail("한도 넘으면 부르면 안 된다"))
    veo = importlib.import_module("veo")
    monkeypatch.setattr(veo, "_vertex_auths", lambda: [])
    mods.run.main(["plan", "--job", "c", "--hours", "1"])
    m = mods.run.main(["generate", "--job", "c", "--max-cost", "0.05"])
    assert m["spent_usd"] == 0 and not any(t.get("status") for t in m["tracks"])


def test_vocals_flag_is_a_note_and_old_checks_are_redone(mods, monkeypatch):
    """2026-10-10 시험: Lyria 는 기악곡에도 설명 텍스트를 줘서 6곡이 전부 '가사'로 탈락했다.
    가사 의심은 표시만 하고, 검사 기준이 바뀌면 이미 만든 곡을 재생성 없이 다시 검사한다."""
    need_ffmpeg()
    monkeypatch.setattr(mods.lyria, "generate", lambda *a, **k: pytest.fail("이미 만든 곡은 다시 만들지 않는다"))
    veo = importlib.import_module("veo")
    monkeypatch.setattr(veo, "_vertex_auths", lambda: [])
    mods.run.main(["plan", "--job", "v", "--hours", str(100 / 3600), "--tracks", "2"])
    d = mods.run.job_dir("v")
    m = mods.run.load(d)
    for i, t in enumerate(m["tracks"]):
        tone(d / "tracks" / f"{t['id']}.wav", 70, freq=300 + 40 * i)
        t.update(file=f"{t['id']}.wav", vocals=True, text="A calm piece with soft pads", status="rejected",
                 qc={"problems": ["가사(보컬) 있음"], "sha256": str(i)})       # 옛 검사 결과(version 없음)
    mods.run.save(d, m)
    m = mods.run.main(["generate", "--job", "v", "--max-cost", "0"])
    assert [t["status"] for t in m["tracks"]] == ["approved", "approved"]
    assert m["tracks"][0]["qc"]["notes"] == ["가사 의심(들어서 확인)"]
    assert "가사 의심" in (d / "report.md").read_text(encoding="utf-8")
    assert "A calm piece" in (d / "report.md").read_text(encoding="utf-8")


def test_imagen_request_and_fallback(mods, tmp_path):
    png = base64.b64encode(b"\x89PNGfake").decode()
    c = _C([_R(404), _R(200, {"predictions": [{"bytesBase64Encoded": png, "mimeType": "image/png"}]})])
    got = mods.imagen.generate("moon", tmp_path / "bg.png", c, [({"Authorization": "Bearer t"}, "proj")])
    assert (tmp_path / "bg.png").read_bytes() == b"\x89PNGfake" and got["model"] == mods.imagen.MODELS[1]
    url, h, body = c.calls[0]
    assert url.endswith("/projects/proj/locations/us-central1/publishers/google/models/imagen-4.0-generate-001:predict")
    assert body["parameters"]["aspectRatio"] == "16:9" and body["instances"][0]["prompt"] == "moon"
    with pytest.raises(mods.imagen.ImagenError):
        mods.imagen.generate("moon", tmp_path / "x.png", _C([_R(200, {"predictions": []})] * 2 + [_R(200, {"candidates": []})]),
                             [({"Authorization": "Bearer t"}, "proj")])
    gem = {"candidates": [{"content": {"parts": [{"text": "ok"}, {"inlineData": {"mimeType": "image/png", "data": png}}]}}]}
    c = _C([_R(403), _R(404), _R(403), _R(404), _R(200, gem)])
    got = mods.imagen.generate("moon", tmp_path / "g.png", c, [({"x-goog-api-key": "k"}, "proj")])
    assert got["model"] == "gemini-2.5-flash-image" and (tmp_path / "g.png").read_bytes() == b"\x89PNGfake"
    assert c.calls[-1][0].endswith("/projects/proj/locations/global/publishers/google/models/"
                                   "gemini-2.5-flash-image:generateContent")
    assert c.calls[-1][2]["generationConfig"]["responseModalities"] == ["IMAGE"]
    p1, p2 = (mods.presets.background_prompt("sleep", j) for j in ("sleep-001", "sleep-002"))
    assert p1 == mods.presets.background_prompt("sleep", "sleep-001") and "no text" in p1


def test_render_uses_generated_background(mods, tmp_path, monkeypatch):
    need_ffmpeg()
    monkeypatch.setattr(mods.video, "LOOP_SEC", 2)
    monkeypatch.setenv("LONGFORM_IMAGEN", "1")
    veo = importlib.import_module("veo")
    monkeypatch.setattr(veo, "_vertex_auths", lambda: [({"x-goog-api-key": "k"}, "")])

    def fake_image(prompt, out, client, auths):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1408x768", "-frames:v", "1",
                        str(out)], check=True)
        return {"file": out.name, "model": "imagen-test", "prompt": prompt}

    monkeypatch.setattr(mods.imagen, "generate", fake_image)
    mods.run.main(["plan", "--job", "b", "--hours", str(70 / 3600), "--tracks", "1"])
    d = mods.run.job_dir("b")
    m = mods.run.load(d)
    tone(d / "tracks" / "t001.wav", 80)
    m["tracks"][0].update(file="t001.wav", status="approved", duration=80.0,
                          qc={"duration": 80.0, "version": mods.audio.QC_VERSION})
    mods.run.save(d, m)
    mods.run.main(["assemble", "--job", "b"])
    m = mods.run.main(["render", "--job", "b"])
    assert m["final"]["ok"], m["final"]
    assert m["background"].startswith("Imagen(imagen-test)") and m["image"]["usd"] == mods.imagen.PRICE_USD
    assert (d / "background.png").exists() and (d / "thumbnail.jpg").stat().st_size > 1000
    assert "Background image generated with Google AI (imagen-test)" in mods.run.description(m)
    assert "Imagen" in (d / "report.md").read_text(encoding="utf-8")
    monkeypatch.setattr(mods.imagen, "generate", lambda *a, **k: pytest.fail("이미 만든 배경은 다시 만들지 않는다"))
    (d / "loop.mp4").unlink()
    assert mods.run.main(["render", "--job", "b"])["final"]["ok"]

    # 배경 다시 만들기: 이미지가 안 되면 같은 화면으로 다시 올리지 않고 멈춘다. 되면 새 이미지로 렌더
    m = mods.run.load(d)
    m["upload"] = {"url": "https://youtu.be/old", "studio": "s"}
    mods.run.save(d, m)
    mods.run.main(["visuals", "--job", "b"])
    monkeypatch.setattr(mods.imagen, "generate", lambda *a, **k: (_ for _ in ()).throw(mods.imagen.ImagenError("403")))
    with pytest.raises(SystemExit):
        mods.run.main(["render", "--job", "b"])
    monkeypatch.setattr(mods.imagen, "generate", fake_image)
    m = mods.run.main(["render", "--job", "b"])
    assert m["final"]["ok"] and "upload" not in m and m["previous_uploads"][0]["url"] == "https://youtu.be/old"
    assert "need_image" not in m and "youtu.be/old" in (d / "report.md").read_text(encoding="utf-8")


def test_refused_lead_is_skipped_and_failures_dont_stop_early(mods, monkeypatch):
    """2026-10-10 sleep-001: Warm Pads·Harp 곡이 매번 finishReason=OTHER 로 거절돼 실패 10곡에서 멈췄다.
    계속 거절되는 악기는 건너뛰고, 실패가 섞여도 성공이 이어지면 끝까지 만든다."""
    need_ffmpeg()
    veo = importlib.import_module("veo")
    monkeypatch.setattr(veo, "_vertex_auths", lambda: [({"x-goog-api-key": "k"}, "")])
    calls = []

    def fake_generate(prompt, out_base, client, auths=None, retries=3):
        calls.append(prompt)
        if "harp" in prompt or len(calls) % 2 == 0:
            raise mods.lyria.LyriaError("오디오 없음 finishReason=OTHER")
        f = out_base.with_suffix(".wav")
        tone(f, 70, freq=150 + 7 * len(calls))
        return {"file": f.name, "mime": "audio/wav", "text": "", "vocals": False}

    monkeypatch.setattr(mods.lyria, "generate", fake_generate)
    mods.run.main(["plan", "--job", "f", "--hours", str(1500 / 3600)])
    m = mods.run.main(["generate", "--job", "f", "--max-cost", "5", "--workers", "1"])
    assert mods.run.covered(m) >= m["target_sec"]
    harp = [t for t in m["tracks"] if t["name"].startswith("Harp")]
    assert sum(t.get("status") == "failed" for t in harp) == mods.run.DEAD_LEAD
    assert any(t.get("status") == "skipped" for t in harp)
    assert sum(t.get("status") == "failed" for t in m["tracks"]) > 10


def test_localizations_and_audio_language(mods):
    """해외 노출: 번역 제목·설명을 localizations 로, 오디오 언어는 보내지 않는다('zxx' 는 API 가 거절)."""
    loc = importlib.import_module("localize")
    js = {"candidates": [{"content": {"parts": [{"text": '{"ko": {"title": "깊은 잠 음악 #2", "description": "설명"},'
                                                         ' "ja": {"title": "", "description": "x"}}'}]}}]}
    got = loc.parse(js, {"ko": "Korean", "ja": "Japanese"})
    assert got == {"ko": {"title": "깊은 잠 음악 #2", "description": "설명"}}           # 빈 번역은 뺀다
    with pytest.raises(loc.LocalizeError):
        loc.parse({"candidates": []}, {"ko": "Korean"})
    p = loc.prompt("Fall Asleep Fast #2", "1:00:00 Rain", loc.LANGS)
    assert "medical" in p and "timestamp" in p and "ko" in p
    preset = mods.presets.CATEGORIES["sleep-rain"]
    b = mods.upload.build_body(preset, "d", "t", ["x"], got)
    assert "defaultAudioLanguage" not in b["snippet"] and b["localizations"] == got
    assert "localizations" not in mods.upload.build_body(preset, "d", "t", ["x"])


def test_next_job_schedule(mods, tmp_path, monkeypatch):
    """정기 제작: 주마다 한 테마, 월요일 홀수·목요일 짝수(짝이 맞으면 6시간 모음). 번호는 state.json 에 남긴다."""
    sch = importlib.import_module("cadence")
    nj = sch.next_job
    assert nj({}, 0, 2) is None                                       # 수요일
    assert nj({"rain": 2}, 0, 0)["job"] == "rain-003"
    assert nj({"rain": 3}, 0, 3)["job"] == "rain-004"
    assert nj({"sleep": 3}, 2, 0)["job"] == "sleep-005"               # 짝수에서 시작하지 않게
    r = nj({}, 1, 0)
    assert r["job"] == "ocean-001" and r["category"] == "sleep-ocean" and r["upload"] and r["max_cost"] == 9
    monkeypatch.setenv("LONGFORM_STATE", str(tmp_path / "st"))
    assert sch.load_state()["rain"] == 2                              # 캐시 없으면 이미 올린 번호부터
    mods.run.main(["mark", "--job", "rain-003"])
    assert sch.mark("rain-6h-002") is None and sch.load_state()["rain"] == 3
    mods.run.main(["mark", "--job", "rain-001"])                      # 작은 번호로 되돌리지 않는다
    assert sch.load_state()["rain"] == 3 and nj(sch.load_state(), 0, 3)["job"] == "rain-004"


def test_localize_existing_keeps_privacy(mods):
    """기존 영상 번역 넣기: 번역 없는 영상만 고치고, status(공개 여부)는 보내지 않는다."""
    calls = []

    class Q:
        def __init__(self, name):
            self.name = name

        def __getattr__(self, method):
            def f(**kw):
                calls.append((self.name, method, kw))
                return SimpleNamespace(execute=lambda: R[(self.name, method)])
            return f
    R = {("channels", "list"): {"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU1"}}}]},
         ("playlistItems", "list"): {"items": [{"contentDetails": {"videoId": "a"}}, {"contentDetails": {"videoId": "b"}}]},
         ("videos", "list"): {"items": [
             {"id": "a", "snippet": {"title": "A", "description": "d", "categoryId": "10"}, "status": {"privacyStatus": "private"}},
             {"id": "b", "snippet": {"title": "B", "categoryId": "10", "defaultAudioLanguage": "zxx"},
              "status": {"privacyStatus": "public"},
              "localizations": {k: {"title": "비", "description": "x"} for k in ("ko", "ja", "es", "pt", "de")}}]},
         ("videos", "update"): {}}
    yt = SimpleNamespace(**{n: (lambda n=n: Q(n)) for n in ("channels", "playlistItems", "videos")})
    rows = mods.upload.localize_existing(lambda t, d: {"ko": {"title": t + "ko", "description": "dko"}}, False, yt)
    assert [r.get("updated") for r in rows] == [None, None] and not [c for c in calls if c[1] == "update"]
    R[("videos", "list")]["items"][0]["localizations"] = {"en": {"title": "A", "description": "d"}}   # 기본 언어만
    rows = mods.upload.localize_existing(lambda t, d: {"ko": {"title": t + "ko", "description": "dko"}}, True, yt)
    ups = [c for c in calls if c[1] == "update"]
    assert len(ups) == 1 and ups[0][2]["body"]["id"] == "a" and "status" not in ups[0][2]["body"]
    assert "defaultAudioLanguage" not in ups[0][2]["body"]["snippet"] and ups[0][2]["body"]["localizations"]["ko"]["title"] == "Ako"
    assert ups[0][2]["body"]["localizations"]["en"]["title"] == "A"                     # 기존 것은 남긴다
    assert rows[0]["updated"] and rows[1]["privacy"] == "public"


def test_localize_limits_and_fallback(mods):
    """유튜브 한도: 설명 5000'바이트'·'<>' 금지. 한 언어가 거절되면 언어별로 넣어 받아 주는 것만 남긴다(2026-10-15 400)."""
    loc = importlib.import_module("localize")
    hi = "\n".join(f"{i}:00:00 " + "नींद" * 40 for i in range(60))            # 힌디어 — 글자 수는 5000 미만, 바이트는 훨씬 큼
    d = loc.clean_description(hi + " <b>")
    assert len(d.encode()) <= 5000 and d.endswith("नींद") and "<" not in d    # 줄 단위로 잘린다
    assert loc.clean_title("<Sleep> " + "x" * 200) == ("Sleep " + "x" * 200)[:100]

    from googleapiclient.errors import HttpError
    puts = []

    class V:
        def update(self, part, body):
            puts.append(body)

            def ex():
                if "hi" in (body.get("localizations") or {}):
                    raise HttpError(SimpleNamespace(status=400, reason="bad"), b"invalidVideoMetadata")
                return {}
            return SimpleNamespace(execute=ex)
    yt = SimpleNamespace(videos=lambda: V())
    three = {k: {"title": k, "description": k} for k in ("ko", "hi", "ja")}
    ok, bad = mods.upload.update_localized(yt, "a", {"title": "A"}, three)
    assert sorted(ok) == ["ja", "ko"] and bad == ["hi"] and "hi" not in puts[-1]["localizations"]
    ok, bad = mods.upload.update_localized(yt, "a", {"title": "A"}, {"ko": three["ko"]})
    assert bad == [] and len(puts) == 5                                           # 거절 없으면 한 번에
