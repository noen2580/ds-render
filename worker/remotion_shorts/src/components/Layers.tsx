// 5층 스택의 상단 3개 — 그레이드 → 그레인 → 비네트 (스킬 규칙 5).
// 서로 다른 소재(쿠팡 상품 사진 + Pexels 실사 영상)를 하나의 톤으로 묶는 역할.
import React from "react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { theme } from "../theme";

export const BgMesh: React.FC = () => {
  const f = useCurrentFrame();
  const d1 = Math.sin(f / 55) * 50;
  const d2 = Math.cos(f / 70) * 40;
  return (
    <AbsoluteFill style={{ background: theme.colors.bg }}>
      <div style={{ position: "absolute", width: 1200, height: 1200, borderRadius: "50%",
        top: -430, left: -280 + d1, filter: "blur(60px)",
        background: `radial-gradient(circle, ${theme.colors.primary}26, transparent 62%)` }} />
      <div style={{ position: "absolute", width: 900, height: 900, borderRadius: "50%",
        bottom: -380, right: -240 - d2, filter: "blur(80px)",
        background: `radial-gradient(circle, ${theme.colors.accent}1A, transparent 65%)` }} />
    </AbsoluteFill>
  );
};

export const Grade: React.FC = () => (
  <AbsoluteFill style={{ pointerEvents: "none" }}>
    <AbsoluteFill style={{ backgroundColor: theme.colors.primary,
      mixBlendMode: "soft-light", opacity: 0.14 }} />
    <AbsoluteFill style={{ background:
      "linear-gradient(180deg, rgba(0,0,0,0.28), transparent 26%, transparent 70%, rgba(0,0,0,0.34))" }} />
  </AbsoluteFill>
);

export const Grain: React.FC = () => {
  const f = useCurrentFrame();
  const noise = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='220' height='220'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='220' height='220' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E")`;
  return <AbsoluteFill style={{ pointerEvents: "none", backgroundImage: noise,
    backgroundSize: "220px",
    backgroundPosition: `${(f * 7) % 220}px ${(f * 13) % 220}px`,
    opacity: 0.045, mixBlendMode: "overlay" }} />;
};

export const Vignette: React.FC = () => (
  <AbsoluteFill style={{ pointerEvents: "none", background:
    "radial-gradient(ellipse at center, transparent 54%, rgba(0,0,0,0.26) 100%)" }} />
);
