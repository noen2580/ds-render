// B안 — 영상 전체를 Remotion으로 만든다.
// 세그먼트를 Sequence로 깔고, 소재가 사진이면 ProductScene, 실사면 Footage.
// 타이틀·자막은 전 구간 위에 고정 레이어로 얹는다.
import React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile,
         useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "./theme";
import { BgMesh, Grade, Grain, Vignette } from "./components/Layers";
import { Footage } from "./components/Motion";
import { BigCaption, CaptionBar, TitleBlock } from "./components/Chrome";
import { SpeechBubbleTrack } from "./components/Bubble";
import { XFADE } from "./scenes/CharacterScene";
import { CutScene } from "./scenes/CutScene";
import { ProductScene } from "./scenes/ProductScene";
import { CharacterScene } from "./scenes/CharacterScene";
import type { Manifest } from "./manifest";

/** 실사 구간. 들어올 때 살짝 확대되며 페이드 — 컷이 뚝 끊기지 않게. */
const FootageScene: React.FC<{ src: string }> = ({ src }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const inO = interpolate(frame, [0, XFADE], [0, 1],
    { easing: theme.ease.out, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const scale = interpolate(frame, [0, durationInFrames], [1.04, 1],
    { easing: theme.ease.inOut, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ opacity: inO }}>
      <AbsoluteFill style={{ transform: `scale(${scale})` }}>
        <Footage src={src} />
      </AbsoluteFill>
      <Grade />
      <Grain />
      <Vignette />
    </AbsoluteFill>
  );
};


/** 컷을 타임라인에 배치한다.
 *
 *  세그먼트(내레이션 문단)에 하나씩 맞추면 안 된다 — 7문단 35초면 컷 하나가
 *  5초씩 머물러서 정지 화면처럼 보인다. 목표는 2.8초다.
 *
 *  경계는 **자막 큐 시작에 맞춘다.** 말이 끊기는 지점에서 화면이 바뀌어야
 *  리듬이 산다. 아무 데서나 바뀌면 말 중간에 컷이 튄다. */
function planCuts(cuts: { file: string }[], cues: Manifest["cues"], total: number) {
  const TARGET = 2.8;
  const n = Math.max(4, Math.min(cuts.length, Math.round(total / TARGET)));
  const bounds: number[] = [0];
  for (let i = 1; i < n; i++) {
    const want = (total * i) / n;
    let best = want, bd = Infinity;
    for (const c of cues) {
      const d = Math.abs(c.start - want);
      if (d < bd) { bd = d; best = c.start; }
    }
    // 1.2초보다 짧은 컷은 만들지 않는다 — 눈이 따라가지 못한다.
    if (best > bounds[bounds.length - 1] + 1.2) bounds.push(best);
  }
  bounds.push(total);
  return bounds.slice(0, -1).map((start, i) => ({
    start,
    duration: bounds[i + 1] - start,
    image: cuts[i % cuts.length].file,
  }));
}

export const Full: React.FC<{ manifest: Manifest; dir: string }> = ({ manifest, dir }) => {
  const { fps } = useVideoConfig();
  const f = (sec: number) => Math.round(sec * fps);

  // 컷이 넉넉할 때만 컷 모드로 간다. 상세페이지가 부실한 상품(실측 최소 17컷이었지만
  // 카테고리에 따라 더 적을 수 있다)은 기존 상품 카드 구조로 폴백한다.
  const cuts = manifest.cuts ?? [];
  if (cuts.length >= 8) {
    const plan = planCuts(cuts, manifest.cues, manifest.totalDuration);
    return (
      <AbsoluteFill style={{ backgroundColor: theme.colors.bg }}>
        {plan.map((p, i) => (
          <Sequence key={`c${i}`} from={f(p.start)}
                    durationInFrames={f(p.duration) + XFADE}>
            <CutScene image={`${dir}/${p.image}`} zoomIn={i % 2 === 0} />
          </Sequence>
        ))}
        <TitleBlock sub={manifest.titleSub} main={manifest.titleMain} />
        <BigCaption cues={manifest.cues} fps={fps} />
        <Audio src={staticFile(`${dir}/${manifest.audio}`)} />
      </AbsoluteFill>
    );
  }

  return (
    <AbsoluteFill style={{ backgroundColor: theme.colors.bg }}>
      <BgMesh />
      {manifest.segments.map((s) => (
        <Sequence key={s.index} from={f(s.start)} durationInFrames={f(s.duration) + XFADE}>
          {s.character
            ? <CharacterScene
                clip={`character/${s.character}`}
                clipDuration={f(8)}
                image={s.showProduct ? `${dir}/${s.productImage}` : undefined}
                revealAt={f(0.6)} />
            : s.isVideo
              ? <FootageScene src={`${dir}/${s.source}`} />
              : <ProductScene image={`${dir}/${s.source}`} name={manifest.heroName} />}
        </Sequence>
      ))}
      <TitleBlock sub={manifest.titleSub} main={manifest.titleMain} />
      {/* 자막은 검은 바가 아니라 **캐릭터 머리 위 말풍선**으로 나간다.
          캐릭터 구간이 아닌 세그먼트(실사·상품 단독)에서는 머리가 없으므로
          기존 자막 바로 되돌아간다. */}
      {manifest.segments.some((s) => s.character)
        ? <SpeechBubbleTrack segments={manifest.segments} cues={manifest.cues}
                             clipDuration={f(8)} />
        : null}
      {manifest.segments.every((s) => s.character) ? null
        : <CaptionBar cues={manifest.cues} fps={fps} />}
      <Audio src={staticFile(`${dir}/${manifest.audio}`)} />
    </AbsoluteFill>
  );
};
