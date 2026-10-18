// 상품 공개 씬 — 정지 사진 한 장을 "움직이는 화면"으로 만드는 게 목적.
//
// 기존 ffmpeg판은 이 구간이 14초 내내 정지 사진이었다. 여기서는 카드가 스프링으로
// 올라오고, 스포트라이트가 퍼지고, 모서리 브래킷이 스태거로 붙고, 4.5초마다 라이트
// 스윕이 지나가고, 카드가 계속 미세하게 숨쉰다. 상품은 objectFit:contain이라 안 잘린다.
//
// **상품명 텍스트는 넣지 않는다.** 자막이 이미 "결론부터 말하면 이겁니다. 쿠첸 브레인…"
// 으로 같은 내용을 말하고, 위치도 자막 바(1148~1248)와 정확히 겹쳤다(실측).
import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { BgMesh, Grade, Grain, Vignette } from "../components/Layers";
import { Enter, KenBurnsCard, useBreath } from "../components/Motion";

const CARD = 700;
const CARD_TOP = theme.safe.top + 150;   // 438 — 자막 바(1148) 위에서 끝난다
const SWEEP_PERIOD = 112;                // 프레임(약 4.5초)마다 라이트 스윕

/** 카드 모서리 브래킷 — 4개가 스태거로 붙는다. 텍스트가 아니라 자막과 안 겹친다. */
const Brackets: React.FC<{ delay: number }> = ({ delay }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const L = 54, T = 5;
  const line = `${T}px solid ${theme.colors.primary}`;
  const corners: React.CSSProperties[] = [
    { top: -T, left: -T, borderTop: line, borderLeft: line },
    { top: -T, right: -T, borderTop: line, borderRight: line },
    { bottom: -T, left: -T, borderBottom: line, borderLeft: line },
    { bottom: -T, right: -T, borderBottom: line, borderRight: line },
  ];
  return (
    <>
      {corners.map((c, i) => {
        const s = spring({ frame: frame - delay - i * 5, fps, config: theme.spring.snappy });
        return (
          <div key={i} style={{
            position: "absolute", width: L, height: L, ...c,
            opacity: s, transform: `scale(${interpolate(s, [0, 1], [0.6, 1])})`,
          }} />
        );
      })}
    </>
  );
};

/** 주기적으로 카드 위를 지나가는 라이트 스윕 — "90프레임마다 새 요소" 규칙 충족. */
const Sweep: React.FC = () => {
  const frame = useCurrentFrame();
  const phase = (frame % SWEEP_PERIOD) / SWEEP_PERIOD;
  const x = interpolate(phase, [0, 1], [-CARD, CARD * 1.6],
    { easing: theme.ease.inOut });
  const o = interpolate(phase, [0, 0.15, 0.5, 0.85, 1], [0, 0.5, 0.35, 0, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none" }}>
      <div style={{ position: "absolute", top: -80, bottom: -80, left: x, width: 190,
        transform: "rotate(14deg)", opacity: o, filter: "blur(24px)",
        background: `linear-gradient(90deg, transparent, ${theme.colors.text}, transparent)` }} />
    </div>
  );
};

export const ProductScene: React.FC<{ image: string; name?: string }> = ({ image }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const breath = useBreath();
  const halo = spring({ frame, fps, config: theme.spring.smooth });

  return (
    <AbsoluteFill>
      <BgMesh />
      <AbsoluteFill style={{ alignItems: "center" }}>
        <div style={{ position: "absolute", top: CARD_TOP - 90, width: CARD + 200,
          height: CARD + 200, borderRadius: "50%", filter: "blur(70px)",
          opacity: halo * 0.55,
          background: `radial-gradient(circle, ${theme.colors.glow}, transparent 66%)` }} />

        <Enter delay={4} style={{ position: "absolute", top: CARD_TOP }}>
          <div style={{ position: "relative", width: CARD, height: CARD,
            transform: `scale(${breath})` }}>
            <div style={{ width: "100%", height: "100%", borderRadius: 32, overflow: "hidden",
              background: "#fff", border: "1px solid rgba(255,255,255,0.10)",
              boxShadow: "0 40px 80px -20px rgba(0,0,0,0.65)" }}>
              <KenBurnsCard src={image} />
              <Sweep />
            </div>
            <Brackets delay={20} />
          </div>
        </Enter>
      </AbsoluteFill>
      <Grade />
      <Grain />
      <Vignette />
    </AbsoluteFill>
  );
};
