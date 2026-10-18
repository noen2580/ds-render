# ds-render

dsportal 쇼츠·장편 영상 렌더러. GitHub Actions 에서 돈다.

- `worker/youtube_shorts/cloud_worker.py`: 쇼츠 렌더. NAS 작업 대기열(`WORKER_API`)에서 대본을 받아 TTS, Remotion 렌더, 검사, 유튜브 업로드를 하고 결과를 돌려준다. 워크플로는 `.github/workflows/shorts-render.yml`.
- `worker/longform_music/`: 수면 음악 장편. 워크플로는 `longform-music.yml`(정기 제작, `longform-run` 브랜치 요청).
- 대본 생성, 상품 선정, 발행은 비공개 저장소에 있다. 이 저장소에는 렌더와 업로드만 둔다.

키는 저장소 Secrets 에만 둔다. 코드에 키를 넣지 않는다. 실행 로그는 공개이므로 키나 토큰을 출력하지 않는다.

라이선스를 붙이지 않았다. 코드는 공개되어 있지만 사용 권한을 주지 않는다(All rights reserved).
