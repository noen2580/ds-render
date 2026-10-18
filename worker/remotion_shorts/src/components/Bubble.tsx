// 캐릭터 머리 위 **대사 말풍선**. 자막이 여기로 들어온다.
//
// 왜 이렇게 바꿨나 — 그전에는 자막이 화면을 가로지르는 검은 띠였고, 캐릭터는
// 그 아래에서 따로 움직였다. 말하는 주체가 없으니 캐릭터가 장식으로만 보였다.
// 자막을 머리 위로 올리면 **로봇이 말하는 것**이 되고, 띠가 사라지면서 세로도 트인다.
//
// 가능한 이유는 자막이 이미 짧기 때문이다. 실측(36큐/35초): 평균 6.2자, 최대 8자.
// 한 마디씩 끊어지는 형태라 말풍선에 그대로 들어간다.
//
// 상품명 전용 말풍선은 두지 않는다. 내레이션이 이미 말하기 때문이다 —
// "제가 고른 건 / 이거예요. 펫 / 리서치 응고형 / 벤토나이트 / 고양이 모래."
//
// 위치는 `public/character/tracks.json` 에서 온다. 클립이 고정 재사용이라
// 프레임별 머리 좌표를 미리 구워뒀다(tools/youtube_shorts/track_character.py).
import React from "react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { CHAR_SCALE, CHAR_SHIFT, XFADE, clipStartFrom } from "../scenes/CharacterScene";
import type { Cue, Segment } from "../manifest";
import tracks from "../../public/character/tracks.json";

type Point = { body: number[]; head: number[]; visor: number[] };
type Track = { fps: number; points: Point[] };

/** 클립 이름(`character/xxx.mp4` 또는 `xxx`)으로 프레임별 머리 위치를 찾는다.
 *  `frame` 은 **클립 안에서의 프레임**이다(세그먼트 프레임이 아니다). */
export function headAt(clip: string, frame: number, fps: number) {
  const key = clip.replace(/^character\//, "").replace(/\.mp4$/, "");
  const t = (tracks as Record<string, Track>)[key];
  if (!t || !t.points.length) return null;
  // 추적은 12fps 로 떴고 렌더는 다른 fps 일 수 있다. 시간으로 환산해 맞춘다.
  const i = Math.min(t.points.length - 1,
                     Math.max(0, Math.round((frame / fps) * t.fps)));
  const p = t.points[i];
  return {
    cx: (p.head[0] + p.head[2]) / 2,   // 0~1
    top: p.head[1],                     // 0~1
  };
}

/** 말풍선 트랙 — 전 구간에 **하나만** 깐다.
 *
 *  왜 세그먼트마다 깔지 않는가(2026-09-11 수정) — 세그먼트 Sequence 는 크로스페이드
 *  때문에 `duration + XFADE` 로 겹쳐 놓는다. 그 겹치는 0.5초 동안 앞뒤 세그먼트의
 *  말풍선이 **동시에** 그려졌고, 각자 자기 클립의 머리를 따라가니 위치가 달라
 *  두 개가 화면에서 겹쳐 보였다("중간중간 말풍선이 겹치는 증상").
 *  영상은 겹쳐야 부드럽지만 글자는 겹치면 안 읽힌다. 그래서 이 레이어는 세그먼트
 *  바깥에 두고, 지금 시각의 세그먼트 하나만 골라 말풍선 하나를 그린다. */
export const SpeechBubbleTrack: React.FC<{
  segments: Segment[];
  cues: Cue[];
  clipDuration: number;   // 캐릭터 클립 길이(프레임)
}> = ({ segments, cues, clipDuration }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  const t = frame / fps;

  const cue = cues.find((c) => t >= c.start && t < c.end);
  if (!cue) return null;

  const seg = segments.find((s) => t >= s.start && t < s.start + s.duration);
  if (!seg || !seg.character) return null;

  // 화면에 **지금 보이는** 클립 프레임을 되짚는다. CharacterScene 은 클립 가운데를
  // 쓰려고 startFrom 만큼 건너뛰고, 모자라면 Loop 로 되감는다. 그 계산을 그대로
  // 따라가지 않으면 말풍선이 몇 초 전 머리 위치를 따라다닌다.
  const segFrame = frame - Math.round(seg.start * fps);
  const segFrames = Math.round(seg.duration * fps) + XFADE;
  const startFrom = clipStartFrom(clipDuration, segFrames);
  const loopLen = Math.max(clipDuration - startFrom, 1);
  const clipFrame = startFrom + (segFrame % loopLen);

  const h = headAt(`character/${seg.character}`, clipFrame, fps);
  if (!h) return null;

  // 클립 좌표(0~1) → 캔버스 좌표. CharacterScene 이 transformOrigin "top center" 로
  // scale 후 translateY 하므로 같은 순서로 환산한다.
  const cx = width / 2 + (h.cx - 0.5) * width * CHAR_SCALE;
  const headTop = h.top * height * CHAR_SCALE + CHAR_SHIFT;

  // 큐가 바뀔 때마다 스프링을 새로 튀기면 1초마다 들썩여서 눈이 피로하다.
  // 등장은 짧게 튀고(첫 6프레임), 그 뒤로는 가만히 둔다.
  const since = (t - cue.start) * fps;
  const pop = interpolate(since, [0, 6], [0.88, 1],
    { easing: theme.ease.out, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const fade = interpolate(since, [0, 4], [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  const GAP = 26;   // 머리 꼭대기와 말풍선 사이

  return (
    <div style={{
      position: "absolute", left: cx, top: headTop - GAP,
      transform: `translate(-50%, -100%) scale(${pop})`,
      transformOrigin: "bottom center",
      opacity: fade,
      pointerEvents: "none",
    }}>
      <div style={{
        position: "relative",
        background: "#FFFFFF",
        color: "#141414",
        fontFamily: theme.font, fontSize: 52, fontWeight: 800,
        padding: "20px 34px", borderRadius: 34,
        maxWidth: 820, textAlign: "center", whiteSpace: "nowrap",
        boxShadow: "0 20px 50px -14px rgba(0,0,0,0.8)",
      }}>
        {cue.line}
        {/* 꼬리 — 말풍선 아래 가운데에서 머리를 향해 내려간다. */}
        <div style={{
          position: "absolute", left: "50%", bottom: -17,
          width: 0, height: 0, transform: "translateX(-50%)",
          borderLeft: "17px solid transparent",
          borderRight: "17px solid transparent",
          borderTop: "19px solid #FFFFFF",
        }} />
      </div>
    </div>
  );
};
