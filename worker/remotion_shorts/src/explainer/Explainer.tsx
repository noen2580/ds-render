// 정보 전달형 쇼츠 — hook → point×3 → answer → cta.
// 무음으로 봐도 이해돼야 한다: 장면마다 큰 헤드라인 + 보조 문구, 하단엔 문장 단위 자막.
import React from "react";
import { AbsoluteFill, Audio, Img, Sequence, interpolate, spring, staticFile,
         useCurrentFrame, useVideoConfig } from "remotion";
import { ex } from "./theme";
import { Backdrop, Captions, Finish, Headline, ImageCard, Rise, Sub, TopBar, useExit } from "./parts";
import type { ExManifest, ExScene } from "./types";
import { Footage } from "../components/Motion";

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const W = ex.safe.right - ex.safe.left;

// 세로 배치: 상단 진행 바(≈250) 아래부터 자막 위(≈1060)까지가 본문 영역이다.
const TOP = ex.safe.top + 80;
// 상품 쇼츠 point 장면 사진 칸 — 배지+제목 한 줄 아래부터 자막 윗선(1125) 바로 위까지.
const PHOTO_TOP = TOP + 190;
const PHOTO_BOTTOM = 1115;
// 상품 쇼츠 point/answer 장면의 상품 사진 한 변. 배지(132)+여백 줄 높이 안에서 헤드라인과 겹치지 않게.
const SIDE_IMG = 220;

/** HOOK — 첫 15프레임 안에 움직임. 질문이 튀어 들어오고 상품 사진이 아래에서 올라온다. */
const HookScene: React.FC<{ s: ExScene }> = ({ s }) => {
  const exit = useExit();
  return (
    <AbsoluteFill style={{ ...exit }}>
      {s.video ? (
        // 불편 장면 클립을 전면에 깔고, 글자가 읽히게 위·아래를 어둡게 덮는다.
        <AbsoluteFill>
          <Footage src={s.video} />
          <AbsoluteFill style={{ background:
            "linear-gradient(180deg, rgba(0,0,0,0.78) 0%, rgba(0,0,0,0.35) 38%, rgba(0,0,0,0.35) 62%, rgba(0,0,0,0.8) 100%)" }} />
          {/* 영상 안 표시 — 사실적인 AI 장면을 실제 촬영으로 오해하지 않게. */}
          <div style={{ position: "absolute", right: 1080 - ex.safe.right, top: ex.safe.top - 128, fontFamily: ex.font, fontWeight: 700,
                        fontSize: 26, color: "rgba(255,255,255,0.8)", padding: "4px 12px", borderRadius: 12,
                        background: "rgba(0,0,0,0.45)" }}>AI 생성 장면</div>
        </AbsoluteFill>
      ) : null}
      <div style={{ position: "absolute", left: ex.safe.left, width: W, top: TOP }}>
        <Headline text={s.headline} highlight={s.highlight} size={108} delay={2} />
        <div style={{ height: 24 }} />
        <Sub text={s.sub} delay={14} />
      </div>
      {s.image && s.video ? (
        // 불편 장면이 있으면 처음 2초는 장면만 — 가운데 카드가 손·물건을 가렸다(2026-10-07).
        // 그 뒤 작게 오른쪽 아래(자막 위)에 상품을 띄운다.
        <div style={{ position: "absolute", left: ex.safe.right - 220, top: 1040 - 220 }}>
          <ImageCard src={s.image} size={220} delay={60} />
        </div>
      ) : s.image ? (
        // 제목(최대 2줄)+보조 문구 아래, 자막(≈1070) 위에 들어가도록 — 첫 판에서 보조 문구를 덮었다.
        <div style={{ position: "absolute", left: ex.safe.left + (W - 310) / 2, top: TOP + 395 }}>
          <ImageCard src={s.image} size={310} delay={8} />
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

/** POINT — 번호 배지(튕김) → 기준 헤드라인 → "그래서 어떻게" 행동 카드. 뒤에 큰 번호를 옅게 깐다. */
const PointScene: React.FC<{ s: ExScene; total: number }> = ({ s, total }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const exit = useExit();
  const b = spring({ frame: frame - 2, fps, config: ex.spring.bouncy });
  const card = spring({ frame: frame - 16, fps, config: ex.spring.smooth });
  const wm = spring({ frame, fps, config: ex.spring.smooth });
  const breathe = 1 + Math.sin(frame / 20) * 0.012;
  const drift = interpolate(frame, [0, 6 * fps], [0, -30], { ...clamp, easing: ex.ease.inOut });
  const head = s.headline.replace(/^\s*\d+[.)]\s*/, "");      // 번호는 배지가 대신한다
  if (s.image) {
    // 상품 쇼츠 — 공식 사진을 화면 전체에 크게 깔고 천천히 확대(크레딧 없음). 가운데 작은 카드는 화면 절반이
    // 비어 보였다(2026-10-07). Veo 상품 컷은 편당 크레딧이 두 배라 쓰지 않는다. 보조 문구는 뺀다(자막이 같은 말을 한다).
    const kb = interpolate(frame, [0, durationInFrames], [1, 1.08], { ...clamp, easing: ex.ease.inOut });
    const pan = interpolate(frame, [0, durationInFrames], [0, -16], { ...clamp, easing: ex.ease.inOut });
    // 바로 깔리게 — 스프링으로 늦게 뜨면 앞 장면 퇴장과 겹쳐 1초쯤 까만 화면이 보였다(2026-10-07).
    const vin = interpolate(frame, [0, 4], [0, 1], clamp);
    return (
      <AbsoluteFill style={{ ...exit }}>
        <AbsoluteFill style={{ opacity: vin, }}>
          <AbsoluteFill style={{ background: "#fff" }}>
            {/* 제목 아래~자막 위까지만 사진을 둔다 — 화면 전체에 깔면 자막 상자가 상품 한가운데를 가렸다(2026-10-07). */}
            <div style={{ position: "absolute", left: 0, right: 0, top: PHOTO_TOP, height: PHOTO_BOTTOM - PHOTO_TOP }}>
              <Img src={staticFile(s.image)} style={{ width: "100%", height: "100%", objectFit: "contain",
                transform: `translateY(${pan}px) scale(${kb})` }} />
            </div>
          </AbsoluteFill>
          <AbsoluteFill style={{ background:
            "linear-gradient(180deg, rgba(0,0,0,0.85) 0%, rgba(0,0,0,0.75) 22%, rgba(0,0,0,0) 28.5%, rgba(0,0,0,0) 72%, rgba(0,0,0,0.75) 100%)" }} />
        </AbsoluteFill>
        <div style={{ position: "absolute", left: ex.safe.left, width: W, top: TOP - 20 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 18, marginBottom: 18 }}>
            <div style={{ width: 84, height: 84, borderRadius: 24, display: "flex", alignItems: "center",
              justifyContent: "center", background: ex.colors.surfaceHi, border: `2px solid ${ex.colors.line}`,
              fontFamily: ex.font, fontWeight: 900, fontSize: 52, color: ex.colors.text,
              opacity: b, transform: `scale(${interpolate(b, [0, 1], [0.4, 1]) * breathe})` }}>{s.index}</div>
            <div style={{ fontFamily: ex.font, fontWeight: 700, fontSize: 36, color: ex.colors.textDim }}>
              {s.label ?? "기준"} {s.index} / {total}</div>
          </div>
          <Headline text={head} highlight={s.highlight} size={88} delay={2} />
        </div>
      </AbsoluteFill>
    );
  }
  return (
    <AbsoluteFill style={{ ...exit }}>
      {/* 워터마크 번호 — 그래픽 층. 깊이를 주고 빈 공간을 채운다. */}
      <div style={{ position: "absolute", right: 1080 - ex.safe.right - 20, top: TOP - 120,
        fontFamily: ex.font, fontWeight: 900, fontSize: 520, lineHeight: 1, letterSpacing: "-0.06em",
        color: ex.colors.text, opacity: 0.05 * wm, transform: `translateY(${drift}px)` }}>
        {String(s.index).padStart(2, "0")}
      </div>
      <div style={{ position: "absolute", left: ex.safe.left, width: W, top: TOP }}>
        <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
          <div style={{ width: 132, height: 132, borderRadius: 36, display: "flex", alignItems: "center",
            justifyContent: "center", background: ex.colors.surfaceHi, border: `2px solid ${ex.colors.line}`,
            fontFamily: ex.font, fontWeight: 900, fontSize: 80, color: ex.colors.text,
            opacity: b, transform: `scale(${interpolate(b, [0, 1], [0.4, 1]) * breathe}) rotate(${interpolate(b, [0, 1], [-18, 0])}deg)` }}>
            {s.index}
          </div>
          <Rise delay={6} from={20}>
            <div style={{ fontFamily: ex.font, fontWeight: 700, fontSize: 42, color: ex.colors.textDim }}>
              {s.label ?? "기준"} {s.index} / {total}</div>
          </Rise>
        </div>
        {/* 상품 쇼츠 — 배지 줄 오른쪽에 상품 사진. 무엇을 파는 영상인지 장면이 바뀌어도 보이게. */}
        {s.image ? (
          <div style={{ position: "absolute", right: 0, top: -20 }}>
            <ImageCard src={s.image} size={SIDE_IMG} delay={4} zoomIn={s.index % 2 === 1} />
          </div>
        ) : null}
        <div style={{ height: s.image ? 110 : 60 }} />
        <Headline text={head} highlight={s.highlight} size={112} delay={8} />
        <div style={{ height: 70 }} />
        {s.sub ? (
          <div style={{ display: "flex", alignItems: "center", gap: 26, padding: "40px 44px",
            borderRadius: 32, background: ex.colors.surface, border: `1px solid ${ex.colors.line}`,
            borderLeft: `10px solid ${ex.colors.accent}`,
            opacity: card, transform: `translateX(${interpolate(card, [0, 1], [-80, 0])}px) scale(${interpolate(card, [0, 1], [0.96, 1])})` }}>
            <div style={{ fontFamily: ex.font, fontWeight: 900, fontSize: 64, color: ex.colors.accent }}>→</div>
            <div style={{ fontFamily: ex.font, fontWeight: 900, fontSize: 64, color: ex.colors.text,
                          letterSpacing: "-0.02em", lineHeight: 1.2, wordBreak: "keep-all" }}>{s.sub}</div>
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

/** ANSWER — 결론 카드에 조건별 선택을 보여 준다(무음이어도 답이 보여야 한다).
 *  이 장면의 히어로 색은 카드 테두리+글로 하나뿐. */
const AnswerScene: React.FC<{ s: ExScene }> = ({ s }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const exit = useExit();
  const p = spring({ frame: frame - 3, fps, config: ex.spring.smooth });
  const glow = 0.6 + Math.sin(frame / 18) * 0.15;
  const opts = s.options ?? [];
  return (
    <AbsoluteFill style={{ ...exit }}>
      <div style={{ position: "absolute", left: ex.safe.left, width: W, top: TOP }}>
        <Rise delay={0} from={20}>
          <div style={{ fontFamily: ex.font, fontWeight: 900, fontSize: 46, color: ex.colors.accent,
                        letterSpacing: "0.04em" }}>결론</div>
        </Rise>
        {s.image ? (
          <div style={{ position: "absolute", right: 0, top: -40 }}>
            <ImageCard src={s.image} size={150} delay={2} zoomIn={false} />
          </div>
        ) : null}
        <div style={{ height: s.image ? 70 : 20 }} />
        <Headline text={s.headline} size={96} delay={4} />
        <div style={{ height: 50 }} />
        <div style={{ padding: "20px 40px", borderRadius: 40, background: ex.colors.surface,
          border: `3px solid ${ex.colors.hero}`, boxShadow: `0 0 ${Math.round(70 * glow)}px ${ex.colors.hero}55`,
          opacity: p, transform: `translateY(${interpolate(p, [0, 1], [60, 0])}px) scale(${interpolate(p, [0, 1], [0.92, 1])})` }}>
          {opts.length ? opts.map((o, i) => (
            <Rise key={i} delay={12 + i * 6} from={30}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 24,
                padding: "34px 0", borderTop: i ? `1px solid ${ex.colors.line}` : "none" }}>
                <div style={{ fontFamily: ex.font, fontWeight: 700, fontSize: 46, color: ex.colors.textDim,
                              lineHeight: 1.25, wordBreak: "keep-all", flex: 1 }}>{o.if}</div>
                <div style={{ fontFamily: ex.font, fontWeight: 900, fontSize: 84, color: ex.colors.text,
                              letterSpacing: "-0.03em" }}>{o.then}</div>
              </div>
            </Rise>
          )) : (
            <div style={{ padding: "34px 0" }}><Sub text={s.sub} delay={12} /></div>
          )}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** 상품 쇼츠 CTA — 상품 사진 + 큰 번호(#12). "프로필 링크에서 번호로 찾기"가 무음으로도 보여야 한다.
 *  세로 예산: TOP(330) ~ 자막 윗선(1070). 히어로 색은 번호 알약 하나뿐. */
const ProductCta: React.FC<{ s: ExScene }> = ({ s }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pill = spring({ frame: frame - 14, fps, config: ex.spring.bouncy });
  const glow = 0.6 + Math.sin(frame / 14) * 0.2;
  const IMG = 300;
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: ex.safe.left, width: W, top: TOP - 10 }}>
        <Headline text={s.headline} size={84} delay={2} align="center" />
        <div style={{ height: 26 }} />
        <div style={{ display: "flex", justifyContent: "center" }}>
          {s.image ? <ImageCard src={s.image} size={IMG} delay={6} /> : null}
        </div>
        <div style={{ height: 30 }} />
        <div style={{ display: "flex", justifyContent: "center" }}>
          <div style={{ padding: "14px 56px", borderRadius: 999, background: ex.colors.hero,
            fontFamily: ex.font, fontWeight: 900, fontSize: 132, lineHeight: 1.05, color: "#fff",
            letterSpacing: "-0.02em", boxShadow: `0 0 ${Math.round(80 * glow)}px ${ex.colors.hero}88`,
            opacity: pill, transform: `scale(${interpolate(pill, [0, 1], [0.5, 1])})` }}>{s.code}</div>
        </div>
        {s.name ? (
          <Rise delay={20} from={20}>
            <div style={{ marginTop: 18, textAlign: "center", fontFamily: ex.font, fontWeight: 700,
                          fontSize: 40, color: ex.colors.textDim, wordBreak: "keep-all" }}>{s.name}</div>
          </Rise>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};

/** CTA — 조용하게. 프로필 링크로 안내(쇼츠 설명란 링크는 클릭 불가). */
const CtaScene: React.FC<{ s: ExScene }> = ({ s }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const a = spring({ frame: frame - 16, fps, config: ex.spring.smooth });
  const nudge = Math.sin(frame / 8) * 6;
  if (s.code) return <ProductCta s={s} />;
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: ex.safe.left, width: W, top: TOP + 160 }}>
        <Headline text={s.headline} size={100} delay={2} align="center" />
        <div style={{ height: 30 }} />
        <div style={{ display: "flex", justifyContent: "center" }}><Sub text={s.sub} delay={10} /></div>
        <div style={{ height: 80 }} />
        <div style={{ display: "flex", justifyContent: "center", opacity: a,
                      transform: `translateY(${interpolate(a, [0, 1], [30, 0]) + nudge}px)` }}>
          <div style={{ padding: "28px 52px", borderRadius: 999, background: ex.colors.hero,
            fontFamily: ex.font, fontWeight: 900, fontSize: 48, color: "#fff",
            boxShadow: `0 0 60px ${ex.colors.hero}66` }}>DSPORTAL 프로필 링크 ↑</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

/** 장면 전환 효과음 — 화면보다 조금 먼저. */
const Sfx: React.FC<{ scenes: ExScene[]; fps: number }> = ({ scenes, fps }) => {
  const lead = Math.round(ex.sec.sfxLead * fps);
  return (
    <>
      {scenes.map((s, i) => {
        const at = Math.max(0, Math.round(s.start * fps) - lead);
        return (
          <React.Fragment key={i}>
            {i > 0 ? <Sequence from={at} durationInFrames={Math.round(0.5 * fps)}>
              <Audio src={staticFile("sfx/whoosh.wav")} volume={0.35} /></Sequence> : null}
            <Sequence from={at + Math.round(0.12 * fps)} durationInFrames={Math.round(0.3 * fps)}>
              <Audio src={staticFile(s.type === "point" ? "sfx/tick.wav" : "sfx/pop.wav")} volume={0.45} />
            </Sequence>
            {s.type === "answer" ? <Sequence from={at + Math.round(0.1 * fps)} durationInFrames={Math.round(0.8 * fps)}>
              <Audio src={staticFile("sfx/hit.wav")} volume={0.55} /></Sequence> : null}
          </React.Fragment>
        );
      })}
    </>
  );
};

export const Explainer: React.FC<{ manifest: ExManifest }> = ({ manifest }) => {
  const { fps } = useVideoConfig();
  const f = (sec: number) => Math.round(sec * fps);
  const points = manifest.scenes.filter((s) => s.type === "point").length;
  const hero = manifest.scenes.find((s) => s.image)?.image;
  return (
    <AbsoluteFill style={{ backgroundColor: ex.colors.bg }}>
      <Backdrop image={hero} />
      {manifest.scenes.map((s, i) => (
        <Sequence key={i} from={f(s.start)} durationInFrames={Math.max(1, f(s.duration))}>
          {s.type === "hook" ? <HookScene s={s} />
            : s.type === "point" ? <PointScene s={s} total={points} />
            : s.type === "answer" ? <AnswerScene s={s} />
            : <CtaScene s={s} />}
        </Sequence>
      ))}
      <TopBar scenes={manifest.scenes} fps={fps} disclosure={manifest.disclosure} />
      <Captions cues={manifest.cues} fps={fps} />
      <Finish />
      <Audio src={staticFile(manifest.audio)} />
      <Sfx scenes={manifest.scenes} fps={fps} />
    </AbsoluteFill>
  );
};

export const exDuration = (m: ExManifest) => Math.round(m.totalDuration * m.fps);
