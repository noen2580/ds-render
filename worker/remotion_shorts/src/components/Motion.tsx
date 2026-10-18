// 재사용 모션 조각들. 선형 보간 금지, 등장은 2~3개 속성을 함께 움직인다(스킬 규칙 1·2).
import React from "react";
import { Img, OffthreadVideo, interpolate, spring, staticFile,
         useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";

/** 등장: 투명도 + 상승 + 확대를 함께. 단독 페이드는 금지. */
export const Enter: React.FC<{ delay?: number; children: React.ReactNode;
                               style?: React.CSSProperties }> =
({ delay = 0, children, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const s = spring({ frame: frame - delay, fps, config: theme.spring.snappy });
  return (
    <div style={{ ...style, opacity: s,
      transform: `translateY(${interpolate(s, [0, 1], [46, 0])}px) scale(${interpolate(s, [0, 1], [0.94, 1])})` }}>
      {children}
    </div>
  );
};

/** 단어 단위 순차 등장. 3~6프레임 간격으로 스태거(스킬 규칙 3). */
export const WordReveal: React.FC<{ text: string; delay?: number; stagger?: number;
                                    style?: React.CSSProperties }> =
({ text, delay = 0, stagger = 4, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return (
    <div style={{ display: "flex", flexWrap: "wrap", justifyContent: "center", gap: 14, ...style }}>
      {text.split(" ").filter(Boolean).map((w, i) => {
        const s = spring({ frame: frame - delay - i * stagger, fps, config: theme.spring.snappy });
        return (
          <span key={i} style={{ display: "inline-block", opacity: s,
            transform: `translateY(${interpolate(s, [0, 1], [30, 0])}px)` }}>{w}</span>
        );
      })}
    </div>
  );
};

/** 정지 이미지용 Ken Burns — 여기서는 **상품 카드 안에서만** 움직인다.
 *  프레임 전체를 확대하면 상품이 잘리는데, 카드로 감싸면 카드 밖으로 나가지 않는다. */
export const KenBurnsCard: React.FC<{ src: string; zoomTo?: number }> = ({ src, zoomTo = 1.07 }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const scale = interpolate(frame, [0, durationInFrames], [1, zoomTo],
    { easing: theme.ease.inOut, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return <Img src={staticFile(src)} style={{ width: "100%", height: "100%",
    objectFit: "contain", transform: `scale(${scale})` }} />;
};

/** 실사 영상 소재 — 반드시 OffthreadVideo (스킬 규칙 6). */
export const Footage: React.FC<{ src: string }> = ({ src }) => (
  <OffthreadVideo src={staticFile(src)} muted
    style={{ width: "100%", height: "100%", objectFit: "cover" }} />
);

/** 2초 이상 화면에 있는 요소는 미세하게 숨쉬어야 한다(스킬 규칙 7). */
export const useBreath = (amp = 0.008, period = 90) => {
  const frame = useCurrentFrame();
  return 1 + Math.sin(frame / period * Math.PI * 2) * amp;
};
