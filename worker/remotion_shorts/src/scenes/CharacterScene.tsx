// 캐릭터 클립 위에 **실제 상품 사진**을 효과와 함께 얹는 씬.
//
// 역할 분담이 이 구조의 전부다:
//   캐릭터(생성 영상) = 상황과 감정을 연기한다. 사람이 아니어도 된다.
//   상품(쿠팡 실사진)  = 무엇을 사는지 정확히 보여준다. 반드시 실사여야 한다.
// 생성 영상에 상품을 "그리게" 하면 안 된다 — 화면의 물건과 구매 링크의 물건이
// 달라지고, 그건 우리가 1688 소재를 버린 이유와 같은 문제다.
//
// 왜 카드가 캐릭터를 덮지 않고 위쪽에 뜨는가 — 캐릭터를 계속 보여줘야 채널 정체성이
// 쌓인다. 카드가 화면 중앙을 가리면 캐릭터는 사실상 배경이 된다.
import React from "react";
import { AbsoluteFill, Img, Loop, OffthreadVideo, interpolate, spring,
         staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { theme } from "../theme";
import { Grade, Grain, Vignette } from "../components/Layers";
import { useBreath } from "../components/Motion";

// 카드는 **타이틀 블록 아래**에서 시작해야 한다. 세이프존 상단(288)만 보고 350에
// 뒀더니 타이틀과 143px 겹쳤다 — 실측(2026-09-03 렌더): 타이틀이 y=306~499까지
// 내려오는데 카드가 y=356에서 시작했다. 화면에서 제목 글자가 상품 사진 위에 얹혔다.
// 자막을 세이프존 하단으로 되돌리면서 생긴 공간을 카드에 준다.
// 320은 "영상에서 상품이 뭔지 알아보기 어렵다"는 지적을 받았다. 420이면 화면
// 가로의 39%라 폼롤러처럼 세로로 긴 물건도 형태가 읽힌다.
const CARD = 440;
const CARD_TOP = 280;          // 제목이 3.5초 뒤 비우는 자리 → 카드 하단 720

// 캐릭터 클립을 **아래를 기준으로 축소**해 상단을 비운다.
//
// 실측 이유 — 첫 생성 클립(미리캔버스)에서 로봇이 화면 세로 30~83% 구간을 차지했다.
// 1080x1920으로 환산하면 머리 꼭대기가 y=579라 카드(350~810)와 **211px 겹쳤다**.
// 프롬프트에 "lower 60%"를 넣었지만 생성기가 인물을 가운데 두는 성향이 강해서,
// 프롬프트만으로는 통제가 안 된다. 합성 쪽에서 확실히 잡는 편이 재생성보다 싸다.
//
// 0.8배로 줄이면 머리 꼭대기가 y=847로 내려가 카드 아래에 안전하게 들어간다.
// 아래를 기준(transform-origin: bottom)으로 줄이므로 캐릭터가 공중에 뜨지 않는다.
// 캐릭터를 **아래 기준 축소**가 아니라 **위 기준 축소 + 아래로 이동**으로 바꿨다.
//
// 아래를 기준으로 줄이면 크기와 위치를 따로 못 정한다 — 작게 만들수록 얼굴이
// 내려가서, 카드와 자막 사이의 좁은 창에 얼굴을 맞출 수가 없었다.
//
// 원본 클립에서 캐릭터는 y 615~1613, 바이저(얼굴)는 대략 675~935를 차지한다.
// 변환 후 좌표는 `Y * s + shift` 이므로, 얼굴이 카드 하단(930)과 자막 상단(1148)
// 사이에 오도록 풀면:
//   675 * 0.66 + 504 = 950   (얼굴 위)
//   935 * 0.66 + 504 = 1121  (얼굴 아래, 자막 1148 위)
// 몸통은 자막 아래로 계속 이어진다 — 가리면 안 되는 건 얼굴이지 몸이 아니다.
// 자막이 위로 올라가면서 캐릭터는 카드 아래로 내려간다.
//
// 원본에서 캐릭터 상단 615, 바이저(눈) 675~935. 변환 좌표는 `Y * s + shift`.
// 로봇이 위아래로 61px 떠다니므로 **가장 높이 떴을 때**를 기준으로 잡는다:
//   (675 - 61) * 0.62 + 690 = 1071  ≥ 카드 하단(1070)
// 즉 최악의 프레임에서도 눈이 카드 아래에 있다. 이마가 카드에 살짝 가리는 건
// 괜찮다 — 로봇이 카드를 들어올린 것처럼 읽힌다. 가리면 안 되는 건 눈이다.
// 2026-09-11 재배치 — **축소를 걷어냈다.**
//
// 0.62배는 카드와 자막을 피하려고 캐릭터를 계속 밀어낸 결과였는데, 클립이
// 1080x1920 9:16 이라 축소하면 좌우에 205px 씩 검은 띠가 생긴다. 클립 자체 배경의
// 테두리까지 그대로 보여서 **화면 안에 작은 화면이 하나 더 있는** 꼴이었다.
// 실사용 지적("무언가 부족한 느낌")의 가장 큰 원인이 이것이다.
//
// scale 1.0 이면 가로를 꽉 채워 띠가 사라진다. 대신 카드를 위(290)로 올리고
// 자막을 그 아래(810)로 내려서 얼굴 자리를 비웠다.
//   얼굴 = 원본 바이저(675~935) + shift
//   672 + 348 = 1020  말풍선 아래 ✓
//   941 + 348 = 1289
// 머리 꼭대기(1020) 위 ~140px 이 말풍선 자리다. 자막을 740~836 으로 올려
// 그 띠를 비웠다 — 처음엔 자막이 810~906 이라 말풍선과 정면으로 겹쳤다.
export const CHAR_SCALE = 1.0;
export const CHAR_SHIFT = 348;

/** 세그먼트 경계에서 겹치는 프레임 수(약 0.5초). 영상은 이만큼 크로스페이드된다. */
export const XFADE = 12;

/** 클립의 어느 프레임부터 쓸지. 말풍선도 같은 값을 써야 머리를 제대로 따라간다. */
export function clipStartFrom(clipDuration: number, segmentFrames: number) {
  return Math.max(0, Math.floor((clipDuration - segmentFrames) / 2));
}

/** 카드가 들어올 때 한 번 퍼지는 링 — "여기 주목"의 시각 신호. */
const Pop: React.FC<{ at: number }> = ({ at }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [at, at + 26], [0, 1],
    { easing: theme.ease.out, extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  if (p <= 0 || p >= 1) return null;
  const d = interpolate(p, [0, 1], [CARD * 0.7, CARD * 1.9]);
  return (
    <div style={{
      position: "absolute", left: 540 - d / 2, top: CARD_TOP + CARD / 2 - d / 2,
      width: d, height: d, borderRadius: "50%",
      border: `6px solid ${theme.colors.primary}`,
      opacity: interpolate(p, [0, 0.3, 1], [0, 0.7, 0]),
    }} />
  );
};

export const CharacterScene: React.FC<{
  clip: string;          // 캐릭터 생성 영상 (9:16)
  clipDuration: number;  // 그 클립의 길이(프레임). 세그먼트보다 짧으면 루프한다.
  image?: string;        // 쿠팡 상품 사진 — 없으면 카드 없이 캐릭터만
  revealAt?: number;     // 카드가 들어오는 프레임
}> = ({ clip, clipDuration, image, revealAt = 40 }) => {
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();

  // **클립의 가운데 구간을 쓴다.** 클립은 8~40초인데 세그먼트는 2~10초라, 앞에서부터
  // 자르면 동작이 시작만 하고 끝나기 전에 넘어간다(실사용 지적). 생성 클립은 대개
  // 앞뒤가 중립 자세이고 가운데에서 동작이 완성되므로, 남는 길이의 절반을 건너뛰어
  // 절정이 이 구간 안에 들어오게 한다.
  const startFrom = clipStartFrom(clipDuration, durationInFrames);
  const breath = useBreath();
  const card = image
    ? spring({ frame: frame - revealAt, fps, config: theme.spring.bouncy })
    : 0;

  return (
    <AbsoluteFill style={{ backgroundColor: theme.colors.bg }}>
      {/* 캐릭터 — 생성 클립은 3초 안팎이고 세그먼트는 그보다 길 수 있어 Loop로 감싼다.
          반드시 OffthreadVideo를 쓴다(일반 video 태그는 렌더 중 프레임을 놓친다). */}
      <AbsoluteFill style={{
        transform: `translateY(${CHAR_SHIFT}px) scale(${CHAR_SCALE})`,
        transformOrigin: "top center",
      }}>
        <Loop durationInFrames={Math.max(clipDuration - startFrom, 1)}>
          <OffthreadVideo src={staticFile(clip)} muted startFrom={startFrom}
            style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </Loop>
      </AbsoluteFill>

      {/* 카드가 뜨는 순간 위쪽을 살짝 눌러 시선을 넘긴다. 컷 없이 주목을 옮기는
          가장 싼 방법이다. */}
      {image && (
        <AbsoluteFill style={{
          background: `linear-gradient(180deg, rgba(0,0,0,${0.5 * card}) 0%, `
                    + `rgba(0,0,0,${0.12 * card}) 44%, transparent 64%)`,
        }} />
      )}

      {image && (
        <AbsoluteFill style={{ alignItems: "center" }}>
          <Pop at={revealAt} />
          <div style={{
            position: "absolute", top: CARD_TOP, width: CARD, height: CARD,
            borderRadius: 28, overflow: "hidden", background: "#fff",
            border: `3px solid ${theme.colors.primary}`,
            boxShadow: `0 30px 70px -18px rgba(0,0,0,0.7), 0 0 60px ${theme.colors.glow}`,
            opacity: card,
            // 등장은 투명도 + 상승 + 확대를 함께 — 단독 페이드는 눈에 안 띈다.
            transform: `scale(${interpolate(card, [0, 1], [0.72, 1]) * breath}) `
                     + `translateY(${interpolate(card, [0, 1], [70, 0])}px)`,
          }}>
            <Img src={staticFile(image)}
                 style={{ width: "100%", height: "100%", objectFit: "contain" }} />
          </div>
        </AbsoluteFill>
      )}

      <Grade />
      <Grain />
      <Vignette />
    </AbsoluteFill>
  );
};
