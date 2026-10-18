export type Segment = {
  index: number; text: string; start: number; duration: number;
  source: string; isVideo: boolean;
  // 캐릭터 모드에서만 채워진다 — export_assets.py --character
  character?: string;      // public/character/ 안의 클립 파일명
  showProduct?: boolean;   // 이 구간에 상품 카드를 띄우는가
  productImage?: string;
};
export type Cue = { line: string; start: number; end: number };
export type Manifest = {
  postId: number; title: string; titleSub: string; titleMain: string;
  category: string; heroName: string; fps: number; width: number; height: number;
  audio: string; totalDuration: number;
  safe: { top: number; bottom: number; right: number };
  segments: Segment[]; cues: Cue[];
  // 쿠팡 상세페이지에서 뽑아 점수순으로 정렬한 컷(coupang_detail.py).
  // headline 은 판매자가 쓴 문구다 — 우리가 만든 자막보다 대개 세다.
  cuts?: { file: string; score: number; kind: string; headline: string }[];
};
