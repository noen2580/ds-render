// 정보 전달형 쇼츠(Explainer) 전용 테마 — 색·이징·스프링·폰트는 여기서만 정한다(스킬 규칙 9).
// 캐릭터 영상(src/theme.ts, 노랑)과 분리: 이쪽은 DSPORTAL 브랜드(파랑)다.
import { Easing } from "remotion";
import { loadFont } from "@remotion/google-fonts/NotoSansKR";

const { fontFamily } = loadFont("normal", { weights: ["500", "700", "900"], ignoreTooManyRequestsWarning: true });

export const ex = {
  colors: {
    bg: "#0A0D14",
    surface: "#141A26",
    surfaceHi: "#1C2433",
    hero: "#3B82F6",          // 프레임당 한 요소만(강조 단어 또는 결론 카드)
    heroSoft: "rgba(59,130,246,0.18)",
    accent: "#22D3EE",
    text: "#F5F7FA",
    textDim: "#A7B0C0",
    line: "rgba(255,255,255,0.10)",
  },
  // 쇼츠 UI 를 피한 안전 영역(1080x1920). 하단 설명·버튼, 우측 액션 버튼 자리를 뺐다.
  safe: { top: 250, bottom: 1300, left: 64, right: 900 },
  ease: {
    out: Easing.bezier(0.16, 1, 0.3, 1),
    inOut: Easing.bezier(0.83, 0, 0.17, 1),
    in: Easing.bezier(0.7, 0, 0.84, 0),
  },
  spring: {
    snappy: { damping: 14, stiffness: 170, mass: 0.6 },
    smooth: { damping: 20, stiffness: 90, mass: 1 },
    bouncy: { damping: 10, stiffness: 180, mass: 0.7 },
  },
  font: fontFamily,
  sec: {
    exit: 0.3,      // 퇴장은 등장보다 빠르게
    sfxLead: 0.08,  // 효과음은 화면보다 2~3프레임 먼저
  },
} as const;
