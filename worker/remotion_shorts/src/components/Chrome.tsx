// 고정 레이어 — 타이틀 블록과 자막 바. 전환에 밀리면 안 되므로 씬 위에 항상 얹는다.
import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import type { Manifest } from "../manifest";

/** 제목 — **처음 3.5초만 보여주고 사라진다.**
 *
 *  예전에는 영상 내내 y=296~499 를 차지했다. 세로의 10%를, 시청자가 이미 아는
 *  정보에 35초 동안 쓰고 있었던 셈이다. 쇼츠는 세로 전체가 무기인데 그럴 여유가 없다.
 *
 *  훅 구간에는 필요하다 — 스크롤하다 멈춘 사람이 "무슨 영상인지"를 0.5초 안에
 *  알아야 하기 때문이다. 그 역할이 끝나면 자리를 비운다. */
const TITLE_OUT_SEC = 3.5;
const TITLE_FADE_SEC = 0.5;

export const TitleBlock: React.FC<{ sub: string; main: string }> = ({ sub, main }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!main) return null;
  const s = spring({ frame, fps, config: theme.spring.smooth });
  const y = interpolate(s, [0, 1], [-28, 0]);
  // 등장은 스프링, 퇴장은 선형 페이드 — 나가는 요소가 튀면 시선을 뺏는다.
  const out = interpolate(
    frame,
    [(TITLE_OUT_SEC - TITLE_FADE_SEC) * fps, TITLE_OUT_SEC * fps],
    [1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  if (out <= 0) return null;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div style={{ position: "absolute", top: 100, left: 0, right: 0,
        display: "flex", flexDirection: "column", alignItems: "center", gap: 4,
        opacity: s * out, transform: `translateY(${y}px)`, fontFamily: theme.font }}>
        {sub ? (
          <div style={{ fontSize: 34, fontWeight: 800, color: theme.colors.primary,
            letterSpacing: 1, textShadow: "0 2px 10px rgba(0,0,0,0.8)" }}>{sub}</div>
        ) : null}
        <div style={{ fontSize: 58, fontWeight: 800, color: theme.colors.text,
          textShadow: "0 3px 16px rgba(0,0,0,0.85)" }}>{main}</div>
      </div>
    </AbsoluteFill>
  );
};

/** 자막 — 가로 풀사이즈 고정 바. 글자만 바뀌고 바는 절대 움직이지 않는다.
 *
 *  **세이프존 하단(1248)에 붙인다.** 그 아래(1248~1920)는 유튜브 UI가 덮는
 *  데드존이라 글자를 두면 가려진다.
 *
 *  한때 얼굴을 피하려고 858로 올렸는데, 그러면 자막이 카드와 얼굴 사이를 먹어서
 *  상품 카드를 320까지 줄여야 했고 "상품이 안 보인다"는 문제가 생겼다.
 *  지금은 자막을 원래 자리로 되돌리고, **캐릭터 쪽을 내려서** 얼굴이 자막 위에
 *  오도록 맞춘다(CharacterScene의 CHAR_SCALE/CHAR_SHIFT 참고).
 *  자막이 로봇의 몸통을 지나가는 건 괜찮다 — 가리면 안 되는 건 얼굴이다. */
// 자막 바 상단 y. 카드 하단(830)과 캐릭터 머리(약 1007) 사이.
// 타이틀(296~499) 바로 아래. 원래는 세이프존 하단(1148)에 뒀는데, 자막 바가
// 화면 가운데를 가로지르면서 **캐릭터의 팔 동작을 잘랐다** — 얼굴만 피해서 될
// 문제가 아니었다(실측 비교 2026-09-03: 양팔 벌린 동작이 바에 끊김).
// 위로 올리면 글자가 상단에 한 덩어리로 모이고, 아래쪽 넓은 공간을 캐릭터와
// 상품 카드가 온전히 쓴다.
// 자막 바 상단 y. **카드 아래, 말풍선 위**다.
//   카드 280~720 → 자막 740~836 → 말풍선 ~874~980 → 얼굴 1020~1280
// 처음엔 810 에 뒀는데 말풍선(866~946)과 겹쳐 둘 다 안 읽혔다.
// 몸통을 지나가는 건 괜찮다 — 가리면 안 되는 건 눈과 말풍선이다.
export const CAPTION_TOP = 740;

/** 컷 모드 자막 — 화면 가득한 이미지 위에 얹는 **큰 글씨**.
 *
 *  조회수 상위 쿠팡 쇼츠(살림남 142만·82만)를 실제로 열어보면 자막이 둘이다.
 *  위에 작은 원문 자막, 가운데에 큰 굵은 핵심 문구. 우리는 큰 쪽만 쓴다 —
 *  원문 자막은 유튜브 자동자막이 대신한다.
 *
 *  왜 바가 아니라 글자 뒤에만 깔리나 — 컷이 화면을 꽉 채우므로 가로 전체를 덮는
 *  띠를 그으면 그만큼 이미지가 죽는다. 글자 폭만큼만 가린다.
 *
 *  **살림남과 우리는 조건이 다르다.** 그쪽 화면은 손과 상품뿐이라 가운데 위쪽에
 *  큰 자막을 놓을 자리가 비어 있다. 우리 컷은 상세페이지에서 잘라온 것이라
 *  이미 큰 글씨를 품고 있다. 처음에 430에 76px로 놓았더니 컷의 헤드라인과
 *  정면으로 겹쳐 둘 다 안 읽혔다(실측 렌더 2026-09-11: 6프레임 중 3프레임 충돌).
 *
 *  그래서 **주인공을 컷의 문구에 넘기고** 자막은 아래로 내려 읽기 보조로 둔다.
 *  판매자가 쓴 "1초 만에 단단해지는 응고력" 이 우리가 만든 자막보다 세다.
 *  1090은 세이프존 하단(1248) 위이고, 상세 컷의 헤드라인은 대개 상단·중단에 있다. */
export const BIG_CAPTION_TOP = 1090;

export const BigCaption: React.FC<{ cues: Manifest["cues"]; fps: number }> = ({ cues, fps }) => {
  const frame = useCurrentFrame();
  const t = frame / fps;
  const idx = cues.findIndex((c) => t >= c.start && t < c.end);
  if (idx < 0) return null;
  const cue = cues[idx];
  // 큐가 바뀔 때마다 스프링을 튀기면 1초마다 들썩인다. 짧게 나타나기만 한다.
  const since = (t - cue.start) * fps;
  const pop = interpolate(since, [0, 5], [0.94, 1],
    { easing: theme.ease.out, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const fade = interpolate(since, [0, 4], [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div style={{ position: "absolute", top: BIG_CAPTION_TOP, left: 0, width: "100%",
        display: "flex", justifyContent: "center",
        opacity: fade, transform: `scale(${pop})` }}>
        <span style={{ fontFamily: theme.font, fontSize: 56, fontWeight: 800,
          color: theme.colors.text, lineHeight: 1.25, textAlign: "center",
          background: "rgba(0,0,0,0.74)", padding: "12px 30px", borderRadius: 16,
          maxWidth: 940, whiteSpace: "nowrap",
          textShadow: "0 4px 18px rgba(0,0,0,0.9)" }}>
          {cue.line}
        </span>
      </div>
    </AbsoluteFill>
  );
};

export const CaptionBar: React.FC<{ cues: Manifest["cues"]; fps: number }> = ({ cues, fps }) => {
  const frame = useCurrentFrame();
  const t = frame / fps;
  const active = cues.find((c) => t >= c.start && t < c.end);
  const barTop = CAPTION_TOP;
  return (
    <AbsoluteFill style={{ pointerEvents: "none" }}>
      <div style={{ position: "absolute", top: barTop, left: 0, width: "100%", height: 96,
        background: "rgba(0,0,0,0.72)", display: "flex",
        alignItems: "center", justifyContent: "center" }}>
        <span style={{ fontFamily: theme.font, fontSize: 46, fontWeight: 700,
          color: theme.colors.text, maxWidth: 696, textAlign: "center",
          whiteSpace: "nowrap", overflow: "hidden" }}>
          {active ? active.line : ""}
        </span>
      </div>
    </AbsoluteFill>
  );
};
