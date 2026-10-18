// make_explainer_short.py 가 쓰는 매니페스트 형식. 시간은 전부 초 단위.
export type ExScene = {
  type: "hook" | "point" | "answer" | "cta";
  index: number;             // point 는 1~3
  start: number;
  duration: number;
  headline: string;
  sub: string;
  highlight: string;         // headline 안의 강조 단어(없으면 "")
  image?: string;            // public/ 기준 경로 — 상품 쇼츠는 모든 장면, 블로그 쇼츠는 hook 만
  video?: string;            // 상품 쇼츠 hook — Veo 로 만든 '불편한 상황' 클립(상품은 나오지 않는다)
  label?: string;            // point 배지 옆 문구(기본 "기준") — 상품 쇼츠는 "포인트"
  options?: { if: string; then: string }[];   // answer 전용 — 조건별 선택
  code?: string;             // 상품 쇼츠 cta — 링크인바이오 번호("#12")
  name?: string;             // 상품 쇼츠 cta — 짧은 상품명
};
export type ExCue = { text: string; start: number; end: number };
export type ExManifest = {
  kind: "explainer";
  postId: number;
  fps: number;
  width: number;
  height: number;
  totalDuration: number;
  audio: string;             // public/ 기준 — 내레이션+BGM 믹스
  category: string;
  disclosure?: string;       // 화면 하단 제휴 고지(영상 안에서 알려야 한다)
  scenes: ExScene[];
  cues: ExCue[];
};
