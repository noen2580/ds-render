// 씬을 조립하는 최소 단위들. **카테고리마다 새로 그리지 않기 위한** 부품 상자다.
//
// 왜 이 구조인가 — 카테고리가 72개라 "밥 짓는 캐릭터", "청소하는 캐릭터"를 하나씩
// 그리면 72벌을 만들어야 하고 그건 유지가 안 된다. 대신 움직임을 **입자·파동·회전·
// 발광** 네 가지로 추상화하면, 카테고리별로 달라지는 건 소품 실루엣 하나와 파라미터
// 몇 개뿐이다. 전기밥솥=냄비+상승입자, 청소기=노즐+흡입입자, 마사지기=목+파동링처럼
// 같은 부품을 다르게 조립한다.
//
// 난수는 반드시 remotion의 `random(seed)`를 쓴다 — Math.random을 쓰면 프레임마다
// 값이 달라져 입자가 매 프레임 순간이동한다(렌더가 프레임 단위로 독립 실행된다).
import React from "react";
import { interpolate, random, useCurrentFrame } from "remotion";
import { theme } from "../theme";

/** 위로 올라가며 흔들리다 사라지는 입자 — 김, 향, 온기. */
export const Rise: React.FC<{
  seed: string; count?: number; x: number; y: number; spread?: number;
  rise?: number; size?: number; color?: string; period?: number;
}> = ({ seed, count = 14, x, y, spread = 150, rise = 420, size = 26,
       color = "#FFFFFF", period = 78 }) => {
  const frame = useCurrentFrame();
  return (
    <>
      {new Array(count).fill(0).map((_, i) => {
        // 입자마다 시작 위상을 달리해 한꺼번에 솟구치지 않게 한다.
        const phase = ((frame + random(`${seed}p${i}`) * period) % period) / period;
        const dx = (random(`${seed}x${i}`) - 0.5) * spread;
        const wob = Math.sin(phase * Math.PI * 2.6 + i) * 26;
        const s = size * (0.6 + random(`${seed}s${i}`) * 0.8);
        return (
          <div key={i} style={{
            position: "absolute", left: x + dx + wob, top: y - phase * rise,
            width: s, height: s, borderRadius: "50%", background: color,
            filter: `blur(${10 + s * 0.35}px)`,
            // 바닥에서 태어나 중간에 가장 진하고 위에서 사라진다.
            opacity: interpolate(phase, [0, 0.18, 0.62, 1], [0, 0.82, 0.45, 0]),
            transform: `scale(${interpolate(phase, [0, 1], [0.55, 1.5])})`,
          }} />
        );
      })}
    </>
  );
};

/** 한 점으로 빨려드는 입자 — 흡입, 집중. Rise의 반대 방향 버전. */
export const Suck: React.FC<{
  seed: string; count?: number; x: number; y: number; radius?: number;
  size?: number; color?: string; period?: number;
}> = ({ seed, count = 18, x, y, radius = 340, size = 16,
       color = theme.colors.textDim, period = 64 }) => {
  const frame = useCurrentFrame();
  return (
    <>
      {new Array(count).fill(0).map((_, i) => {
        const phase = ((frame + random(`${seed}q${i}`) * period) % period) / period;
        const ang = random(`${seed}a${i}`) * Math.PI * 2;
        const r = radius * (1 - phase);
        const s = size * (0.5 + random(`${seed}z${i}`) * 0.9);
        return (
          <div key={i} style={{
            position: "absolute",
            left: x + Math.cos(ang) * r, top: y + Math.sin(ang) * r * 0.55,
            width: s, height: s, borderRadius: "50%", background: color,
            filter: "blur(3px)",
            opacity: interpolate(phase, [0, 0.2, 0.85, 1], [0, 0.95, 0.6, 0]),
          }} />
        );
      })}
    </>
  );
};

/** 퍼져나가는 동심원 — 진동, 파동, 알림. */
export const Rings: React.FC<{
  x: number; y: number; count?: number; max?: number;
  period?: number; color?: string; thickness?: number;
}> = ({ x, y, count = 3, max = 460, period = 70,
       color = theme.colors.primary, thickness = 4 }) => {
  const frame = useCurrentFrame();
  return (
    <>
      {new Array(count).fill(0).map((_, i) => {
        const phase = ((frame + (i * period) / count) % period) / period;
        const d = max * phase;
        return (
          <div key={i} style={{
            position: "absolute", left: x - d / 2, top: y - d / 2,
            width: d, height: d, borderRadius: "50%",
            border: `${thickness}px solid ${color}`,
            opacity: interpolate(phase, [0, 0.25, 1], [0, 0.75, 0]),
          }} />
        );
      })}
    </>
  );
};

/** 맥동하는 발광 — 열, 전원, 작동 중임을 알리는 신호. */
export const Glow: React.FC<{
  x: number; y: number; size?: number; color?: string;
  period?: number; base?: number;
}> = ({ x, y, size = 520, color = theme.colors.glow, period = 62, base = 0.42 }) => {
  const frame = useCurrentFrame();
  const p = base + Math.sin((frame / period) * Math.PI * 2) * 0.18;
  return (
    <div style={{
      position: "absolute", left: x - size / 2, top: y - size / 2,
      width: size, height: size, borderRadius: "50%", filter: "blur(58px)",
      opacity: p, background: `radial-gradient(circle, ${color}, transparent 68%)`,
    }} />
  );
};
