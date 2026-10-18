// 컴포지션 정의. **매니페스트를 하드코딩으로 import 하지 않는다.**
//
// 예전에는 `import manifest from "../public/post_566/manifest.json"` 이었는데,
// 렌더할 글을 바꿀 때마다 소스를 고쳐야 했고 실제로 사고가 났다 — 캐릭터 모드로
// post_536 에셋을 새로 뽑아놓고 post_566을 렌더해서, 길이가 안 맞는 걸 보고서야
// 알아챘다(2026-09-03). 자동화하려면 글 번호가 런타임에 들어와야 한다.
//
// 지금은 `--props=props.json` 으로 매니페스트를 통째로 주입받고, 영상 길이·해상도는
// calculateMetadata가 그 매니페스트에서 계산한다. 렌더 커맨드는 글이 바뀌어도 같다.
import React from "react";
import { Composition } from "remotion";
import { Full } from "./Full";
import { CharacterScene } from "./scenes/CharacterScene";
import { Thumbnail } from "./scenes/Thumbnail";
import fallback from "../public/post_536/manifest.json";
import type { Manifest } from "./manifest";
import { Explainer, exDuration } from "./explainer/Explainer";
import type { ExManifest } from "./explainer/types";

// Explainer 는 매니페스트 없이 열면 이 최소 예시로 뜬다(스튜디오 확인용).
const EX_FALLBACK: ExManifest = {
  kind: "explainer", postId: 0, fps: 30, width: 1080, height: 1920, totalDuration: 6,
  audio: "sfx/hit.wav", category: "SSD",
  scenes: [
    { type: "hook", index: 0, start: 0, duration: 3, headline: "SSD, 뭘 살지 고민인가요?", sub: "NVMe vs SATA", highlight: "SSD" },
    { type: "point", index: 1, start: 3, duration: 3, headline: "M.2 단자 확인", sub: "없으면 NVMe 불가", highlight: "M.2" },
  ],
  cues: [{ text: "SSD 종류가 너무 많죠?", start: 0.2, end: 2.8 }],
};

const FALLBACK = fallback as unknown as Manifest;

type FullProps = { manifest: Manifest; dir: string };

export const RemotionRoot: React.FC = () => (
  <>
    <Composition
      id="Full"
      component={Full}
      // props가 없을 때만 쓰이는 값 — 실제 렌더는 calculateMetadata가 덮어쓴다.
      durationInFrames={Math.round(FALLBACK.totalDuration * FALLBACK.fps)}
      fps={FALLBACK.fps}
      width={FALLBACK.width}
      height={FALLBACK.height}
      defaultProps={{ manifest: FALLBACK, dir: `post_${FALLBACK.postId}` } as FullProps}
      calculateMetadata={({ props }) => {
        const m = (props as FullProps).manifest ?? FALLBACK;
        return {
          durationInFrames: Math.round(m.totalDuration * m.fps),
          fps: m.fps,
          width: m.width,
          height: m.height,
        };
      }}
    />

    {/* 정보 전달형 쇼츠 — `--props=<manifest를 {manifest: ...} 로 감싼 json>` */}
    <Composition
      id="Explainer"
      component={Explainer}
      durationInFrames={exDuration(EX_FALLBACK)}
      fps={EX_FALLBACK.fps}
      width={EX_FALLBACK.width}
      height={EX_FALLBACK.height}
      defaultProps={{ manifest: EX_FALLBACK }}
      calculateMetadata={({ props }) => {
        const m = (props as { manifest: ExManifest }).manifest ?? EX_FALLBACK;
        return { durationInFrames: exDuration(m), fps: m.fps, width: m.width, height: m.height };
      }}
    />

    {/* 썸네일 — `npx remotion still src/index.ts Thumbnail out.png --props=...` */}
    <Composition
      id="Thumbnail"
      component={Thumbnail}
      durationInFrames={1}
      fps={1}
      width={1080}
      height={1920}
      defaultProps={{ badge: "2026 TOP 5", main: "폼롤러", sub: "고를 때 뭘 보나",
                      image: `post_${FALLBACK.postId}/product_0.jpg` }}
    />

    {/* 캐릭터 클립 단독 확인용 — 레이아웃을 조정할 때 8초만 빠르게 뽑아본다. */}
    <Composition
      id="Character"
      component={CharacterScene}
      durationInFrames={8 * 25}
      fps={25}
      width={1080}
      height={1920}
      defaultProps={{
        clip: "character/reveal_present_1.mp4",
        clipDuration: 200,
        image: `post_${FALLBACK.postId}/product_0.jpg`,
        revealAt: 15,
      }}
    />
  </>
);
