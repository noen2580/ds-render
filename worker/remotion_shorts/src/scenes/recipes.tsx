// 카테고리별 씬 "레시피" — 소품 실루엣 하나 + 부품 조합.
//
// 이 파일이 확장 지점이다. 새 카테고리를 붙일 때 건드리는 건 여기뿐이고,
// 모션 로직은 Primitives.tsx를 그대로 쓴다. 캐릭터를 그리지 않는 이유는
// Primitives.tsx 머리말에 적어두었다 — 72개를 손으로 그릴 수 없다.
//
// 소품은 **단순 실루엣**이다. 사실적으로 그리려 들면 (1) 카테고리마다 작업량이
// 폭발하고 (2) 어설픈 사실주의가 진짜 상품 사진 옆에 놓였을 때 더 싸구려로 보인다.
// 실루엣 + 브랜드 색이면 "우리가 만든 그래픽"으로 읽혀서 오히려 톤이 맞는다.
import React from "react";
import { interpolate, useCurrentFrame } from "remotion";
import { theme } from "../theme";
import { Glow, Rings, Rise, Suck } from "../components/Primitives";

const CX = 540;          // 캔버스 가로 중앙
// 소품 중심. 상품 카드가 top 420에서 700px이므로 카드 영역(420~1120)의 중앙에 맞춘다 —
// 교대할 때 두 요소가 **같은 자리에서** 바뀌어야 컷이 아니라 초점 이동으로 읽힌다.
// 첫 시안은 소품이 화면 폭의 32%뿐이라(카드는 65%) 교대 순간 크기가 튀었다.
const CY = 770;

/** 냄비/밥솥 실루엣. 뚜껑이 김의 압력에 맞춰 아주 살짝 들썩인다. */
const Pot: React.FC = () => {
  const frame = useCurrentFrame();
  const lift = Math.max(0, Math.sin(frame / 26)) * 7;
  const body = { background: theme.colors.bgAlt,
                 border: `5px solid ${theme.colors.textDim}` };
  return (
    <>
      <div style={{ position: "absolute", left: CX - 280, top: CY - 30,
        width: 560, height: 330, borderRadius: "34px 34px 96px 96px", ...body }} />
      {/* 손잡이 좌우 */}
      {[-1, 1].map((d) => (
        <div key={d} style={{ position: "absolute", top: CY + 70,
          left: CX + d * 312 - 46, width: 92, height: 34, borderRadius: 17,
          background: theme.colors.textDim, opacity: 0.75 }} />
      ))}
      {/* 뚜껑 — 들썩임 */}
      <div style={{ position: "absolute", left: CX - 302, top: CY - 82 - lift,
        width: 604, height: 52, borderRadius: 26, ...body }} />
      <div style={{ position: "absolute", left: CX - 26, top: CY - 126 - lift,
        width: 52, height: 52, borderRadius: "50%", background: theme.colors.primary,
        boxShadow: `0 0 40px ${theme.colors.primary}` }} />
    </>
  );
};

/** 청소기 노즐 + 바닥선. */
const Nozzle: React.FC = () => (
  <>
    <div style={{ position: "absolute", left: CX - 430, top: CY + 250,
      width: 860, height: 6, borderRadius: 3, background: theme.colors.textDim,
      opacity: 0.5 }} />
    <div style={{ position: "absolute", left: CX - 175, top: CY + 158,
      width: 350, height: 92, borderRadius: "16px 16px 6px 6px",
      background: theme.colors.bgAlt, border: `6px solid ${theme.colors.textDim}` }} />
    <div style={{ position: "absolute", left: CX - 42, top: CY - 150,
      width: 84, height: 312, borderRadius: 42, background: theme.colors.bgAlt,
      border: `6px solid ${theme.colors.textDim}` }} />
  </>
);

/** 목/어깨 실루엣 — 마사지·안마 계열. */
const Neck: React.FC = () => (
  <>
    <div style={{ position: "absolute", left: CX - 100, top: CY - 300,
      width: 200, height: 200, borderRadius: "50%",
      background: theme.colors.bgAlt, border: `6px solid ${theme.colors.textDim}` }} />
    <div style={{ position: "absolute", left: CX - 240, top: CY - 70,
      width: 480, height: 390, borderRadius: "190px 190px 34px 34px",
      background: theme.colors.bgAlt, border: `6px solid ${theme.colors.textDim}` }} />
  </>
);

export type Recipe = { prop: React.FC; fx: React.FC };

export const RECIPES: Record<string, Recipe> = {
  // 전기밥솥 — 김이 올라오고 아래에서 열이 맥동한다.
  rice: {
    prop: Pot,
    fx: () => (
      <>
        <Glow x={CX} y={CY + 190} size={720} />
        <Rise seed="steam" x={CX} y={CY - 110} count={22} spread={300}
              rise={470} size={46} period={86} />
      </>
    ),
  },
  // 청소기 — 먼지가 노즐로 빨려든다.
  vacuum: {
    prop: Nozzle,
    fx: () => (
      <>
        <Glow x={CX} y={CY + 200} size={640} color="rgba(74,222,128,0.34)" />
        <Suck seed="dust" x={CX} y={CY + 200} count={28} radius={470} size={22}
              color={theme.colors.text} />
      </>
    ),
  },
  // 마사지기 — 진동이 파동으로 퍼진다.
  massage: {
    prop: Neck,
    fx: () => (
      <>
        <Glow x={CX} y={CY + 40} size={680} />
        <Rings x={CX} y={CY + 20} count={4} max={720} thickness={6} />
      </>
    ),
  },
};

/** 카테고리 이름 → 레시피 키. 매핑이 없으면 null(= 기존 실사 B-roll 경로 유지). */
export const recipeFor = (category: string): Recipe | null => {
  const c = category || "";
  if (/밥솥|인덕션|전기포트|냄비|프라이팬|에어프라이어|토스터|그릴/.test(c)) return RECIPES.rice;
  if (/청소기/.test(c)) return RECIPES.vacuum;
  if (/마사지|안마/.test(c)) return RECIPES.massage;
  return null;
};

/** 소품이 물러나고 상품 카드가 들어오는 전환 진행도(0~1). */
export const useHandoff = (revealAt: number, dur = 22) => {
  const frame = useCurrentFrame();
  return interpolate(frame, [revealAt, revealAt + dur], [0, 1],
    { easing: theme.ease.out, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
};
