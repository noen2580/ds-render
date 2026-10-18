// 정보 전달형 쇼츠의 공용 조각. 선형 이징 금지, 등장은 2~3속성, 스태거, 퇴장은 더 빠르게.
import React from "react";
import { AbsoluteFill, Img, interpolate, spring, staticFile,
         useCurrentFrame, useVideoConfig } from "remotion";
import { ex } from "./theme";
import type { ExCue, ExScene } from "./types";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;

/** 장면 퇴장 — 마지막 exit 초 동안 위로 빠지며 사라진다. */
export const useExit = () => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const n = Math.round(ex.sec.exit * fps);
  const t = interpolate(frame, [durationInFrames - n, durationInFrames], [0, 1],
    { ...clamp, easing: ex.ease.in });
  return { opacity: 1 - t, transform: `translateY(${-50 * t}px)` };
};

/** 등장: 투명도 + 상승 + 확대 */
export const Rise: React.FC<{ delay?: number; from?: number; children: React.ReactNode;
                              style?: React.CSSProperties }> =
({ delay = 0, from = 50, children, style }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: ex.spring.snappy });
  return (
    <div style={{ ...style, opacity: p,
      transform: `translateY(${interpolate(p, [0, 1], [from, 0])}px) scale(${interpolate(p, [0, 1], [0.94, 1])})` }}>
      {children}
    </div>
  );
};

/** 헤드라인 — 어절 단위 스태거 + 강조 단어 뒤로 알약이 5프레임 늦게 깔린다. */
export const Headline: React.FC<{ text: string; highlight?: string; delay?: number;
                                  size?: number; align?: "left" | "center" }> =
({ text, highlight = "", delay = 0, size = 96, align = "left" }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const words = text.split(" ").filter(Boolean);
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: `${Math.round(size * 0.12)}px ${Math.round(size * 0.26)}px`,
                  justifyContent: align === "center" ? "center" : "flex-start",
                  fontFamily: ex.font, fontWeight: 900, fontSize: size, lineHeight: 1.12,
                  letterSpacing: "-0.03em", color: ex.colors.text, wordBreak: "keep-all" }}>
      {words.map((w, i) => {
        const d = delay + i * 3;
        const p = spring({ frame: frame - d, fps, config: ex.spring.snappy });
        const hit = highlight && w.includes(highlight);
        const pill = spring({ frame: frame - d - 5, fps, config: ex.spring.smooth });
        return (
          <span key={i} style={{ position: "relative", display: "inline-block", opacity: p,
            transform: `translateY(${interpolate(p, [0, 1], [36, 0])}px) scale(${interpolate(p, [0, 1], [1.12, 1])})` }}>
            {hit ? <span style={{ position: "absolute", left: -10, right: -10, top: "14%", bottom: "4%",
              borderRadius: 16, background: ex.colors.hero, transformOrigin: "left center",
              transform: `scaleX(${pill})`, zIndex: 0 }} /> : null}
            <span style={{ position: "relative", zIndex: 1 }}>{w}</span>
          </span>
        );
      })}
    </div>
  );
};

/** 보조 문구 */
export const Sub: React.FC<{ text: string; delay?: number }> = ({ text, delay = 0 }) =>
  text ? (
    <Rise delay={delay} from={24}>
      <div style={{ fontFamily: ex.font, fontWeight: 700, fontSize: 50, color: ex.colors.textDim,
                    letterSpacing: "-0.02em", lineHeight: 1.3, wordBreak: "keep-all" }}>{text}</div>
    </Rise>
  ) : null;

/** 상품 사진 카드 — 흰 판 위에 올리고(쿠팡 사진은 흰 배경) 카드 안에서만 Ken Burns. */
export const ImageCard: React.FC<{ src: string; size: number; delay?: number; zoomIn?: boolean }> =
({ src, size, delay = 0, zoomIn = true }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const p = spring({ frame: frame - delay, fps, config: ex.spring.smooth });
  const kb = interpolate(frame, [0, durationInFrames], zoomIn ? [1, 1.08] : [1.08, 1],
    { ...clamp, easing: ex.ease.inOut });
  const float = Math.sin(frame / 26) * 4;                       // 숨쉬기
  return (
    <div style={{ width: size, height: size, borderRadius: 36, overflow: "hidden", background: "#fff",
      boxShadow: "0 40px 80px -24px rgba(0,0,0,0.7)", border: `1px solid ${ex.colors.line}`,
      opacity: p, transform: `translateY(${interpolate(p, [0, 1], [70, 0]) + float}px) rotate(${interpolate(p, [0, 1], [-4, 0])}deg) scale(${interpolate(p, [0, 1], [0.9, 1])})` }}>
      <Img src={staticFile(src)} style={{ width: "100%", height: "100%", objectFit: "contain",
        transform: `scale(${kb})` }} />
    </div>
  );
};

/** 상단 진행 바 — 장면 수만큼 칸, 현재 칸이 차오른다. + 브랜드 워드마크. */
export const TopBar: React.FC<{ scenes: ExScene[]; fps: number; disclosure?: string }> = ({ scenes, fps, disclosure }) => {
  const frame = useCurrentFrame();
  const t = frame / fps;
  return (
    <div style={{ position: "absolute", top: ex.safe.top - 150, left: ex.safe.left, right: 1080 - ex.safe.right }}>
      <div style={{ display: "flex", gap: 10 }}>
        {scenes.map((s, i) => {
          const fill = interpolate(t, [s.start, s.start + s.duration], [0, 1], clamp);
          return (
            <div key={i} style={{ flex: 1, height: 8, borderRadius: 8, background: ex.colors.line, overflow: "hidden" }}>
              <div style={{ width: `${fill * 100}%`, height: "100%", background: ex.colors.text, opacity: 0.85 }} />
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 22, fontFamily: ex.font, fontWeight: 900, fontSize: 30,
                    letterSpacing: "0.18em", color: ex.colors.textDim }}>DSPORTAL</div>
      {/* 제휴 고지 — 영상 내내 작게(공정위 추천·보증 심사지침: 영상 안에서 알릴 것). */}
      {disclosure ? <div style={{ marginTop: 8, fontFamily: ex.font, fontWeight: 500, fontSize: 26,
                                  color: ex.colors.textDim, opacity: 0.85 }}>{disclosure}</div> : null}
    </div>
  );
};

/** 하단 자막 — 문장 단위(한 줄 16자 안팎), 들어올 때 살짝 튀고 나갈 때 빠르게. */
export const Captions: React.FC<{ cues: ExCue[]; fps: number }> = ({ cues, fps }) => {
  const frame = useCurrentFrame();
  const t = frame / fps;
  const cue = cues.find((c) => t >= c.start && t < c.end);
  if (!cue) return null;
  const local = frame - Math.round(cue.start * fps);
  const p = spring({ frame: local, fps, config: ex.spring.snappy });
  const outN = Math.round(0.12 * fps);
  const endF = Math.round((cue.end - cue.start) * fps);
  const o = interpolate(local, [endF - outN, endF], [1, 0], clamp);
  return (
    <div style={{ position: "absolute", left: ex.safe.left, right: 1080 - ex.safe.right,
                  // 두 줄 상자(≈171) 아랫변이 안전 영역 끝(1300)에 닿게 — 상품 쇼츠 point 사진이 자막에 가리지 않게 내렸다(2026-10-07).
                  top: ex.safe.bottom - 175, display: "flex", justifyContent: "center" }}>
      <div style={{ opacity: Math.min(p, o), transform: `translateY(${interpolate(p, [0, 1], [18, 0])}px) scale(${interpolate(p, [0, 1], [0.96, 1])})`,
        padding: "18px 30px", borderRadius: 22, background: "rgba(0,0,0,0.62)",
        fontFamily: ex.font, fontWeight: 700, fontSize: 52, lineHeight: 1.3, color: ex.colors.text,
        textAlign: "center", wordBreak: "keep-all", whiteSpace: "pre-line", maxWidth: "100%" }}>{cue.text}</div>
    </div>
  );
};

/** 배경 — 메쉬 + 흐린 상품 사진 질감(평면 배경 금지). */
export const Backdrop: React.FC<{ image?: string }> = ({ image }) => {
  const frame = useCurrentFrame();
  const d1 = Math.sin(frame / 55) * 50, d2 = Math.cos(frame / 70) * 40;
  return (
    <AbsoluteFill style={{ background: ex.colors.bg }}>
      {image ? <Img src={staticFile(image)} style={{ position: "absolute", inset: -80, width: 1240, height: 2080,
        objectFit: "cover", filter: "blur(60px) saturate(0.8)", opacity: 0.16,
        transform: `scale(${1.1 + Math.sin(frame / 90) * 0.02})` }} /> : null}
      <div style={{ position: "absolute", width: 1200, height: 1200, borderRadius: "50%", top: -420, left: -320 + d1,
        filter: "blur(60px)", background: `radial-gradient(circle, ${ex.colors.hero}40, transparent 62%)` }} />
      <div style={{ position: "absolute", width: 900, height: 900, borderRadius: "50%", bottom: -360, right: -260 - d2,
        filter: "blur(80px)", background: `radial-gradient(circle, ${ex.colors.accent}22, transparent 65%)` }} />
    </AbsoluteFill>
  );
};

export const Finish: React.FC = () => {
  const frame = useCurrentFrame();
  const noise = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='220' height='220'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2'/%3E%3C/filter%3E%3Crect width='220' height='220' filter='url(%23n)' opacity='0.5'/%3E%3C/svg%3E")`;
  return (
    <>
      <AbsoluteFill style={{ pointerEvents: "none", background:
        "linear-gradient(180deg, rgba(0,0,0,0.35), transparent 22%, transparent 70%, rgba(0,0,0,0.45))" }} />
      <AbsoluteFill style={{ pointerEvents: "none", backgroundImage: noise, backgroundSize: "220px",
        backgroundPosition: `${(frame * 7) % 220}px ${(frame * 13) % 220}px`, opacity: 0.05, mixBlendMode: "overlay" }} />
      <AbsoluteFill style={{ pointerEvents: "none", background:
        "radial-gradient(ellipse at center, transparent 55%, rgba(0,0,0,0.3) 100%)" }} />
    </>
  );
};
