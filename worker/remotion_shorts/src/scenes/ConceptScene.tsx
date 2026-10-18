// 개념 검증 씬 — "전체를 모션으로 만들고, 상품을 부각할 때 실제 상품 이미지를 얹는다".
//
// 앞부분: 카테고리 상황을 그래픽으로 연기한다(밥솥이면 김이 오르는 냄비).
//   실사 스톡에 없는 장면도 만들 수 있고, 라이선스가 걸릴 여지가 없다.
// 뒷부분: 소품이 뒤로 물러나고 **진짜 쿠팡 상품 사진**이 그 자리를 차지한다.
//   화면과 구매 링크가 같은 물건이어야 한다는 원칙은 그대로다 — 그래픽은 어디까지나
//   상황이고, 상품은 실물 사진이어야 한다.
//
// 핵심은 두 구간이 **끊기지 않고 이어진다**는 것이다. 소품과 상품 카드가 같은 발광을
// 공유하고 같은 자리에서 교대하므로, 컷이 아니라 "카메라가 초점을 옮긴" 것처럼 읽힌다.
import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile,
         useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { BgMesh, Grade, Grain, Vignette } from "../components/Layers";
import { useBreath } from "../components/Motion";
import { Glow } from "../components/Primitives";
import { RECIPES, useHandoff, type Recipe } from "./recipes";

const CARD = 700;
const CARD_TOP = 420;          // 기존 ffmpeg 파이프라인의 _CARD_TOP과 같은 값
const CX = 540;

export const ConceptScene: React.FC<{
  recipe?: keyof typeof RECIPES; image: string; revealAt?: number;
}> = ({ recipe = "rice", image, revealAt = 100 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const r: Recipe = RECIPES[recipe];
  const h = useHandoff(revealAt);
  const breath = useBreath();

  // 상품 카드는 스프링으로 들어온다 — 교대 시점이 물리적으로 느껴져야 "얹혔다"가 아니라
  // "바뀌었다"로 읽힌다.
  const card = spring({ frame: frame - revealAt, fps, config: theme.spring.snappy });

  return (
    <AbsoluteFill>
      <BgMesh />

      {/* 두 구간이 공유하는 발광 — 소품에서 카드로 초점이 옮겨가도 빛은 끊기지 않는다. */}
      <Glow x={CX} y={interpolate(h, [0, 1], [920, CARD_TOP + CARD / 2])} size={620} />

      {/* 1구간: 카테고리 상황 그래픽. 교대하며 뒤로 물러난다(축소 + 하강 + 흐려짐). */}
      <AbsoluteFill style={{
        opacity: 1 - h,
        transform: `scale(${interpolate(h, [0, 1], [1, 0.82])}) `
                 + `translateY(${interpolate(h, [0, 1], [0, 70])}px)`,
        filter: `blur(${h * 9}px)`,
      }}>
        <r.fx />
        <r.prop />
      </AbsoluteFill>

      {/* 2구간: 실제 상품 사진. 기존 파이프라인과 같은 700 정사각 카드·같은 위치. */}
      <AbsoluteFill style={{ alignItems: "center", opacity: card }}>
        <div style={{
          position: "absolute", top: CARD_TOP, width: CARD, height: CARD,
          borderRadius: 32, overflow: "hidden", background: "#fff",
          border: "1px solid rgba(255,255,255,0.10)",
          boxShadow: "0 40px 80px -20px rgba(0,0,0,0.65)",
          transform: `scale(${interpolate(card, [0, 1], [0.86, 1]) * breath}) `
                   + `translateY(${interpolate(card, [0, 1], [56, 0])}px)`,
        }}>
          <Img src={staticFile(image)}
               style={{ width: "100%", height: "100%", objectFit: "contain" }} />
        </div>
      </AbsoluteFill>

      <Grade />
      <Grain />
      <Vignette />
    </AbsoluteFill>
  );
};
