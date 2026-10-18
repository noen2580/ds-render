// 쇼츠 썸네일 — 정지 이미지 한 장. `npx remotion still` 로 뽑는다.
//
// 왜 만드나 — 쇼츠 피드에서는 영상 첫 프레임이 쓰이지만, **검색 결과·채널의 쇼츠 탭·
// 구독 피드에서는 썸네일이 노출된다.** 지금까지 아무것도 올리지 않아 그 자리에
// 임의의 프레임이 잡혔다.
//
// 문구 규칙(하람마케팅 자료에서 가져옴, 실사용 근거 있는 규칙):
//   핵심 6자 이내 / 상세 12자 이내 / 배지 6자 안팎
//   **제목을 그대로 반복하지 않는다** — 제목은 검색결과에 이미 나오고, 통째로 반복하면
//   글자가 작아져 아무것도 안 읽힌다. 핵심 낱말만 크게, 나머지는 작게.
//
// 세로(1080x1920)로 만든다. 쇼츠 썸네일은 세로로 잘려 노출되므로, 16:9로 만들면
// 좌우가 잘려나가 문구가 깨진다.
import React from "react";
import { AbsoluteFill, Img, staticFile } from "remotion";
import { theme } from "../theme";
import { BgMesh, Grade, Vignette } from "../components/Layers";

export const Thumbnail: React.FC<{
  badge: string;   // "2026 TOP 5" — 기한·숫자
  main: string;    // 카테고리. 6자 이내로 들어오는 값
  sub: string;     // 12자 이내
  image?: string;  // 상품 사진
}> = ({ badge, main, sub, image }) => (
  <AbsoluteFill style={{ backgroundColor: theme.colors.bg }}>
    <BgMesh />

    {/* 배지 — 숫자와 연도만. 근거 없는 과장 표현은 쓰지 않는다. */}
    <AbsoluteFill style={{ alignItems: "center" }}>
      <div style={{
        position: "absolute", top: 300, padding: "14px 34px", borderRadius: 999,
        background: theme.colors.primary, color: "#101014",
        fontFamily: theme.font, fontSize: 46, fontWeight: 800, letterSpacing: -1,
      }}>{badge}</div>

      {/* 핵심 — 화면에서 가장 큰 글자. 멀리서도 이것 하나는 읽혀야 한다. */}
      <div style={{
        position: "absolute", top: 380, width: 1000, textAlign: "center",
        fontFamily: theme.font, fontSize: 150, fontWeight: 900, lineHeight: 1.05,
        color: theme.colors.text, textShadow: "0 8px 40px rgba(0,0,0,0.75)",
      }}>{main}</div>

      {/* 상세 — 작게. 핵심을 보조하는 한 줄. */}
      <div style={{
        position: "absolute", top: 560, width: 940, textAlign: "center",
        fontFamily: theme.font, fontSize: 56, fontWeight: 700,
        color: theme.colors.textDim,
      }}>{sub}</div>

      {image && (
        <div style={{
          position: "absolute", top: 700, width: 720, height: 720,
          borderRadius: 40, overflow: "hidden", background: "#fff",
          border: `6px solid ${theme.colors.primary}`,
          boxShadow: `0 40px 90px -20px rgba(0,0,0,0.8), 0 0 90px ${theme.colors.glow}`,
        }}>
          <Img src={staticFile(image)}
               style={{ width: "100%", height: "100%", objectFit: "contain" }} />
        </div>
      )}
    </AbsoluteFill>

    <Grade />
    <Vignette />
  </AbsoluteFill>
);
