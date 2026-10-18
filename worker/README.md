# worker — 쇼츠 렌더(GitHub Actions)

`.github/workflows/shorts-render.yml` 이 이 폴더만 받아 돌린다. NAS 큐의 대본을 토큰 API(`api/routers/worker.py`)로
받아 TTS(Edge)·Remotion 렌더·자동 검사·유튜브 공개 업로드 후, 결과와 완성 mp4 를 NAS 로 돌려준다.

- `youtube_shorts/cloud_worker.py` 진입점(클라우드). PC 판(shorts_worker.py)은 2026-10-18 저장소를 나누며 뺐다.
- `youtube_shorts/make_explainer_short.py` 한 편 제작(PC 와 같은 코드), `bgm.py` 자체 BGM(`cache/bgm/own`)
- `remotion_shorts/` Explainer 컴포지션(글꼴은 렌더 때 Google Fonts 에서 받는다)

2026-10-02 PC(`E:\Work\docker\tools`)에서 옮겼다. 이후 수정은 **이 폴더가 원본**이다.
NAS 자동 배포는 이 폴더를 받지 않는다(tools/nas_autodeploy.sh 제외 목록).
