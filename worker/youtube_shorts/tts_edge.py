"""edge-tts 기반 무료 TTS 백엔드 — 마이크로소프트 Edge 읽어주기 기능을 쓰는
비공식 클라이언트. SLA 없음, 예고 없이 동작이 바뀔 수 있음.

사용 가능한 한국어 음성 (edge-tts --list-voices로 확인):
  ko-KR-SunHiNeural               여성, General
  ko-KR-InJoonNeural               남성, General
  ko-KR-HyunsuMultilingualNeural   남성, General (신형 멀티링구얼 라인 — 대체로 더 자연스러움)

기본 속도(rate 0%)가 다소 빠르고 딱딱하게 들린다는 피드백이 있어, 기본값을 살짝
느리게(-8%) 조정했다. 너무 빠른 낭독은 특히 make_shorts.py의 _cap_duration()이
전체 길이를 58초 안에 맞추려 배속(atempo)까지 추가로 걸 때 더 부자연스러워진다 —
근본적으로는 스크립트 자체를 짧게 써서 배속이 걸릴 일을 줄이는 게 우선이다."""
import asyncio
import sys
from pathlib import Path

import edge_tts

# Windows 기본 이벤트 루프(Proactor)를 쓰면 edge-tts가 연 소켓 전송 객체가 루프가 닫힌
# 뒤에 GC되면서 "RuntimeError: Event loop is closed"를 stderr로 뱉는다. 음성 파일은 이미
# 저장이 끝난 뒤라 결과에는 영향이 없지만, 렌더 로그에 ERROR 트레이스백이 섞이면
# TTS가 실패한 것처럼 보여 엉뚱한 데를 파게 된다(실측: post#569 렌더 중 1회 발생).
# 이 스크립트는 asyncio 서브프로세스를 쓰지 않으므로(ffmpeg는 subprocess.run) 셀렉터
# 루프로 바꿔도 잃는 기능이 없다.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

DEFAULT_VOICE = "ko-KR-SunHiNeural"
DEFAULT_RATE = "-8%"


def _edge(text: str, out_path: Path, voice: str, rate: str) -> None:
    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(str(out_path))

    asyncio.run(_run())


def synthesize(text: str, out_path: Path, voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE) -> None:
    """edge-tts 로 만들고, 두 번 실패하면 Gemini TTS 로 만든다(2026-10-13, tts_gemini.py).

    2026-10-12 마이크로소프트 서버가 403 으로 거절해 상품 쇼츠 #48·#49 가 실패했다. 예비 음성은
    목소리가 달라지지만 영상이 아예 안 나가는 것보다 낫다. 어느 쪽으로 만들었는지 로그에 남긴다."""
    last = None
    for _ in range(2):
        try:
            _edge(text, out_path, voice, rate)
            if out_path.exists() and out_path.stat().st_size > 0:
                return
            last = RuntimeError("edge-tts 빈 파일")
        except Exception as e:                               # noqa: BLE001
            last = e
    import tts_gemini
    if not tts_gemini.available():
        raise last
    print(f"   edge-tts 실패({type(last).__name__}: {str(last)[:80]}) — Gemini TTS 로 대신", flush=True)
    tts_gemini.synthesize(text, out_path)
