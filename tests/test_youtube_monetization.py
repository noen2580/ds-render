"""유튜브 업로드 기본값·채널 프로필 비교 — 자격증명 없이 확인한다."""
import json
import sys
from pathlib import Path

import pytest

WORKER = Path(__file__).resolve().parents[1] / "worker" / "youtube_shorts"
sys.path.insert(0, str(WORKER))

# API 이미지에는 worker/ 가 없다(.dockerignore) — deploy.sh 게이트에서는 건너뛴다.
if not WORKER.is_dir():
    pytest.skip("worker/ 없음 (API 컨테이너)", allow_module_level=True)
pytest.importorskip("googleapiclient")
import youtube_upload  # noqa: E402
import channel_settings  # noqa: E402


def test_upload_body_marks_synthetic_only_when_asked():
    """Veo 훅 장면이 들어간 영상만 '합성 콘텐츠'로 표시한다."""
    assert "containsSyntheticMedia" not in youtube_upload.build_body("t", "d", [], "public")["status"]
    assert youtube_upload.build_body("t", "d", [], "public", synthetic=True)["status"]["containsSyntheticMedia"] is True


def test_upload_body_monetization_defaults():
    b = youtube_upload.build_body("t" * 150, "d", ["a"], "public")
    assert len(b["snippet"]["title"]) == 100
    assert b["snippet"]["categoryId"] == "26"
    assert b["snippet"]["defaultLanguage"] == "ko"
    assert b["snippet"]["defaultAudioLanguage"] == "ko"
    assert b["status"]["selfDeclaredMadeForKids"] is False
    assert b["status"]["privacyStatus"] == "public"
    assert b["status"]["embeddable"] is True


def test_keywords_roundtrip():
    words = ["생활용품 추천", "살림템", "dsportal"]
    s = channel_settings.keywords_to_str(words)
    assert s == '"생활용품 추천" 살림템 dsportal'
    assert channel_settings.keywords_from_str(s) == words


def test_desired_changes_only_diff():
    profile = json.loads(channel_settings.PROFILE_PATH.read_text(encoding="utf-8"))
    cur = {"description": profile["description"], "country": "KR",
           "keywords": channel_settings.keywords_to_str(profile["keywords"]), "title": "x"}
    ch = channel_settings.desired_changes(cur, profile)
    assert set(ch) == {"defaultLanguage"}
    assert ch["defaultLanguage"] == (None, "ko")


def test_profile_description_within_limit_and_discloses():
    profile = json.loads(channel_settings.PROFILE_PATH.read_text(encoding="utf-8"))
    assert len(profile["description"]) <= 1000
    assert "쿠팡 파트너스" in profile["description"]
    assert len(channel_settings.keywords_to_str(profile["keywords"])) <= 500
