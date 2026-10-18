// 단일 테마 — 컴포넌트에 색/이징/스프링을 절대 인라인하지 않는다(스킬 규칙 9).
// 팔레트는 채널 톤(검정 배경 + 노란 수식어)에 맞춘다.
import { Easing } from "remotion";

export const theme = {
  colors: {
    bg: "#0B0B0D",
    bgAlt: "#15151A",
    primary: "#FFD54A",              // 히어로 색 — 프레임당 한 요소만
    accent: "#4ADE80",
    text: "#FFFFFF",
    textDim: "#B8B8C0",
    glow: "rgba(255, 213, 74, 0.35)",
  },
  // 세이프존 (1080x1920) — somake.ai / MEWPOT 실측값. 글자는 이 밖으로 나가면 안 된다.
  safe: { top: 288, bottom: 1248, left: 48, right: 888 },
  ease: {
    out: Easing.bezier(0.16, 1, 0.3, 1),
    inOut: Easing.bezier(0.83, 0, 0.17, 1),
    in: Easing.bezier(0.7, 0, 0.84, 0),
  },
  spring: {
    snappy: { damping: 14, stiffness: 160, mass: 0.6 },
    smooth: { damping: 20, stiffness: 90, mass: 1 },
    bouncy: { damping: 11, stiffness: 170, mass: 0.7 },
  },
  font: '"Malgun Gothic", "맑은 고딕", sans-serif',
} as const;
