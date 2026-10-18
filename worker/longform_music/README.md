# 3시간 음악 영상 반자동 제작 (첫 카테고리: 수면)

Lyria로 곡을 여러 개 만들고, 자동 검사를 통과한 곡만 겹쳐 이어 3시간(10,800초) 1080p 영상을 만든 뒤
유튜브에 **비공개**로 올린다. 공개 전환은 사람이 스튜디오에서 검수한 뒤 직접 한다.

```
기획(presets.py) → Lyria 3 Pro 생성(lyria.py) → 곡별 자동 검사(audio.analyze)
   → 검사 탈락·사람이 뺀 곡만큼 다시 생성 → 음량 맞춤 + 8초 겹쳐 잇기 → 정확히 10,800초(audio.assemble)
   → Imagen 배경 이미지(작업마다 다른 장면, 실패하면 자체 제작 밤하늘) + 느린 줌 60초 루프를 복사로 이어 붙여
     1080p 렌더(video.py), 같은 이미지로 썸네일 → 최종 검사
   → 비공개 업로드 + 챕터·AI 고지·합성 콘텐츠 표시(upload.py) → report.md 체크리스트로 사람 검수
```

## ChatGPT 안과 다르게 정한 것

| 항목 | ChatGPT 안 | 여기 | 이유 |
|---|---|---|---|
| 모델 | Lyria 2 (`lyria-002`, 30초) | Lyria 3 Pro (`lyria-3-pro-preview`, 최대 약 3분) | 3시간 ≈ 60~75곡이면 된다. 곡당 $0.08 |
| 비용 | 360클립 × $0.06 ≈ $21.6 | 약 $5~6 | Vertex AI 가격표(2026-10-10 확인) |
| 실행 환경 | Cloud Run Jobs + Scheduler + Firestore | GitHub Actions 수동 실행 + 캐시 | 쇼츠와 같은 인증·업로드 경로 재사용, 상시 인프라 없음 |
| 기획 에이전트 | Gemini | 조합표(악기 × 배경 소리 × 조성) | 곡마다 다르게 만드는 데 충분하고 공짜. 필요하면 나중에 Gemini 로 |
| 배경 영상 | 외부 루프 영상 | Imagen 으로 만든 장면 이미지 + 느린 줌 루프(약 $0.04) | 라이선스 확인할 것이 없다. 설명란에 AI 이미지 고지 |
| 렌더 | 3시간 재인코딩 | 60초 루프만 인코딩 후 복사 | 3시간 영상 렌더가 수십 초(조립 포함 약 7분) |

## 실행

GitHub → Actions → **longform-music** → Run workflow

| 입력 | 예 | 설명 |
|---|---|---|
| job | `sleep-001` | 같은 이름이면 이전 곡을 캐시에서 불러와 이어서 만든다 |
| hours | `3` | 시험은 `0.17`(약 10분, 곡 4~5개, 약 $0.4) |
| max_cost | `8` | 이 작업의 누적 Lyria 비용 한도(달러) |
| reject | `t004,t017` | 들어 보고 뺄 곡 |
| upload | 체크 | 끝나면 비공개 업로드 |

또는 `longform-run` 브랜치에 `worker/longform_music/run-request.json`(같은 항목, JSON)을 바꿔 푸시하면 시작된다
(Actions 실행 권한 없이 푸시만 되는 Claude 세션용).

결과: 실행 요약에 보고서, 아티팩트에 `report.md`, `manifest.json`, `thumbnail.jpg`, 앞 15분 `preview_15min.mp3`.

로컬: `cd worker && python longform_music/run.py all --job sleep-001 [--upload]` (사용법은 run.py 맨 위)

## 준비

1. **Vertex 인증** — 쇼츠 Veo 와 같다(`/mnt/project-files/shorts/veo-워크로드아이덴티티-설정.md`).
   Veo 가 실제로 성공한 경로는 `VERTEX_API_KEY` 시크릿(프로젝트 `VERTEX_API_KEY_PROJECT`)이다.
   그 키에 Lyria 3 가 막혀 있으면 키의 API 제한·프로젝트의 모델 사용 설정을 확인한다.
2. **유튜브 채널** — 수면 음악은 별도 채널 **Moonlit Hush (@moonlit-hushsleep)** 에 올린다(같은 구글 계정의 브랜드 채널).
   PC에서 `python longform_music/get_channel_token.py` 로 인증하면서 채널 선택 화면에서 Moonlit Hush 를 고르고,
   받은 refresh token 을 GitHub 시크릿 `SLEEP_YT_REFRESH_TOKEN` 에 넣는다. 없으면 업로드 단계가 멈춘다
   (쇼핑 쇼츠 채널 토큰으로 잘못 올라가지 않게).

## 자동 검사 기준

곡마다: 60초 미만, 중간 3초 이상 무음(-60dBFS), 1초 단위 음량 12dB 이상 급변, 너무 작음, 가사(보컬) 있음, 중복 파일
→ 탈락하면 그 곡은 안 쓰고 다음 기획 곡을 만든다.
최종 파일: 길이 10,800초 ±2초(영상·소리 각각), 1920×1080 H.264, AAC 48kHz 스테레오.

## 공개 전 사람 검수 (report.md 에 체크리스트로 나온다)

- Google Cloud 생성형 AI 약관·금지 사용 정책: 결과물 이용 가능, 특정 곡·아티스트 모방 프롬프트 없음
- 스튜디오에서 처음·중간 몇 곳·끝 들어 보기 (보컬, 튀는 소리, 반복감, 이음매)
- 스튜디오 '저작권' 검사 결과(Content ID 주장 없음). Lyria 결과물에는 SynthID 워터마크·C2PA 정보가 들어간다
- '변경되거나 합성된 콘텐츠' 표시(업로드 때 `containsSyntheticMedia` 로 자동 설정, 유튜브는 AI 생성 음악을 고지 대상 예시로 든다)
- 수익창출: 2025-07 부터 유튜브는 '반복·대량생산' 콘텐츠를 '비진정성 콘텐츠'로 묶어 수익 창출에서 제외한다.
  같은 틀에 음악만 바꾼 영상을 많이 올리면 걸리기 쉽다 → 영상마다 곡 구성·배경·제목을 실제로 다르게, 업로드 간격 두기
