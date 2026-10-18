// 상세페이지 컷 하나를 화면 가득 보여주는 씬.
//
// 왜 카드를 버렸나 — 그전에는 상품을 440px 정사각 카드에 담아 화면 위쪽에 띄웠다.
// 소재가 제휴 API 가 주는 **사진 1장**뿐이라 그 이상 할 게 없었기 때문이다.
// 이제는 상세페이지에서 컷을 14장 뽑는다(`coupang_detail.py`). 실측 렌더에서
// 10점짜리 "타사 vs 펫리서치" 비교 컷을 카드에 넣었더니 우표만 해서 안 읽혔다.
// 좋은 소재를 작은 창에 가두는 구조였다.
//
// 어떻게 채우나 — 컷은 가로 780px 고정인데 세로가 260~1600px 으로 제각각이다.
// cover 로 채우면 낮은 컷이 3배로 확대돼 뭉개지고, contain 으로 맞추면 위아래에
// 검은 띠가 생긴다. 그래서 **가로를 화면에 맞추고, 뒤에 같은 이미지를 흐리게 깔아**
// 남는 자리를 메운다. 어떤 비율이 와도 화면이 비지 않는다.
//
// 그리고 천천히 확대한다. 정지 이미지를 2~3초 띄우면 영상이 멈춘 것처럼 보인다.
import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile,
         useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Grade, Grain, Vignette } from "../components/Layers";

export const CutScene: React.FC<{
  image: string;         // public 기준 경로
  zoomIn?: boolean;      // 컷마다 방향을 번갈아 — 같은 방향만 반복하면 멀미가 난다
}> = ({ image, zoomIn = true }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // 등장 페이드는 짧게. 컷이 2~3초라 길면 절반이 흐린 상태로 지나간다.
  const fade = interpolate(frame, [0, 8], [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const z = interpolate(frame, [0, durationInFrames],
    zoomIn ? [1.0, 1.08] : [1.08, 1.0],
    { easing: theme.ease.inOut, extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ backgroundColor: theme.colors.bg, opacity: fade }}>
      {/* 배경 — 같은 컷을 화면에 꽉 채우고 흐리게. 남는 자리를 컷 자신의 색으로 메운다. */}
      <AbsoluteFill>
        <Img src={staticFile(image)}
             style={{ width: "100%", height: "100%", objectFit: "cover",
                      filter: "blur(48px) brightness(0.45) saturate(1.2)",
                      transform: "scale(1.15)" }} />
      </AbsoluteFill>

      {/* 본체 — 가로를 꽉 채우고 세로는 그대로. 잘리는 일이 없다. */}
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
        <Img src={staticFile(image)}
             style={{ width: "100%", height: "auto", maxHeight: "100%",
                      objectFit: "contain", transform: `scale(${z})`,
                      boxShadow: "0 40px 90px -30px rgba(0,0,0,0.9)" }} />
      </AbsoluteFill>

      <Grade />
      <Grain />
      <Vignette />
    </AbsoluteFill>
  );
};
