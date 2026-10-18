"""
발행글의 JSON-LD 상품 데이터로 유튜브 쇼츠를 생성하고 업로드한다.

Ken Burns 팬/줌 + TTS 내레이션 + 자막을 ffmpeg로 로컬에서 조립한다 — 서버(NAS)에서는
아무것도 렌더링하지 않는다. NAS는 상품 데이터(JSON-LD) 조회용으로만 쓰이고, 그 조회는
이 스크립트를 호출하는 Claude Code 스킬이 SSH로 미리 해서 --post-json으로 넘겨준다
(이 스크립트 자체는 NAS/DB에 의존하지 않는 독립 실행형).

실제 상품 사진(쿠팡/알리)을 그대로 쓰고 AI로 영상 자체를 새로 생성하지 않는다 — 제휴
프로그램 정책상으로도, 소비자 신뢰 측면에서도 안전한 방식이며 2026년 업계 표준 패턴이기도
하다 (Ken Burns + TTS + ffmpeg 조립).

사용 예:
    python make_shorts.py --post-json tmp/post_537.json --post-url https://dsportal.io/... --dry-run
    python make_shorts.py --post-json tmp/post_537.json --post-url https://dsportal.io/...
"""
import argparse
import datetime
import json
import logging
import math
import re
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
import bgm as bgm_lib
import broll
import state as state_store

log = logging.getLogger("youtube_shorts")

# 이번 렌더에 쓴 BGM 트랙 — 설명란 저작자 표시에 필요하다(CC BY 의무).
_LAST_BGM: list = [None]
# 업로드 메타데이터(제목·해시태그)에 쓸 값 — 렌더 중에 확정된다.
_LAST_META: dict = {"hook": "", "category": "", "broll_ids": []}
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"
FONT = str(Path(r"C:\Windows\Fonts\malgunbd.ttf"))
MAX_PRODUCTS = 5  # 너무 길어지지 않도록 슬라이드 수 상한

# core/config.py의 social.channels.threads.linkinbio_url과 동일한 값(NAS 실제 설정
# 확인함). 이 스크립트는 로컬 단독 실행이라 NAS config를 직접 읽지 못하므로 상수로
# 고정한다 — 다른 채널(스레드)에서도 프로필 링크로 이미 쓰고 있어 시청자가 "여기서
# 본 링크"로 인지하기 쉽다는 이점도 있다.
DEFAULT_LINKINBIO_URL = "https://track.dsportal.io/link/youtube/"  # 채널별 링크인바이오(토스 subTag=youtube)
MAX_TOTAL_SEC = 58.0  # 유튜브 쇼츠로 인식되려면 세로+60초 이내여야 함 — 여유 두고 58초 상한

JSONLD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def _extract_products_from_post(html: str) -> list[dict]:
    """post.html_content에 이미 삽입된 JSON-LD(ItemList)에서 상품 데이터를 그대로 재사용."""
    m = JSONLD_RE.search(html or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    products = []
    for it in data.get("itemListElement", []):
        p = it.get("item", {}) or {}
        offers = p.get("offers", {}) or {}
        if p.get("name") and p.get("image"):
            products.append({
                "name": p["name"],
                "image": p["image"],
                "price": offers.get("price", ""),
                "url": p.get("url", ""),
            })
    return products


def _price_text(price: str) -> str:
    raw = str(price or "").replace(",", "").strip()
    if raw.replace(".", "", 1).isdigit():
        return f"{int(float(raw)):,}원"
    return ""


# NAS의 modules/trend/category_value.py와 동일한 규칙을 그대로 복제한 것 — 이 스크립트는
# NAS 코드를 import하지 않는 독립 실행형이라 로직만 미러링한다 (source of truth는 NAS 쪽).
_HIGH_VALUE_CATEGORY_RE = re.compile(
    r"(원피스|자켓|재킷|코트|니트|가디건|청바지|맨투맨|후드티|"
    r"운동화|런닝화|구두|샌들|부츠|로퍼|"
    r"가방|백팩|숄더백|지갑|"
    r"화장품|스킨케어|선크림|향수|립스틱|마스카라|쿠션팩트|앰플|세럼|"
    r"캠핑|텐트|침낭|캠핑의자|캠핑용품|등산화|등산|등산복|요가매트|"
    r"덤벨|폼롤러|헬스|필라테스|골프|자전거|낚시|"
    r"인테리어|리빙|커튼|러그|조명|디퓨저|캔들|침구|이불|매트리스|소파|"
    r"반려동물|강아지용품|고양이용품|사료|캣타워|"
    r"유아동|기저귀|분유|유모차|카시트|아기옷)"
)
_LOW_VALUE_CATEGORY_RE = re.compile(
    r"(TV|텔레비전|냉장고|세탁기|건조기|에어컨|김치냉장고|스타일러|"
    r"노트북|맥북|데스크탑|모니터|그래픽카드|메인보드|"
    r"스마트폰|아이폰|갤럭시|태블릿|아이패드|"
    r"DSLR|미러리스|플레이스테이션|닌텐도)"
)


def _category_tier(name: str) -> int:
    """0=고단가, 1=중립, 2=저단가 — 숫자가 낮을수록 우선순위 높음."""
    if _HIGH_VALUE_CATEGORY_RE.search(name):
        return 0
    if _LOW_VALUE_CATEGORY_RE.search(name):
        return 2
    return 1


# 묶음/세트 상품. 소비자 가이드가 가리키는 물건은 거의 항상 낱개다.
_BULK_RE = re.compile(r"(전\s*\d+\s*권|\d+\s*권\s*세트|\d{2,}\s*개입|,\s*\d{2,}\s*개\b|세트\s*\(전)")

# 본체가 아니라 딸린 물건. 같은 카테고리 단어를 달고 있어 이름만으론 구분이 안 된다
# — "마우스패드"에도 '마우스'가, "공기청정기 교체용 필터"에도 '공기청정기'가 있다.
_ACCESSORY_RE = re.compile(
    r"(필터|교체용|리필|전용\s*케이스|케이스|커버|거치대|받침|패드|스탠드|파우치|"
    r"어댑터|충전기|배터리|부품|소모품|액세서리|스티커|보호|클리너|케이블)")

_HERO_TOKEN_RE = re.compile(r"[가-힣A-Za-z0-9]{2,}")
# 어느 제목에나 나오는 말 + 상품명에도 흔히 박히는 마케팅 수식어.
_HERO_STOP = {
    "추천", "가이드", "방법", "정리", "총정리", "최신", "완벽", "위한", "하는", "이것",
    "년도", "트렌드", "정보", "활용", "비교", "선택", "기준", "핵심", "인기", "베스트",
    "가성비", "최고", "프리미엄", "신상", "고성능", "대용량", "다용도", "정품",
    "무료배송", "할인", "특가", "세일", "저렴", "고급", "일상", "스마트", "현명한"}


def _hero_subjects(title: str) -> list[str]:
    """제목이 실제로 가리키는 물건. broll의 72개 카테고리 목록을 기준으로 삼는다."""
    return [c for c in broll._CATEGORY_QUERIES if c in (title or "")]


def _select_hero_product(products: list[dict], title: str = "") -> dict:
    """매칭된 상품 중 글의 주제에 가장 맞는 1개를 훅의 중심으로 지정.

    **NAS의 `modules/revenue/product_data.select_hero_product`와 같은 규칙이다.**
    블로그가 원문이고 쇼츠·스레드는 거기서 뻗어나가야 하므로, 같은 글에서 채널마다
    다른 상품이 대표로 뽑히면 안 된다. 저쪽을 고치면 여기도 같이 고칠 것.
    (두 코드베이스가 물리적으로 분리돼 있어 import로 공유할 수 없어 규칙을 복제한다.)

    예전에는 `_category_tier` 동률이면 원래 순서로 갈랐는데, tier가 거의 모든 상품에서
    같은 값이라 사실상 **쿠팡 검색 1위를 그대로** 쓰는 것과 같았다. 키워드가 중의적이면
    ("원피스" = 옷 | 만화) 쿠팡이 앞에 놓는 건 우리가 원하는 물건이 아닐 때가 많다.

    판정 순서 — 앞의 것이 절대 우선이다.
      1) 부속품인가 (부속품이 주제어를 달고 있는 경우가 많아 이걸 먼저 본다)
      2) 상품명에 제목의 주제어가 들어있는가
      3) 묶음/세트인가
      4) 제목 단어 겹침 (동률일 때만 쓰는 약한 신호)
    """
    subjects = _hero_subjects(title)
    # 글 주제 자체가 부속품이면(마우스패드 글) 부속품 감점을 끈다.
    accessory_ok = bool(_ACCESSORY_RE.search(" ".join(subjects)))
    want = {t for t in _HERO_TOKEN_RE.findall(title or "")
            if t not in _HERO_STOP and not t.isdigit()
            and not any(t in c for c in subjects)}

    def rank(i: int) -> tuple:
        name = products[i].get("name", "") or ""
        accessory = 0 if accessory_ok else (1 if _ACCESSORY_RE.search(name) else 0)
        on_subject = 1 if (subjects and any(t in name for t in subjects)) else 0
        bulk = 1 if _BULK_RE.search(name) else 0
        overlap = sum(1 for t in want if t in name)
        return (accessory, -on_subject, bulk, -overlap, _category_tier(name), i)

    return products[min(range(len(products)), key=rank)]


_ORDINALS = ["첫 번째로", "두 번째로", "세 번째로", "네 번째로", "다섯 번째로"]
_DISPLAY_NAME_LEN = 26
_PARENS_RE = re.compile(r"[\(（][^)）]*[\)）]")


def _clean_name(name: str) -> str:
    """상품명에서 괄호 안 내용(주로 "럼블롤러(Rumble Roller)"처럼 같은 이름을
    영문으로 병기한 것)을 뺀다 — 괄호 안까지 그대로 읽으면 같은 이름을 두 번
    말하는 것처럼 들린다. 자막과 내레이션이 서로 다른 길이로 잘리면 화면엔 있는데
    음성으론 안 읽히는 부분이 생겨 "내용을 건너뛰고 읽는" 것처럼 들리므로,
    자막과 내레이션 모두 반드시 이 함수 하나로 만든 동일한 이름만 쓴다."""
    stripped = _PARENS_RE.sub("", name)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    base = stripped or name
    if len(base) <= _DISPLAY_NAME_LEN:
        return base.rstrip(" ,.·-")
    # 글자 수로 그냥 자르면 "...접이식 캐"처럼 단어 중간이 잘려 TTS가 어색하게
    # 끊어 읽는다 — 단어 경계에서 자르고 잘렸다는 표시를 남긴다.
    cut = base[:_DISPLAY_NAME_LEN]
    last_space = cut.rfind(" ")
    if last_space > 0:
        cut = cut[:last_space]
    # 예전엔 잘렸다는 뜻으로 "…"를 붙였는데, 호출부가 문장 끝에 마침표를 더하면서
    # 자막에 "뒷목…."처럼 점 네 개가 찍혔다(발행 영상에서 확인). 쿠팡 상품명은 어차피
    # 키워드 나열이라 어디서 잘라도 미완으로 보이므로, 표시 없이 어절 경계에서 끊는다.
    return cut.rstrip(" ,.·-")


# ── 45초 단독 상품 쇼츠 대본 구조 ──────────────────────────────────────────
# 0~3초   훅
# 3~10초  문제/궁금증 제시
# 10~18초 상품 공개
# 18~30초 핵심 장점
# 30~38초 이런 분께 추천
# 38~42초 정리
# 42~45초 댓글 유도 CTA
#
# 예전 구조는 [훅+1위][2위][3위][4위][5위+CTA]로, 훅 직후 바로 상품 나열로 들어가서
# "왜 봐야 하는지"를 세워주는 구간과 마무리 정리가 없었다. 시청 유지에 가장 크게
# 작용하는 두 구간이라 별도 세그먼트로 분리한다.
#
# 상품은 1개만 다룬다(CORE_PRODUCT_COUNT). 여러 개를 나열하면 시청자가 "어느 걸 사야
# 하나"를 또 고민하게 되고 설명란 링크도 하나뿐이라 나머지는 버려진다. 한 상품에
# 시간을 다 쓰니 장점·추천대상까지 온전히 담을 수 있다.

# 훅 — 4가지 유형. 상품 스펙은 이름/가격밖에 없으므로(JSON-LD 한계) 없는 효능을
# 지어내지 않는다. 특히 "결과 약속형"은 상품 효과가 아니라 **영상 시청으로 얻는 것**을
# 약속하는 형태로만 쓴다("이거 쓰면 인생이 바뀐다" 같은 건 검증 불가 + 과장 광고).
# 모든 훅은 "상품 1개만 보여준다"는 실제 구성과 어긋나면 안 된다 — "3개만 뽑았어요"라고
# 해놓고 하나만 나오면 그 자체로 불일치다.
# 훅 — **문제와 감정으로 시작한다. 제품 스펙이나 순위로 시작하지 않는다.**
#
# 근거: 같은 카테고리 쇼츠를 벤치마킹한 분석에서 "성과 상위 영상은 제품 특징이 아니라
# 문제/감정으로 시작한다"는 결론이 나왔다(gpters 파이프라인 사례). 예전 훅 4개 풀 중
# 절반이 "쿠팡에서 제일 위에 뜨는 거예요", "1위가 좀 의외였어요"처럼 제품·순위 중심이라
# 정확히 반대로 가고 있었다.
#
# 상품 스펙은 이름/가격밖에 없으므로(JSON-LD 한계) 없는 효능을 지어내지 않는다.
# 아래 문구는 전부 **사는 사람의 경험**에 대한 것이라 어떤 상품에 붙여도 거짓이 되지 않는다.
_HOOKS_PROBLEM = [          # 1) 문제 직격
    "{category} 고르다 창만 열 개 띄우셨죠.",
    "{category}는 뭘 기준으로 골라야 할지가 제일 어렵죠.",
    "{category} 알아보다 그냥 덮으신 적 있으실 거예요.",
]
_HOOKS_REGRET = [           # 2) 후회·감정
    "{category} 싸게 샀다가 다시 사신 적 있으세요?",
    "{category}는 잘못 고르면 계속 눈에 밟혀요.",
    "{category} 사고 나서 후회하는 이유는 대체로 비슷해요.",
]
_HOOKS_QUESTION = [         # 3) 질문형
    "{category}, 뭐 보고 고르세요?",
    "{category} 살 때 뭐부터 보세요?",
    "아직도 {category} 고민 중이세요?",
]
# 4) 결과 약속형 — 상품 효과가 아니라 **영상 시청으로 얻는 것**만 약속한다
#    ("이거 쓰면 인생이 바뀐다" 같은 건 검증 불가 + 과장 광고).
_HOOKS_PROMISE = [
    "이거 하나면 고민 끝나요.",
    "40초면 정리됩니다.",
    "딱 하나만 보고 가세요.",
]
# 5) 궁금증형 — "그래서 어떻게 되는데?"를 만드는 훅.
#
# 위 1~4번은 전부 **공감**이다("고르다 지치셨죠", "후회하는 이유는 비슷해요").
# 공감은 고개를 끄덕이게 하지만 다음 문장을 기다리게 만들지는 못한다. 반면 답이 걸린
# 질문은 그 답을 듣기 전에는 나가기 어렵다.
#
# **던진 질문은 반드시 영상 안에서 답한다.** 아래 세 개는 전부 "고를 때 뭘 보느냐"를
# 묻는데, 그 답이 [3] 핵심 장점 / [4] 추천 대상(= 블로그 본문에서 뽑은 실제 문장)이다.
# 우리가 답할 수 없는 질문("비싼 게 진짜 다를까요?" — 우리는 스펙 비교 데이터가 없다)은
# 넣지 않는다. 답 없는 질문은 낚시고, 그건 이탈을 앞당긴다.
_HOOKS_CURIOSITY = [
    "{category}, 딱 하나만 보고 골라야 한다면 뭘까요?",
    "{category} 고를 때 진짜 중요한 건 따로 있어요.",
    "{category} 다 비슷해 보이죠? 여기서 갈립니다.",
]

# 문제/궁금증 제시 — 훅에서 잡은 관심을 "그래서 왜 어렵냐"로 이어받는 구간.
_PROBLEM_TEMPLATES = [
    "{category}{eun} 종류가 너무 많죠.",
    "{category}{eun} 가격 차이가 커요.",
    "{category} 고르다 지치셨죠.",
]

# 단독 상품 소개 — 이름을 꺼내는 도입부
_PRODUCT_INTROS = [
    "제가 고른 건 이거예요.",
    "결론부터 말하면 이겁니다.",
    "그래서 이걸로 정했어요.",
]

# 갈등 비트 — [3] 장점과 [4] 추천 대상 사이에 끼우는 한 문장.
#
# 왜 넣나 — 지금 대본은 [2] 공개부터 [5] 정리까지 전부 긍정 서술이라 긴장이 0이다.
# 좋은 얘기만 이어지면 시청자는 "광고구나" 하고 나간다. 한 번 꺾어줘야 다음 문장이
# 궁금해진다.
#
# 왜 "단점"을 말하지 않나 — 블로그 본문에 단점 데이터가 있는 글이 소수다(실측: 표본
# 3건 중 1건에만 '단점/주의/불편' 표현이 있었다). 없는 단점을 지어내면 그건 허위고,
# 있는 글만 골라 쓰면 대본 구조가 글마다 달라진다.
#
# 그래서 갈등을 **상품의 결함이 아니라 시청자의 선택**에 건다. "모두에게 맞지는
# 않는다"는 어떤 상품에도 참이고, 바로 다음 [4]가 "이런 분께 맞는다"로 그 갈등을
# 풀어준다 — [4]가 나열 항목이 아니라 **앞 문장의 답**이 되는 구조다.
# 그래서 이 문장은 추천 대상([4])이 있을 때만 넣는다. 풀어줄 답이 없으면 꺾기만 하고
# 끝나서 오히려 손해다.
_TENSION = [
    "그런데 이게 모두에게 맞는 건 아니에요.",
    "다만 아무나 쓰기 좋은 건 아닙니다.",
    "여기서 한 번 더 갈립니다.",
]

# "추천 대상" 문구를 붙일 때 쓰는 도입어
_TARGET_LEAD = "이런 분께 잘 맞아요."
# 정보성 글에서 뽑은 건 "누구에게 맞는지"가 아니라 "고를 때 뭘 보는지"다.
# 체크리스트 문장에 "이런 분께 잘 맞아요"를 붙이면 말이 어긋난다.
_CRITERIA_LEAD = "고를 땐 이것만 보세요."

# 블로그 본문의 추천 대상 문장이 이미 자체 도입어로 시작하는 경우가 많다
# (실제: "이런 사람에게 추천합니다: 매일 저녁 다리 부종으로…"). 그대로 _TARGET_LEAD를
# 앞에 붙이면 "이런 분께 잘 맞아요. 이런 사람에게 추천합니다:"처럼 같은 말이 두 번
# 나온다(발행 영상에서 확인). 아래 패턴으로 시작하면 도입어를 중복해서 붙이지 않는다.
_TARGET_SELF_LEAD_RE = re.compile(
    r"^(이런|다음과\s*같은)?\s*(사람|분들?|경우)에게\s*(가장\s*)?(추천|적합|권장)\w*\s*[:：]?\s*"
)

# 정리 — 가격 언급 없이(위 _HOOKS_FACT 주석 참고) 선택 기준으로 마무리한다.
_CONCLUSIONS = [
    "쓸 환경만 맞으면 무난한 선택이에요.",
    "고민 길어지면 이걸로 시작해보세요.",
    "스펙보다 어디에 쓸지가 먼저예요.",
]

# CTA — 댓글 유도가 1순위(참여 신호가 노출에 직접 작용). 링크는 영상 설명란에 이미
# 들어가므로 내레이션에서는 짧게만 언급한다.
_CTA = "{category} 뭐 쓰세요? 댓글 남겨주세요."


def _eun_neun(word: str) -> str:
    """받침 유무에 따라 '은'/'는'을 고른다.

    템플릿에 "는"을 박아두니 "전기밥솥는 가격 차이가 커요"가 나왔다(실측). 자막으로도
    틀리지만 TTS가 그대로 읽으면 더 크게 들린다. 한글 음절은 (코드포인트-0xAC00)%28이
    0이 아니면 받침이 있다. 한글이 아닌 카테고리(SSD 등)는 "에스에스디"처럼 읽히므로
    받침 없음으로 본다."""
    ch = (word or "")[-1:] 
    if ch and "가" <= ch <= "힣":
        return "은" if (ord(ch) - 0xAC00) % 28 else "는"
    return "는"


_RANK_SECTION_RE = re.compile(r"<h2[^>]*>\s*\d+\s*위[^<]*</h2>(.*?)(?=<h2|$)", re.S)
_SENTENCE_END_RE = re.compile(r"^(.+?[다요][.!?])")


def _hero_purchase_link(html: str, title: str = "") -> str:
    """영상에서 소개한 히어로 상품의 구매 링크를 돌려준다.

    JSON-LD에 저장된 url은 클릭 추적용 리다이렉터(dsportal.io/r?...&u=<쿠팡딥링크>)라
    쿠팡 딥링크가 u 파라미터에 인코딩돼 들어있다. 유튜브 설명란에는 낯선 도메인을
    거치는 것보다 link.coupang.com으로 바로 보내는 편이 신뢰도·정책 양쪽에서 낫고,
    구매 귀속은 딥링크 자체에 심긴 파트너스 subId로 정상 처리된다."""
    import urllib.parse as _up

    products = _extract_products_from_post(html)
    if not products:
        return ""
    hero = _select_hero_product(products, title)
    url = (hero.get("url") or "").strip()
    if not url:
        return ""
    try:
        qs = _up.parse_qs(_up.urlparse(url).query)
        inner = (qs.get("u") or [""])[0]
        if inner.startswith("http"):
            return inner
    except Exception:
        pass
    return url


def _split_target_audience(text: str) -> tuple[str, str]:
    """(장점문장, 추천대상문구)로 분리한다.

    ranking.txt 프롬프트는 "추천 대상: ~" 형식을 요구하지만, LLM이 그대로 안 쓰고
    "…3~4인 가구 사용자에게 가장 추천합니다."처럼 자연스러운 마지막 문장으로 녹여
    쓰는 경우가 많다(실측). 두 형식을 모두 잡는다 — 단독 상품 영상은 한 상품에
    시간을 다 쓰므로 이 문구가 "이런 분께 맞아요" 구간을 채우는 핵심 재료다."""
    parts = re.split(r"추천\s*대상\s*[:：]", text, maxsplit=1)
    if len(parts) > 1:
        return parts[0].strip(), re.sub(r"^[\s:：]+", "", parts[1]).strip().rstrip(" .")

    # 마커가 없으면 마지막 문장이 추천 대상을 서술하는지 본다.
    sents = [s.strip() for s in re.split(r"(?<=[다요][.!?])\s+", text) if s.strip()]
    if len(sents) >= 2 and re.search(r"(추천|적합|어울)", sents[-1]):
        return " ".join(sents[:-1]).strip(), sents[-1].rstrip(" .")
    return text.strip(), ""


def _extract_rank_targets(html: str, count: int) -> list[str]:
    """각 순위 섹션의 '추천 대상' 문구만 뽑는다 (없으면 빈 문자열)."""
    out = []
    for body in _RANK_SECTION_RE.findall(html)[:count]:
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"&#\d+;", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        out.append(_split_target_audience(text)[1])
    return out


def _extract_rank_reasons(html: str, count: int) -> list[str]:
    """랭킹형 글의 'N위 [...]' h2 섹션에서 실제 장점 설명 문장을 그대로 뽑아온다.
    예전엔 상품 이름+가격만 읽고 "인기 많아요"류 막연한 문구를 붙였는데, 실제로 왜
    사야 하는지 이유가 하나도 없어 구매 전환을 유도할 수 없었다(사용자 피드백:
    "상품 그대로를 자막 및 음성으로 읽음, 구매 유도 없음"). ranking.txt 프롬프트가
    이미 각 순위마다 "왜 이 순위인지" 구체적 장점을 1~2문장 써두므로, 그걸 그대로
    재사용해 실제 설득력 있는 내레이션을 만든다. product/hybrid처럼 순위 구조가
    없는 글은 빈 리스트를 반환해 호출부가 기존 방식으로 자연스럽게 폴백한다."""
    sections = _RANK_SECTION_RE.findall(html)
    reasons = []
    for body in sections[:count]:
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"&#\d+;", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        text = _split_target_audience(text)[0]
        m = _SENTENCE_END_RE.match(text)
        if m:
            # 깨끗하게 문장이 끝나는 지점을 찾았으면 길이와 무관하게 그대로 쓴다 —
            # 여기서 또 글자 수로 재차 잘라내면 "…편의성을." 처럼 목적어만 남고
            # 서술어("자랑합니다")가 잘려나가 문장이 깨지는 문제가 있었다.
            reason = m.group(1).strip()
        elif text:
            reason = text[:55].rsplit(" ", 1)[0].rstrip(",.") + "."
        else:
            reason = ""
        reasons.append(reason)
    return reasons


_TITLE_CATEGORY_RE = re.compile(r"([가-힣A-Za-z0-9]{2,10}?)\s*(?:추천\s*TOP|순위\s*BEST)")


def _stable_seed(text: str) -> int:
    """제목에서 재현 가능한 정수 시드를 만든다.

    파이썬 내장 hash()는 문자열에 대해 프로세스마다 값이 달라진다(PYTHONHASHSEED 랜덤화).
    이걸 시드로 쓰고 있어서 **같은 글을 다시 렌더할 때마다 훅 문구도 B-roll 클립도
    바뀌었다** — 실측으로 같은 제목이 4/3/0으로 나왔다. 영상을 다시 만들어 비교해야 할 때
    이전과 다른 결과가 나오면 무엇이 개선된 건지 판단할 수가 없다."""
    return zlib.crc32(text.encode("utf-8"))


def _title_category_anchor(title: str) -> str:
    """'2026년 직장인 텐트 추천 TOP 5'에서 카테고리 명사('텐트')만 뽑는다 — ranking.txt
    템플릿이 항상 '{keyword} 추천 TOP 5'/'{keyword} 순위 BEST 5' 형태로 제목을 만들기
    때문에, 그 직전 구절의 마지막 단어가 실제 상품 카테고리다."""
    m = _TITLE_CATEGORY_RE.search(title)
    if m:
        words = m.group(1).strip().split()
        if words:
            return words[-1]
    # 랭킹형이 아닌 제목은 위 패턴에 안 걸린다 — 정보성 글이 그렇다. 이때는 제목 안에
    # 알려진 카테고리 이름이 그대로 들어있는지 찾는다(카테고리 집합이 유한하므로 가능).
    return broll.find_known_category(title)


def _filter_reasons_by_relevance(products: list[dict], reasons: list[str], title: str) -> list[str]:
    """N위 섹션과 실제 매칭된 상품이 어긋난 경우(상품 검색이 5개를 다 못 채워 무관한
    상품으로 메운 경우) 그 자리의 문장을 그대로 붙이면 "원뿔형 텐트 디자인" 같은
    설명이 세면도구 같은 완전히 무관한 상품에 붙는 사고가 난다(실사용 중 발견 —
    #540 4·5위가 텐트가 아니라 보냉백/세면도구였는데 텐트 설명이 그대로 붙었음).
    제목에서 뽑은 카테고리 단어가 상품명에 없으면 그 이유 문장은 버리고 일반
    문구로 안전하게 폴백시킨다."""
    anchor = _title_category_anchor(title)
    if not anchor:
        return reasons
    return [r if (r and anchor in p.get("name", "")) else "" for r, p in zip(reasons, products)]


# 영상은 상품 1개만 단독으로 다룬다.
# 여러 개를 나열하면 시청자가 "어느 걸 사야 하나"를 또 고민하게 되고, 설명란 링크도
# 하나만 걸 수 있어 나머지는 버려진다. 제휴 쇼츠가 단독 상품 구성인 이유다.
# 블로그는 그대로 TOP 5를 유지한다(글은 여러 상품을 비교하는 매체라 유리) — 영상만
# 히어로 상품 하나에 집중한다.
CORE_PRODUCT_COUNT = 1
# 내레이션용 문장 상한 (한국어 TTS 낭독 속도 약 6자/초).
# 상품 3개를 다루던 때는 60자로 조여야 했지만, 단독 상품 구성으로 바뀌면서 한 상품에
# 시간을 다 쓸 수 있게 됐다. 60자로 두면 블로그의 장점 문장(보통 70~80자) 대부분이
# "깔끔히 자를 지점 없음" 판정으로 통째로 생략돼, 정작 왜 사야 하는지가 빠진 영상이
# 나온다(실측 확인). 90자면 원문 그대로 들어간다.
_REASON_MAX_CHARS = 90
# 한도를 이 배율까지 넘는 건 자르지 않고 통째로 쓴다 — 몇 글자 때문에 문장을 부수는
# 것보다 조금 긴 게 낫다.
_KEEP_WHOLE_RATIO = 1.4
# 추천 대상 문구는 핵심 정보("3~4인 가구 사용자에게")가 문장 끝에 오기 때문에 앞부분만
# 남기면 정작 "누구에게"가 사라진다. 자르지 말고 통째로 들어가도록 넉넉히 잡는다.
_TARGET_MAX_CHARS = 75


# 문장 끝에 남으면 "다음 말을 꺼내다 만" 느낌이 나는 접속사/열거어.
_DANGLING_TAIL_RE = re.compile(
    r"(?:\s|^)(다만|하지만|그러나|그리고|또한|특히|첫째|둘째|셋째|먼저|마지막으로|반면)\s*$"
)

# 정보성 글(post_type=product)은 "N위" 섹션이 없고 일반 h2로만 구성된다.
_INFO_SECTION_RE = re.compile(r"<h2[^>]*>(.*?)</h2>(.*?)(?=<h2|$)", re.S)
# 우리는 쿠팡 전용이라 해외 직구/알리를 다루는 섹션은 내레이션에 쓰지 않는다 —
# 설명란 링크는 쿠팡인데 "알리에서 사면 싸다"고 말하면 그대로 어긋난다.
_OFFSITE_RE = re.compile(r"(해외\s*직구|알리|아마존|이베이|직구)")
# 어느 섹션을 어느 구간에 쓸지 — 제목만 보고 고른다.
_INFO_ADVANTAGE_RE = re.compile(r"(특징|장단점|장점|성능|비교|분석)")
_INFO_CRITERIA_RE  = re.compile(r"(체크리스트|가이드|선택|고르|기준|주의|팁)")


def _section_text(body: str) -> str:
    text = re.sub(r"<[^>]+>", " ", body)
    text = re.sub(r"&#\d+;", "", text)
    return re.sub(r"\s+", " ", text).strip()


# "~를 정리해 드립니다", "~를 알아보겠습니다"류는 다음 내용을 예고만 하는 안내 문장이라
# 영상에 넣으면 정작 내용은 없이 자리만 차지한다. 블로그에선 자연스럽지만 45초 안에
# 승부를 봐야 하는 포맷에선 통째로 버리는 게 맞다.
_META_SENTENCE_RE = re.compile(
    # "정리해 드립니다"처럼 띄어쓰기가 들어가므로 \s까지 허용한다.
    r"(정리해|알아보|살펴보|소개해|설명해|짚어보|다뤄)[\s\S]{0,6}?(드립니다|보겠습니다|겠습니다|드릴게요)"
)
# 블로그 흐름을 잇는 선두 접속어 — 앞 문단이 없는 영상에선 붕 뜬다.
_LEAD_CONNECTIVE_RE = re.compile(r"^(마지막으로|먼저|우선|또한|그리고|특히|반면|다만)[,\s]+")


def _first_sentences(text: str, max_chars: int) -> str:
    """완결된 문장만 이어붙여 max_chars 근처까지 담는다(최소 1문장).

    정보성 글에는 _shorten_for_speech를 쓰지 않는다 — 그건 글자 수로 자르는 방식이라
    "…첫째." 같은 파편이 나온다. 여기서는 문장 경계로만 끊으므로 항상 말이 끝난다."""
    out, rest = "", (text or "").strip()
    while rest:
        m = _SENTENCE_END_RE.match(rest)
        if not m:
            break
        sent = m.group(1).strip()
        rest_after = rest[len(m.group(1)):].strip()
        if _META_SENTENCE_RE.search(sent):
            # 안내 문장은 건너뛰고 다음 문장부터 담는다 (뒤에 실제 내용이 온다).
            rest = rest_after
            continue
        sent = _LEAD_CONNECTIVE_RE.sub("", sent).strip()
        if not sent:
            rest = rest_after
            continue
        if out and len(out) + 1 + len(sent) > max_chars:
            break
        out = f"{out} {sent}".strip() if out else sent
        rest = rest[len(m.group(1)):].strip()
        if len(out) >= max_chars:
            break
    return out


def _extract_info_highlights(html: str) -> tuple[str, str]:
    """정보성 글의 h2 섹션에서 (장점 문장, 선택 기준 문장)을 뽑는다.

    랭킹형이 아니면 _extract_rank_reasons/_extract_rank_targets가 빈 값을 돌려주고,
    그 결과 [핵심 장점]과 [추천 대상] 세그먼트가 통째로 빠져 영상이 15초로 줄어든다
    (실측: post#438 가습기 글이 5세그먼트 15.9초). 정보성 글에도 쓸 만한 문장은
    있으므로 섹션 제목을 보고 골라 쓴다."""
    usable: list[tuple[str, str]] = []          # (섹션 제목, 본문)
    for head, body in _INFO_SECTION_RE.findall(html or ""):
        title = re.sub(r"<[^>]+>", "", head).strip()
        if _OFFSITE_RE.search(title):
            continue
        text = _section_text(body)
        if _OFFSITE_RE.search(text[:200]):
            continue
        usable.append((title, text))

    advantage = criteria = ""
    for title, text in usable:
        if not advantage and _INFO_ADVANTAGE_RE.search(title):
            advantage = _first_sentences(text, _REASON_MAX_CHARS)
        elif not criteria and _INFO_CRITERIA_RE.search(title):
            criteria = _first_sentences(text, _TARGET_MAX_CHARS)

    # 제목 키워드로 못 고르면 순서로 고른다. info_product.txt로 만든 최신 정보성 글은
    # 제목이 각도별로 붙어("1. '고속 충전' 문구 뒤에 숨겨진 출력값의 함정") 키워드가
    # 아예 안 들어간다 — 실측으로 무선충전기·인덕션 글이 전부 15초짜리가 됐다.
    # 이런 글은 모든 섹션이 어차피 "고를 때 봐야 할 것"이라 첫 섹션과 마지막 섹션을
    # 각각 핵심 포인트와 선택 기준으로 써도 말이 어긋나지 않는다.
    if not advantage and usable:
        advantage = _first_sentences(usable[0][1], _REASON_MAX_CHARS)
    if not criteria and len(usable) > 1:
        criteria = _first_sentences(usable[-1][1], _TARGET_MAX_CHARS)
    return advantage, criteria


def _shorten_for_speech(text: str, max_chars: int = _REASON_MAX_CHARS) -> str:
    """블로그에서 뽑은 장점 문장을 내레이션 길이에 맞게 줄인다.

    블로그 문장은 글로 읽는 글이라 70~80자까지 가는데, 그대로 읽으면 상품당 20초씩
    잡아먹어 전체가 87초가 되고, _cap_segment_durations가 1.5배속으로 압축해 말이
    급하게 들린다(실측).

    다만 글자 수로 아무 데서나 자르면 "기존.", "1위 제품과 기능적인." 같은 파편이
    그대로 낭독된다(실측). 파편을 읽느니 이유를 아예 빼는 게 낫다 — 신뢰도가 걸린
    문제라서, **쉼표 같은 절 경계에서만** 자르고 마땅한 경계가 없으면 빈 문자열을
    돌려준다(호출부가 이름+가격만으로 문장을 만든다)."""
    text = (text or "").strip()
    if not text:
        return ""
    # 완결된 문장이 한도를 조금 넘는 정도면 그대로 둔다. 79자를 75자에 맞추겠다고
    # 자르면 문장만 부서지고(실측: "…강도를 섬세하게 조절하.") 아끼는 시간은 1초도
    # 안 된다. 전체 길이는 _cap_segment_durations가 따로 잡아준다.
    if len(text) <= max_chars * _KEEP_WHOLE_RATIO:
        return text
    head = text[:max_chars]
    # sep 뒤의 숫자는 "자를 때 어미를 몇 글자 남길지". 쉼표는 버리면 되지만 "며"/"고"는
    # 연결어미라 그 앞에서 자르면 "조절하며"에서 "며"가 떨어져 나가 **어간만 남는다**
    # (실측: 발행 영상 자막에 "조절하."가 그대로 나갔다). 어미까지 포함해서 자른다.
    for sep, keep in ((", ", 0), ("며 ", 1), ("고 ", 1)):
        idx = head.rfind(sep)
        if idx > max_chars // 3:
            cut = head[:idx + keep].rstrip(" ,·-")
            # 절 경계에서 잘랐는데 그 앞이 접속사면 "…있습니다. 다만." 처럼 다음 말을
            # 꺼내다 만 문장이 된다(실측). 접속사는 떼고, 떼고 나서 남는 게 없으면 생략한다.
            cut = _DANGLING_TAIL_RE.sub("", cut).rstrip(" ,·-")
            if cut:
                return cut + "."
    return ""  # 깔끔하게 자를 지점이 없으면 이유를 생략한다


def _build_segments(title: str, ordered_products: list[dict], reasons: list[str] | None = None,
                    target_is_criteria: bool = False,
                    category: str = "", targets: list[str] | None = None) -> list[str]:
    """45초 단독 상품 쇼츠 대본을 만든다.

        [0] 훅              (0~3초)
        [1] 문제 제시        (3~10초)
        [2] 상품 공개        (10~18초)
        [3] 핵심 장점        (18~30초)
        [4] 갈등 한 문장      (30~32초)  ※ [5]가 있을 때만 — 풀어줄 답이 있어야 넣는다
        [5] 이런 분께 추천    (32~40초)  ※ '추천 대상'이 없으면 [4]와 함께 생략
        [6] 정리            (40~44초)
        [7] 댓글 유도 CTA    (44~47초)

    ordered_products[0]가 히어로 상품이고, 영상은 이 한 상품만 다룬다.
    reasons/targets는 랭킹형 글의 'N위' 섹션에서 뽑은 실제 문장이라 새로 창작하지
    않는다. 가격은 어디에도 넣지 않는다 — 영상은 남고 가격은 바뀐다.

    세그먼트별로 TTS를 따로 만들어 각 세그먼트의 실제 음성 길이를 그 슬라이드에
    정확히 쓴다 — 평균으로 나누면 문장 길이가 제각각이라 뒤로 갈수록 어긋난다."""
    reasons = reasons or []
    targets = targets or []
    seed = _stable_seed(title)
    cat = category or "이 제품"
    segments = []

    hero = ordered_products[0]
    hero_name = _clean_name(hero["name"])

    # [0] 훅 — 5가지 유형을 순환한다.
    # 제품 자랑으로 시작하는 유형은 하나도 없다 — 문제/감정/질문/궁금증 계열뿐이다.
    pools = [_HOOKS_PROBLEM, _HOOKS_REGRET, _HOOKS_QUESTION, _HOOKS_PROMISE,
             _HOOKS_CURIOSITY]
    pool = pools[seed % len(pools)]
    segments.append(pool[seed % len(pool)].format(category=cat))

    # [1] 문제/궁금증 제시
    segments.append(_PROBLEM_TEMPLATES[seed % len(_PROBLEM_TEMPLATES)]
                    .format(category=cat, eun=_eun_neun(cat)))

    # [2] 상품 공개 — 이름은 여기서 한 번만 또렷하게 말한다.
    segments.append(f"{_PRODUCT_INTROS[seed % len(_PRODUCT_INTROS)]} {hero_name}.")

    # [3] 핵심 장점 — 블로그 1위 섹션 문장 그대로
    reason = _shorten_for_speech(reasons[0] if reasons else "")
    if reason:
        segments.append(reason)

    # [4] 갈등 + [5] 이런 분께 추천 — 블로그의 '추천 대상' 문구 활용
    target = _shorten_for_speech(targets[0] if targets else "", _TARGET_MAX_CHARS)
    if target:
        # 본문이 이미 "이런 사람에게 추천합니다:"로 시작하면 그 부분을 걷어내고
        # 우리 도입어 하나만 쓴다 — 같은 말을 두 번 하지 않는다.
        target = _TARGET_SELF_LEAD_RE.sub("", target).strip()
        if target:
            # 갈등은 답이 바로 뒤따를 때만 넣는다(_TENSION 주석 참고).
            # '고를 때 뭘 보는지' 체크리스트에는 붙이지 않는다 — "모두에게 맞는 건
            # 아니다"는 상품 얘기지 기준 얘기가 아니라서 말이 어긋난다.
            if not target_is_criteria:
                segments.append(_TENSION[seed % len(_TENSION)])
            lead = _CRITERIA_LEAD if target_is_criteria else _TARGET_LEAD
            segments.append(f"{lead} {target.rstrip('.')}.")

    # [6] 정리
    segments.append(_CONCLUSIONS[seed % len(_CONCLUSIONS)])

    # [7] CTA — 댓글 유도 우선
    segments.append(_CTA.format(category=cat))
    return segments


def _synthesize_tts(text: str, out_path: Path, provider: str, voice: str, openai_key: str) -> None:
    if provider == "edge":
        import tts_edge
        tts_edge.synthesize(text, out_path, voice=voice or tts_edge.DEFAULT_VOICE)
    elif provider == "openai":
        import tts_openai
        tts_openai.synthesize(text, out_path, voice=voice or tts_openai.DEFAULT_VOICE, api_key=openai_key)
    else:
        raise ValueError(f"알 수 없는 TTS 프로바이더: {provider}")


def _trim_silence(path: Path) -> None:
    """TTS 앞뒤 무음을 잘라낸다 (제자리 치환).

    조회수가 잘 나오는 쇼츠의 공통점 중 하나가 "숨 쉬는 구간을 다 잘라내 이탈할 틈을
    주지 않는 것"인데, edge-tts 출력은 문장마다 앞뒤로 0.9~1.8초씩 무음이 붙는다.
    세그먼트를 이어붙이면 문장 사이마다 그 정적이 그대로 쌓여, 실측 결과 전체 오디오의
    **28%(22.3초 중 6.4초)**가 빈 구간이었다. 초반 3초가 승부인 포맷에서 훅 뒤에
    1초 가까운 공백이 붙는 건 그 자체로 손해다.

    -45dB 기준으로 자르되 끝에 0.15초는 남긴다 — 완전히 붙여버리면 다음 문장과
    말이 겹쳐 들려서 오히려 알아듣기 어려워진다.
    """
    trimmed = path.with_name(path.stem + "_trim" + path.suffix)
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(path), "-af",
         "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-45dB:"
         "stop_periods=-1:stop_silence=0.15:stop_threshold=-45dB",
         str(trimmed)],
        capture_output=True,
    )
    # 무음 제거가 실패하거나 결과가 비면 원본을 그대로 쓴다 — 오디오가 사라지는 것보다
    # 조금 긴 편이 낫다.
    if r.returncode == 0 and trimmed.exists() and trimmed.stat().st_size > 1024:
        trimmed.replace(path)
    else:
        log.warning(f"무음 제거 실패, 원본 사용: {path.name}")
        trimmed.unlink(missing_ok=True)


def _audio_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _video_duration_by_frames(path: Path, fps: int = 25) -> float:
    """컨테이너 메타데이터(format=duration)는 이 파이프라인이 생성한 영상에서
    실제 디코딩 프레임 수와 어긋나는 경우가 있어(-count_frames로 직접 확인),
    영상 길이는 반드시 실제 프레임 수를 세어서 계산한다."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
         "-show_entries", "stream=nb_read_frames",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return int(out.stdout.strip()) / fps


def _cap_segment_durations(seg_paths: list[Path], seg_durs: list[float], workdir: Path) -> tuple[list[Path], list[float]]:
    """전체 길이가 유튜브 쇼츠 상한(MAX_TOTAL_SEC)을 넘으면 모든 세그먼트에 동일한
    배속을 적용해 영상 전체를 그 안에 맞춘다 (세그먼트별로 개별 배속하면 상품마다
    말하는 속도가 달라져 더 부자연스러워지므로 전체에 같은 비율을 적용한다).
    atempo 필터는 0.5~2.0 배속만 단일 적용 가능 — 상품 수 상한(5개)에서 2배속을
    넘길 일은 사실상 없어 단일 적용으로 충분하다."""
    total = sum(seg_durs)
    if total <= MAX_TOTAL_SEC:
        return seg_paths, seg_durs
    speed = min(total / MAX_TOTAL_SEC, 2.0)
    new_paths, new_durs = [], []
    for i, p in enumerate(seg_paths):
        sped_path = workdir / f"seg_{i}_sped.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(p), "-filter:a", f"atempo={speed:.4f}", str(sped_path)],
            capture_output=True, check=True,
        )
        new_paths.append(sped_path)
        new_durs.append(_audio_duration(sped_path))
    return new_paths, new_durs


def _concat_audio(seg_paths: list[Path], out_path: Path, workdir: Path) -> None:
    list_file = workdir / "audio_concat_list.txt"
    # **절대 경로로 적는다.** ffmpeg 의 concat 디먹서는 목록 안의 상대 경로를
    # 실행 위치가 아니라 **목록 파일이 있는 폴더** 기준으로 푼다. --out 을 상대
    # 경로로 주면(예: ../remotion_shorts/public/post_655) 목록이 그 폴더 안에
    # 만들어지므로 경로가 한 단계 더 들어가 전부 깨진다.
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in seg_paths),
        encoding="utf-8",
    )
    # 세그먼트별로 따로 인코딩된 mp3를 이어붙일 때 스트림 그대로 copy하면 이음매에서
    # 미세한 끊김/클릭음이 생길 수 있어 다시 인코딩한다.
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
         "-c:a", "aac", "-b:a", "192k", str(out_path)],
        capture_output=True, check=True,
    )


def _download_image(url: str, out_path: Path) -> None:
    r = httpx.get(url, timeout=30, follow_redirects=True)
    r.raise_for_status()
    out_path.write_bytes(r.content)


# 자막은 **한 번에 한 줄만** 띄우고 음성에 맞춰 넘긴다(_caption_cues 참고). 여러 줄을
# 한꺼번에 띄우면 상자가 상품 사진을 크게 덮는데, 한 줄이면 거의 안 가린다.
#
# **8자 이내로 짧게 끊는다.** 참고한 쇼핑쇼츠 제작 스펙이 "흰색 텍스트로 8자 이내,
# 가독성 높고 빠르게 끊겨서 짧게"를 요구한다. 14자였을 때는 8.7초 구간이 5줄(줄당
# 1.74초)이었는데, 8자로 줄이면 9줄(줄당 0.97초)이 되어 훨씬 빠르게 넘어간다.
# 글자 수가 줄어든 만큼 폰트를 46px에서 72px로 키울 수 있다.
# 한 줄 8자 x 72px = 576px + 상자 여백 44px = 620px. 화면 중앙(540) 정렬 시
# 오른쪽 끝이 850px라 우측 데드존(888~)에 닿지 않는다. 이 셋(글자 수·폰트 크기·
# 상자 여백)은 함께 계산해야 한다 — 하나만 키우면 버튼 뒤로 글자가 들어간다.
_CAPTION_MAX_CHARS_PER_LINE = 8

# 자막 박스 아래쪽 여백(px). 유튜브 쇼츠는 하단 350~400px를 자체 UI(제목·채널명·설명·
# 진행바)로 덮으므로, 그보다 위에 자막이 놓이도록 넉넉히 띄운다.
_CAPTION_BOTTOM_MARGIN = 470


def _wrap_lines(text: str, max_chars: int) -> list[str]:
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for w in words:
        while len(w) > max_chars:  # 공백 없는 긴 단어는 강제로 잘라서 줄바꿈
            if current:
                lines.append(current)
                current = ""
            lines.append(w[:max_chars])
            w = w[max_chars:]
        candidate = f"{current} {w}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = w
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


_CAPTION_MAX_LINES = 7  # 이유 문장까지 자막에 실으면서 화면을 넘지 않게 하는 상한


def _wrap_caption(caption_text: str, max_chars: int = _CAPTION_MAX_CHARS_PER_LINE,
                   max_lines: int = _CAPTION_MAX_LINES) -> list[str]:
    """자막을 프레임 폭(1080px)에 맞춰 여러 줄로 나눈다.
    예전엔 자막이 상품명+가격만 따로 만들어져서, 내레이션(훅/이유 문장 포함)과
    자막이 서로 다른 내용이 되는 문제가 있었다 — 음성으론 구매 이유를 말하는데
    화면 자막엔 이름만 나와 "후킹 멘트 없이 음성으로만 읽어주는" 것처럼 보였다
    (사용자 피드백). 이제 내레이션과 완전히 같은 문자열(seg_text)을 그대로
    자막으로 감아써서 화면과 음성이 항상 일치한다.
    문장이 길어서 상한 줄 수를 넘으면, 맨 마지막 줄(거의 항상 가격/CTA 문장)은
    반드시 보존하고 중간 내용만 줄여서 "…"로 표시한다 — 그냥 뒤에서 잘라내면
    가격이 화면에서 통째로 사라지는 문제가 있었다."""
    lines = _wrap_lines(caption_text, max_chars)
    if len(lines) <= max_lines:
        return lines
    last_line = lines[-1]
    head = lines[: max_lines - 1]
    head[-1] = head[-1].rstrip()[: max_chars - 1] + "…"
    return head + [last_line]


def _caption_cues(caption_text: str, duration: float,
                  max_chars: int = _CAPTION_MAX_CHARS_PER_LINE) -> list[tuple[str, float, float]]:
    """자막을 한 줄씩 끊고 각 줄의 표시 구간 (문장, 시작초, 끝초)을 돌려준다.

    여러 줄을 한꺼번에 띄우면 자막 상자가 상품 사진을 크게 덮는다(실측: 6줄이면 상품
    아래 절반이 가려졌다). 한 줄씩 음성에 맞춰 넘기면 화면이 시원해지고, 지금 읽는
    부분이 어디인지도 분명해진다.

    구간은 **글자 수 비례**로 나눈다. TTS는 한국어를 대체로 일정한 속도로 읽으므로
    글자 수가 곧 소요 시간이다. duration은 그 세그먼트 음성의 실측 길이라, 마지막 줄은
    음성이 끝나는 순간에 정확히 함께 사라진다."""
    lines = _wrap_lines(caption_text, max_chars)
    if not lines:
        return []
    total = sum(len(ln) for ln in lines) or 1
    out, elapsed = [], 0.0
    for i, ln in enumerate(lines):
        # 마지막 줄은 세그먼트 끝까지 — 반올림 오차로 자막 없는 프레임이 생기지 않게.
        end = duration if i == len(lines) - 1 else elapsed + duration * len(ln) / total
        out.append((ln, elapsed, end))
        elapsed = end
    return out


# ── 화면 레이아웃 / 세이프존 ──────────────────────────────────────────────────
#
# 유튜브 쇼츠는 영상 위에 자체 UI(검색·메뉴, 우측 좋아요/댓글/공유, 하단 채널명·제목·
# 음원 정보)를 덮어 그린다. 그 영역을 데드존이라 하고, 글자가 거기 들어가면 그냥 안 보인다.
#
# 1080x1920 기준 데드존 (출처: somake.ai 쇼츠 비율 가이드 + MEWPOT 세이프라인 템플릿,
# 사용자 제공):
#     상단 288 / 하단 672 / 좌측 48 / 우측 192
#   → 안전 영역 = x 48~888, y 288~1248 (840 x 960)
#
# 우측 여백(192)이 좌측(48)의 4배다. 화면 정중앙(540) 기준으로 가운데 정렬하면 오른쪽
# 끝이 먼저 버튼에 닿으므로, 글자 폭을 696px 이하로 묶어야 한다(540 + 696/2 = 888).
#
# 이전 레이아웃은 타이틀을 y96/y196에, 자막 기준선을 y1470에 뒀는데 **셋 다 데드존**
# 이었다. 자막 폭도 오른쪽 끝이 922px로 우측 버튼과 겹쳤다.
_CANVAS_W, _CANVAS_H = 1080, 1920
_SAFE_TOP, _SAFE_BOTTOM = 288, 1248
_SAFE_RIGHT = 888

_TITLE_Y_SUB = 296         # 노란 수식어 상단 y
_TITLE_Y_MAIN = 344        # 흰색 핵심어 상단 y (끝나는 지점 약 420)
_TITLE_SUB_SIZE = 38
_TITLE_MAIN_SIZE = 66
_TITLE_SUB_COLOR = "#FFD54A"
_TITLE_SUB_MAX = 14        # 14자 x 38px = 532px → 우측 끝 806px, 안전
_TITLE_SUB_MIN = 6         # 이보다 짧으면 수식어를 생략한다(_title_block 참고)
_TITLE_BOX = 0.45          # 타이틀 뒤 검정 박스 불투명도

# 화면은 **꽉 채운다**(풀블리드). 검정 띠를 위아래로 크게 두면 화면이 비어 보인다 —
# 잘 나가는 쇼츠는 영상이 프레임을 가득 채우고 자막만 안전 구역에 있다(사용자 제공
# 레퍼런스에서 확인).
#
# 문제는 쿠팡 상품 사진이 전부 정사각형이라는 것. 꽉 채우려고 crop하면 좌우 44%가
# 잘려 무슨 물건인지 알 수 없게 된다(실측). 그래서 **배경과 전경을 분리**한다:
#   배경 = 같은 사진을 꽉 채워 크롭한 뒤 블러 + 어둡게 → 프레임을 채우고 자막이 묻히지 않음
#   전경 = 상품 전체가 보이도록 _CARD 안에 축소해서 얹음 (절대 안 잘림)
# B-roll은 이미 9:16 실사 영상이라 그냥 꽉 채워 크롭한다.
# 상품은 **고정된 정사각형**에 중앙 정렬로 놓는다. 타이틀 아래(430)와 자막 바 위(1148)
# 사이에 딱 맞춰 두 레이어와 절대 겹치지 않게 한다 — 위치가 슬라이드마다 흔들리면
# 안 된다.
# **모든 소재가 같은 크기의 정사각 카드에 들어간다.**
#
# 예전엔 B-roll은 화면을 꽉 채우고(1080x1920) 상품 사진만 작은 카드에 넣어서, 슬라이드가
# 넘어갈 때마다 화면에서 보이는 영역 크기가 확 달라졌다 — 사용자 피드백 "영상과 이미지라
# 중간중간 크기가 서로 맞지 않아 이질감이 크다".
#
# 상품 사진은 정사각(1600x1600 등)이라 정사각 카드에 딱 맞고, 9:16 실사 영상은 중앙을
# 정사각으로 잘라 넣으면 똑같이 카드를 채운다. 둘 다 **같은 사각형을 가득 채우므로**
# 화면 구성이 처음부터 끝까지 흔들리지 않는다.
_CARD = 700                # 카드 한 변
_CARD_TOP = 420            # 타이틀(≤410)과 자막 바(1124~) 사이
_BG_DIM = 0.75             # 블러 배경 위에 덮는 검정 불투명도

# 자막 **하단**을 안전 영역 맨 아래에 맞춘다. 줄 수가 늘면 위로 자라 패널을 덮지만,
# 아래로 자라면 채널명·제목에 가려 마지막 줄이 통째로 사라진다.
# drawtext는 y를 **글자 상자(text)** 기준으로 잡고, box=1이면 boxborderw만큼 사방으로
# 더 그린다. 그래서 기준선을 그대로 1248로 두면 상자 아래쪽이 22px 삐져나간다.
# 자막은 **가로 풀사이즈 고정 바**다. 글자 길이에 따라 상자 폭이 달라지면 슬라이드마다
# 자막 덩어리가 커졌다 작아졌다 해서 화면이 어수선해진다. 바는 항상 같은 자리에 있고
# 글자만 바뀐다.
_CAPTION_BAR_TOP = 1124
_CAPTION_BAR_H = 124       # 한 줄(72px) + 위아래 여백
_CAPTION_BAR_ALPHA = 0.82
_CAPTION_SIZE = 72


def _title_block(title: str, category: str) -> tuple[str, str]:
    """상단 고정 타이틀 (노란 수식어, 흰색 핵심어)를 만든다.

    핵심어는 카테고리 그대로 쓴다 — 없으면 ("", "")를 돌려주고 호출부가 타이틀 블록을
    통째로 생략한다. 카테고리를 못 뽑았는데 제목 앞부분을 잘라 넣으면
    "후기고령자를 위한 " 같은 토막이 큰 글씨로 박힌다(실측)."""
    cat = (category or "").strip()
    if not cat or cat not in (title or ""):
        return "", ""
    rest = re.sub(r"\s+", " ", title.replace(cat, " ", 1)).strip(" ,·")
    if len(rest) > _TITLE_SUB_MAX:
        # 쉼표가 있으면 첫 절만 쓴다 — "구매 전, 당신이 놓치기 쉬운 4가지 체크리스트"에서
        # "구매 전"만 남기는 쪽이 잘린 문장보다 읽힌다.
        clauses = [c.strip(" ·") for c in re.split(r"[,·]", rest) if c.strip(" ·")]
        rest = clauses[0] if clauses else rest
    if len(rest) > _TITLE_SUB_MAX:
        cut = rest[:_TITLE_SUB_MAX]
        sp = cut.rfind(" ")
        rest = (cut[:sp] if sp > 4 else cut).rstrip(" ,·")
    # 너무 짧으면 아예 뺀다. "무선충전기 구매 전, 당신이 놓치기 쉬운 …"에서 "구매 전"만
    # 남으면 화면엔 "구매 전 / 무선충전기"가 되어 어순이 뒤집힌 것처럼 읽힌다(사용자
    # 피드백). 없는 게 낫지, 없는 말을 지어내진 않는다.
    if len(rest) < _TITLE_SUB_MIN:
        return "", cat
    return rest, cat


# 상품 전경은 **정지**시킨다. 예전엔 슬라이드마다 다른 줌(Ken Burns)을 걸었는데,
# 정사각 상품 사진에 미세하게 확대/축소가 걸리니 "어설프고 지저분하다"는 피드백을
# 받았다. 사진 한 장을 억지로 움직이는 것보다, 슬라이드가 **넘어갈 때** 전환 효과를
# 주는 편이 훨씬 깔끔하다(_TRANSITIONS 참고).
# 슬라이드가 넘어갈 때 쓰는 전환 효과. 한 영상에서 겹치지 않게 순환하고, 시드가
# 글마다 달라 채널 전체가 같은 패턴으로 보이지도 않는다.
# 화려한 것(pixelize, radial 등)은 뺐다 — 상품 소개 영상에서는 산만하다.
_TRANSITIONS = [
    "slideleft", "fade", "slideup", "wipeleft", "dissolve",
    "slideright", "smoothleft", "slidedown",
]
_TRANSITION_DUR = 0.45     # 전환 길이(초)


def _make_slide_clip(img_path: Path, duration: float, out_path: Path,
                     workdir: Path, is_video: bool = False, hold_until: float = 0.0) -> None:
    """슬라이드 한 장을 렌더한다 — **배경과 상품 이미지만**.

    타이틀과 자막은 여기서 그리지 않는다. 슬라이드 전환(slideleft 등)을 걸면 이 클립
    전체가 밀리므로, 클립 안에 글자를 넣으면 글자도 같이 밀려 위치가 흔들린다.
    두 요소는 합성이 끝난 뒤 _assemble에서 **고정 레이어**로 한 번에 얹는다.

    text='...\n...' 방식은 필터그래프 파싱 단계에서 백슬래시가 사라지고 문자 그대로의
    "n"만 남는 문제가 있었다 (실제로 "EPP 폼롤러 +n운동법..." 처럼 렌더링됨 — 프레임을
    뽑아 직접 확인함). 그래서 모든 글자는 textfile로 넘긴다."""
    # 클립 길이는 hold_until(= 세그먼트 길이 + 전환 여유)까지 렌더한다.
    clip_len = max(duration, hold_until)
    n_frames = max(math.ceil(clip_len * 25), 1)
    # 배경 — 소재를 꽉 채워 크롭한 뒤 블러 + 검정 덮기.
    # 어둡게 까는 건 eq=brightness가 아니라 **검은 사각형 덮기**로 한다. 쿠팡 상품 사진은
    # 대부분 흰 배경이라 블러해도 여전히 흰색이고, brightness로 낮추면 원본 밝기에 따라
    # 결과가 제각각이다(실측: 타이틀 글자가 묻혔다).
    fill = (f"scale={_CANVAS_W}:{_CANVAS_H}:force_original_aspect_ratio=increase,"
            f"crop={_CANVAS_W}:{_CANVAS_H}")
    # 전경 — 무엇이든 같은 정사각 카드를 **가득 채운다**(increase 후 crop).
    # 상품 사진은 정사각이라 손실이 없고, 9:16 영상은 중앙만 남는다.
    card = (f"scale={_CARD}:{_CARD}:force_original_aspect_ratio=increase,"
            f"crop={_CARD}:{_CARD},fps=25")
    # B-roll이 세그먼트보다 짧아도 이어붙여 화면이 끊기지 않게 한다.
    src = (["-stream_loop", "-1", "-i", str(img_path)] if is_video
           else ["-loop", "1", "-i", str(img_path)])
    fc = (
        "[0:v]split=2[bg][fg];"
        f"[bg]{fill},gblur=sigma=32,"
        f"drawbox=x=0:y=0:w=iw:h=ih:color=black@{_BG_DIM}:t=fill[bgb];"
        f"[fg]{card}[fgc];"
        f"[bgb][fgc]overlay=(W-w)/2:{_CARD_TOP}:shortest=0[v]"
    )
    # -an: B-roll 원본 소리는 버린다(내레이션과 겹치면 안 된다).
    # -t가 아니라 -frames:v를 쓴다 — 25fps 기준 프레임 수를 내림 처리하면 매 슬라이드가
    # 오디오보다 최대 40ms씩 짧아지고(누적되면 수백 ms), _assemble()의 -shortest가
    # 그 짧은 쪽(영상)에 맞춰 오디오 끝을 잘라낸다.
    subprocess.run(
        ["ffmpeg", "-y", *src, "-an", "-filter_complex", fc, "-map", "[v]",
         "-frames:v", str(n_frames), "-r", "25", "-pix_fmt", "yuv420p", str(out_path)],
        capture_output=True, check=True,
    )


def _assemble(clips: list[Path], audio_path: Path, out_path: Path, workdir: Path,
              seg_durs: list[float], transitions: list[str],
              cues: list[tuple[str, float, float]],
              title_sub: str = "", title_main: str = "") -> None:
    """슬라이드를 전환 효과로 이어붙이고 내레이션을 얹는다.

    xfade는 두 클립을 duration만큼 겹쳐 섞으므로 이어붙일수록 전체가 짧아진다. 그래서
    호출부가 마지막을 뺀 각 클립을 전환 길이만큼 **더 길게** 렌더해 두고, 여기서 그
    여유분을 전환이 먹는다. 결과적으로 최종 길이 = 세그먼트 길이 합 = 내레이션 길이라
    A/V가 어긋나지 않는다.

    offset(전환 시작 시각)은 각 세그먼트 경계와 정확히 일치한다 — 새 문장이 시작되는
    순간 화면이 넘어가기 시작한다.
    """
    silent = workdir / "silent.mp4"
    n = len(clips)
    cmd = ["ffmpeg", "-y"]
    for c in clips:
        cmd += ["-i", str(c)]

    if n == 1:
        chain, last = "", "0:v"
    else:
        parts, acc = [], seg_durs[0] + _TRANSITION_DUR
        last = "0:v"
        for i in range(1, n):
            offset = acc - _TRANSITION_DUR
            tag = f"vx{i}"
            tr = transitions[(i - 1) % len(transitions)]
            parts.append(f"[{last}][{i}:v]xfade=transition={tr}:"
                         f"duration={_TRANSITION_DUR}:offset={offset:.3f}[{tag}]")
            last = tag
            clip_len = seg_durs[i] + (_TRANSITION_DUR if i < n - 1 else 0.0)
            acc += clip_len - _TRANSITION_DUR
        chain = ";".join(parts)

    # 고정 타이틀은 전환이 다 끝난 **전체 영상 위에** 한 번만 그린다. 클립마다 그리면
    # 슬라이드 전환에 타이틀도 같이 밀려 고정처럼 보이지 않는다.
    font = FONT.replace("\\", "/").replace(":", "\:")
    title_draw = []
    if title_main:
        def _tf(name: str, content: str) -> str:
            f = workdir / f"title_{name}.txt"
            f.write_text(content, encoding="utf-8")
            return str(f).replace("\\", "/").replace(":", "\:")
        if title_sub:
            title_draw.append(
                f"drawtext=fontfile='{font}':textfile='{_tf('sub', title_sub)}':"
                f"fontsize={_TITLE_SUB_SIZE}:fontcolor={_TITLE_SUB_COLOR}:borderw=3:"
                f"bordercolor=black:x=(w-text_w)/2:y={_TITLE_Y_SUB}:"
                # 전환 중 흰 상품 사진이 타이틀 영역을 지나가면 흰 글자가 묻힌다(실측).
                # 옅은 검정 박스를 깔면 배경이 무엇이든 항상 읽힌다 — 어두운 블러 배경
                # 위에서는 거의 보이지 않을 만큼만 넣는다.
                f"box=1:boxcolor=black@{_TITLE_BOX}:boxborderw=12")
        # 수식어가 없으면 핵심어를 그 자리까지 끌어올린다 — 안 그러면 위쪽에 빈 줄이
        # 남아 글자가 아래로 처져 보인다.
        main_y = _TITLE_Y_MAIN if title_sub else _TITLE_Y_SUB + 14
        title_draw.append(
            f"drawtext=fontfile='{font}':textfile='{_tf('main', title_main)}':"
            f"fontsize={_TITLE_MAIN_SIZE}:fontcolor=white:borderw=4:bordercolor=black:"
            f"x=(w-text_w)/2:y={main_y}:box=1:boxcolor=black@{_TITLE_BOX}:boxborderw=14")
    # 자막도 고정 레이어다. 바는 **가로 풀사이즈에 항상 같은 자리**이고 글자만 바뀐다 —
    # 글자 길이에 따라 상자 폭이 달라지면 슬라이드마다 자막 덩어리가 커졌다 작아졌다 해서
    # 화면이 어수선하다. 시각은 전체 타임라인 기준 절대값이라 전환과 무관하게 정확하다.
    bar_mid = _CAPTION_BAR_TOP + _CAPTION_BAR_H // 2
    caption_draw = [
        f"drawbox=x=0:y={_CAPTION_BAR_TOP}:w=iw:h={_CAPTION_BAR_H}:"
        f"color=black@{_CAPTION_BAR_ALPHA}:t=fill"
    ] if cues else []
    for ci, (line, t0, t1) in enumerate(cues):
        f = workdir / f"cue_{ci}.txt"
        f.write_text(line, encoding="utf-8")
        path = str(f).replace("\\", "/").replace(":", "\:")
        caption_draw.append(
            f"drawtext=fontfile='{font}':textfile='{path}':fontsize={_CAPTION_SIZE}:"
            f"fontcolor=white:borderw=3:bordercolor=black:x=(w-text_w)/2:"
            f"y={bar_mid}-text_h/2:enable='between(t,{t0:.3f},{t1:.3f})'")

    overlays = caption_draw + title_draw
    head = f"[{last}]" if chain else "[0:v]"
    graph = (chain + ";" if chain else "") + head + (",".join(overlays) if overlays else "null") + "[outv]"
    cmd += ["-filter_complex", graph,
            "-map", "[outv]", "-pix_fmt", "yuv420p", "-r", "25", str(silent)]
    subprocess.run(cmd, capture_output=True, check=True)

    # 전환/재인코딩을 거치면 영상이 오디오보다 몇 프레임 짧아질 때가 있다. 짧으면
    # 마지막 프레임을 정지 화면으로 늘린다 — 아래 -shortest가 오디오 끝을 잘라내면
    # 바로 티가 나지만, 마지막 화면이 조금 더 머무는 건 눈에 띄지 않는다.
    video_dur = _video_duration_by_frames(silent)
    audio_dur = _audio_duration(audio_path)
    if video_dur < audio_dur:
        pad_amount = audio_dur - video_dur + 0.5
        padded = workdir / "silent_padded.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(silent),
             "-vf", f"tpad=stop_mode=clone:stop_duration={pad_amount:.3f}",
             "-pix_fmt", "yuv420p", "-r", "25", str(padded)],
            capture_output=True, check=True,
        )
        silent = padded

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(silent), "-i", str(audio_path),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         "-movflags", "+faststart", str(out_path)],
        capture_output=True, check=True,
    )


def render_video(post_id: int, title: str, html: str, tts_provider: str, voice: str,
                 openai_key: str, media_keys: dict | str = "",
                 product_clip: Path | None = None) -> Path | None:
    products = _extract_products_from_post(html)[:MAX_PRODUCTS]
    if not products:
        log.error(f"[post#{post_id}] JSON-LD 상품 없음 — 중단")
        return None

    # 랭킹형 글이면 "N위" 섹션에서 실제 장점 문장을 상품과 같은 순서로 미리 뽑아둔다
    # (product/hybrid 등 순위 구조가 없는 글은 빈 리스트 → 기존 방식으로 폴백).
    target_is_criteria = False
    reasons = _extract_rank_reasons(html, len(products))
    reasons = _filter_reasons_by_relevance(products, reasons, title)
    targets = _extract_rank_targets(html, len(products))

    # 정보성 글은 위 두 추출이 전부 빈 값이라 [핵심 장점]/[추천 대상] 세그먼트가
    # 사라진다 — 그러면 7개여야 할 세그먼트가 5개로 줄어 영상이 15초짜리가 된다.
    # 이때만 일반 h2 섹션에서 문장을 가져온다(랭킹형에는 영향 없음).
    if not any(reasons) and not any(targets):
        info_reason, info_target = _extract_info_highlights(html)
        # 모든 상품 슬롯에 같은 문장을 넣는다. 랭킹형과 달리 이 문장은 특정 상품이 아니라
        # 카테고리에 대한 설명이라 어느 상품에 붙어도 맞고, 무엇보다 아래에서 히어로 상품을
        # 맨 앞으로 재정렬하기 때문이다 — 0번에만 넣으면 히어로가 0번이 아닐 때 그 문장이
        # 통째로 날아가 세그먼트가 다시 5개로 줄어든다(실측: post#565 빨래건조대).
        if info_reason:
            reasons = [info_reason] * len(products)
        if info_target:
            targets = [info_target] * len(products)
            target_is_criteria = True

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"post_{post_id}.mp4"

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp = Path(tmp_str)

        # 이미지를 먼저 전부 내려받아 실제로 화면에 나올 상품만 확정한 뒤,
        # 그 확정된 목록으로만 내레이션 스크립트를 만든다.
        # (예전 버전은 순서대로 다운로드하면서 실패한 상품만 건너뛰고 넘어갔는데,
        # 내레이션 스크립트는 원래 상품 순서 그대로 만들어져 있어서 — 예를 들어
        # 2번째 상품 다운로드가 실패하면 화면엔 [1,3,4,5]가 나오는데 내레이션은
        # 여전히 "1번...2번...3번..." 순서로 읽어서, 그 지점부터 모든 슬라이드가
        # 한 칸씩 밀려 금액/이름이 자막과 어긋나는 버그가 있었다.)
        valid_products = []
        valid_reasons = []
        valid_targets = []
        img_paths = []
        for i, p in enumerate(products):
            img_path = tmp / f"img_{i}.jpg"
            try:
                _download_image(p["image"], img_path)
            except Exception as e:
                log.warning(f"이미지 다운로드 실패, 이 상품은 영상에서 제외 [{p['image']}]: {e}")
                continue
            valid_products.append(p)
            valid_reasons.append(reasons[i] if i < len(reasons) else "")
            valid_targets.append(targets[i] if i < len(targets) else "")
            img_paths.append(img_path)

        if not valid_products:
            log.error("유효한 상품 이미지 없음 — 중단")
            return None

        # 히어로 상품(카테고리 등급이 가장 높은 1개)을 맨 앞으로 — 세그먼트(내레이션)와
        # 슬라이드(이미지)가 반드시 같은 순서를 참조해야 하므로 리스트를 함께 재정렬한다.
        hero = _select_hero_product(valid_products, title)
        hero_i = next(i for i, p in enumerate(valid_products) if p is hero)
        order = [hero_i] + [i for i in range(len(valid_products)) if i != hero_i]
        valid_products = [valid_products[i] for i in order]
        valid_reasons = [valid_reasons[i] for i in order]
        valid_targets = [valid_targets[i] for i in order]
        img_paths = [img_paths[i] for i in order]
        log.info(f"단독 소개 상품: {_clean_name(hero['name'])}")

        # 세그먼트마다 TTS를 따로 만들어 실제 음성 길이를 정확히 측정한다 — 슬라이드
        # 길이를 "평균"으로 나누면 문장마다 길이가 달라 뒤로 갈수록 자막-음성이
        # 어긋나고, 반올림이 누적돼 마지막에 음성이 살짝 잘리는 문제가 있었다.
        category = _title_category_anchor(title)
        # 상단 고정 타이틀 — 모든 슬라이드에 같은 글자가 박혀 시선의 기준점이 된다.
        title_sub, title_main = _title_block(title, category)
        log.info(f"타이틀 블록: {title_sub!r} / {title_main!r}" if title_main else "타이틀 블록 없음(카테고리 미확정)")
        _LAST_META["category"] = category
        segments = _build_segments(title, valid_products, valid_reasons,
                                   category=category, targets=valid_targets,
                                   target_is_criteria=target_is_criteria)

        # 슬라이드 이미지 배정.
        # 상품을 특정해서 말하는 구간(상품 공개/핵심 장점/추천 대상/정리)은 반드시
        # 히어로 이미지여야 한다 — 여기서 다른 상품이 뜨면 설명란 링크와 화면이
        # 어긋나 시청자가 다른 걸 산 줄 안다.
        # 반대로 카테고리 얘기를 하는 구간([1] "종류가 너무 많죠", 마지막 CTA
        # "뭐 쓰세요?")은 다른 상품 사진을 써서 화면을 바꾼다. 예전엔 7슬라이드 중
        # 6개가 같은 사진이라 36초가 사실상 정지화면이었다.
        # 세그먼트 개수는 본문에 장점/추천 문장이 있느냐에 따라 달라지므로 고정
        # 인덱스로 세지 않고, 항상 존재하는 앞 2개와 뒤 2개만 위치로 특정한다.
        n_seg = len(segments)
        slide_imgs = [img_paths[0]] * n_seg
        others = img_paths[1:] or [img_paths[0]]
        if n_seg > 1:
            slide_imgs[1] = others[0]            # [1] 문제 제시
        # 여기까지는 전부 정지 이미지 — 아래에서 일부 슬롯만 B-roll 영상으로 교체된다.
        is_video = [False] * n_seg

        # 마지막 CTA 슬라이드에 **다른 상품 사진**은 쓰지 않는다. 영상이 끝나며 남는
        # 마지막 화면이 설명란 링크와 다른 브랜드면(실측: 쿠첸 링크인데 마지막 화면은
        # 쿠쿠) 시청자가 무엇을 사는 건지 헷갈린다. 대신 아래에서 상품이 아닌
        # 생활 장면(B-roll)으로 채우고, B-roll을 못 구하면 히어로 사진으로 남는다.
        seg_paths, seg_durs = [], []
        for i, seg_text in enumerate(segments):
            seg_path = tmp / f"seg_{i}.mp3"
            _synthesize_tts(seg_text, seg_path, tts_provider, voice, openai_key)
            # 무음 제거는 길이 측정 **전에** 해야 한다 — 슬라이드 길이가 이 값에서
            # 나오므로, 나중에 자르면 화면과 음성이 어긋난다.
            _trim_silence(seg_path)
            seg_paths.append(seg_path)
            seg_durs.append(_audio_duration(seg_path))
        log.info(f"세그먼트 길이(초): {[round(d, 1) for d in seg_durs]}")

        seg_paths, seg_durs = _cap_segment_durations(seg_paths, seg_durs, tmp)

        # B-roll(실사 영상)은 **상품을 특정하지 않는 구간에만** 깐다.
        # [0] 훅 — 초반 3초에 움직이는 실사 화면이 나오느냐가 이탈률을 가른다.
        # [마지막] CTA — "뭐 쓰세요?"는 카테고리 질문이라 생활 장면이 자연스럽다.
        # 상품 공개·장점·추천 구간은 절대 건드리지 않는다. 거기에 다른 물건이 나오면
        # 화면과 구매 링크가 다른 제품이 된다.
        # 세그먼트 길이가 확정된 뒤에 받아야 "이 구간보다 긴 클립"을 고를 수 있다 —
        # 짧은 클립을 루프로 늘리면 같은 동작이 반복되는 게 눈에 띈다.
        # 훅과 CTA는 검색어 자체가 갈라져 있어(broll._CATEGORY_QUERIES) 서로 다른
        # 결과 풀에서 뽑힌다. 그래도 겹칠 수 있으므로 이미 쓴 video_id를 넘겨 한 번 더 막는다
        # — 실측에서 텐트 영상의 훅과 CTA가 같은 촬영자의 거의 같은 드론샷이었다.
        # 실사 영상(B-roll)을 **쓸 수 있는 모든 구간에** 깐다.
        #
        # 정지 사진으로는 시청이 안 붙는다 — 유튜브에 이미 움직이는 영상이 널려 있어서
        # 사진 한 장을 슬라이드로 넘기는 방식은 경쟁이 안 된다(사용자 판단). 그래서
        # 상품을 **반드시** 보여줘야 하는 두 구간만 사진으로 남기고 나머지는 실사로 채운다.
        #
        # 7세그먼트 기준 (훅/문제/공개/장점/추천/정리/CTA):
        #   [0] 훅       B-roll — 초반 3초에 움직임이 없으면 거기서 이탈한다
        #   [1] 문제     B-roll — "종류가 너무 많죠"는 상황 설명이라 실사가 더 맞다
        #   [2] 공개     상품 사진 (필수) — 무엇을 파는지 여기서 정확히 보여준다
        #   [3] 장점     상품 사진 (필수) — 이 제품 고유 기능을 말하는 구간
        #   [4] 추천     B-roll — "이런 분께 잘 맞아요"는 사람과 상황 얘기다
        #   [5] 정리     B-roll — 카테고리 수준의 마무리라 상품이 없어도 된다
        #   [6] CTA      B-roll — "뭐 쓰세요?"는 카테고리 질문이다
        #
        # [2][3]까지 실사로 바꾸면 화면의 물건과 설명·구매 링크가 어긋난다. 거기가 한계선이다.
        if n_seg <= 4:
            broll_slots = [(0, "hook")]
        elif n_seg < 7:
            broll_slots = [(0, "hook"), (n_seg - 1, "cta")]
        else:
            broll_slots = [(0, "hook"), (1, "hook"),
                           (n_seg - 3, "cta"), (n_seg - 2, "cta"), (n_seg - 1, "cta")]
        # 갈등 문장("모두에게 맞는 건 아니에요")도 상품이 아니라 상황 얘기라 실사로 채운다.
        # 위 슬롯은 위치로만 정해져 있어서 이 구간이 상품 사진으로 남는데, 그러면 바로
        # 앞 [장점]과 **같은 사진**이 되어 아래 runs 병합에 흡수된다 — 실측: 폼롤러
        # 영상에서 상품 사진 한 장이 18.4초(전체 38.1초의 절반) 동안 정지해 있었다.
        # 화면을 꺾어줘야 "여기서 갈립니다"가 말로만 끝나지 않는다.
        # _TENSION은 닫힌 문구 집합이라 텍스트로 되짚어도 안전하다.
        tension_slots = [i for i, t in enumerate(segments) if t in _TENSION]
        broll_slots += [(i, "hook") for i in tension_slots
                        if i not in {s for s, _r in broll_slots}]
        used_broll_ids: set[str] = set()
        for slot, role in broll_slots:
            bpath = tmp / f"broll_{slot}.mp4"
            got = broll.fetch(category, bpath, media_keys, slot=role,
                              seed=_stable_seed(title) + slot,
                              min_duration=seg_durs[slot],
                              exclude_ids=used_broll_ids)
            if got:
                slide_imgs[slot], vid = got
                is_video[slot] = True
                used_broll_ids.add(vid)
        # 실제로 쓴 클립의 소스만 설명란 크레딧에 넣는다 — 안 쓴 소스를 적으면 거짓이다.
        _LAST_META["broll_ids"] = sorted(used_broll_ids)
        total_dur = sum(seg_durs)
        log.info(f"내레이션 총 길이: {total_dur:.1f}초")

        audio_path = tmp / "narration.m4a"  # AAC로 재인코딩하므로 컨테이너도 맞춰준다
        _concat_audio(seg_paths, audio_path, tmp)

        # 배경음악을 내레이션 아래에 깐다. 없으면 말이 끊긴 구간이 그대로 정적이 되어
        # 같은 화면이어도 훨씬 심심하게 들린다(우리 영상은 오디오 트랙이 1개뿐이었다).
        # 실패하면 원본 내레이션을 그대로 쓴다 — BGM은 부가 요소라 여기서 멈추면 안 된다.
        bgm_track = bgm_lib.pick(_stable_seed(title))
        if bgm_track:
            mixed = tmp / "narration_bgm.m4a"
            if bgm_lib.mix(audio_path, mixed, bgm_track, total_dur, tmp):
                audio_path = mixed
                _LAST_BGM[0] = bgm_track
                log.info(f"BGM: {bgm_track['title']} / {bgm_track['artist']} ({bgm_track['license']})")

        # 전환 효과 순서는 글마다 다르게 시작한다 — 채널 전체가 같은 패턴으로 보이지 않게.
        tstart = _stable_seed(title) % len(_TRANSITIONS)
        transitions = _TRANSITIONS[tstart:] + _TRANSITIONS[:tstart]

        # 사전 렌더된 상품 클립(Remotion 모션그래픽)이 있으면 정지 사진 슬라이드를
        # 통째로 대체한다. 이미 1080x1920이라 아래 crop은 그대로 통과하고, 자막/타이틀/
        # 전환/합성은 기존 경로를 그대로 쓴다 — A/V 싱크 로직을 건드리지 않는 게 요점이다.
        if product_clip is not None:
            for i in range(n_seg):
                if not is_video[i]:
                    slide_imgs[i] = product_clip
                    is_video[i] = True
            log.info(f"상품 구간을 사전 렌더 클립으로 대체: {product_clip.name}")

        # 연속한 슬라이드가 **같은 소재**면 하나의 클립으로 합친다. 같은 사진끼리
        # 슬라이드/디졸브를 걸어봐야 사진이 자기 자신 위로 지나가는 것뿐이라 의미가
        # 없다(피드백: "같은 이미지를 슬라이더 할 필요가 없지 않나"). 자막은 이미
        # 합성 후 절대 시각으로 그리므로 클립을 합쳐도 타이밍에 영향이 없다.
        runs: list[tuple[Path, bool, float]] = []
        for img_path, seg_dur, vid_flag in zip(slide_imgs, seg_durs, is_video):
            if runs and runs[-1][0] == img_path and runs[-1][1] == vid_flag:
                prev = runs[-1]
                runs[-1] = (prev[0], prev[1], prev[2] + seg_dur)
            else:
                runs.append((img_path, vid_flag, seg_dur))
        # runs는 **합쳐진 뒤의 클립 수**다. 전환은 그 사이사이에만 걸리므로 하나 적다.
        log.info(f"세그먼트 {len(segments)}개 → 클립 {len(runs)}개 "
                 f"(화면 전환 {max(len(runs) - 1, 0)}개)")

        clips = []
        n_slides = len(runs)
        for i, (img_path, vid_flag, seg_dur) in enumerate(runs):
            clip_path = tmp / f"clip_{i}.mp4"
            # 자막은 반드시 그 슬라이드의 내레이션(seg_text)과 완전히 같은 문자열로 만든다
            # — 이름/가격만 따로 자막을 만들면 음성으로 말하는 훅·구매 이유가 화면엔
            # 전혀 안 보이는 불일치가 생긴다.
            #
            # 마지막을 뺀 클립은 **전환 길이만큼 더 길게** 렌더한다. xfade가 두 클립을
            # 그만큼 겹쳐 먹으므로, 이 여유분이 있어야 최종 길이가 내레이션과 정확히
            # 같아진다(_assemble 참고). 자막 타이밍은 seg_dur 기준 그대로라 음성과
            # 어긋나지 않고, 마지막 줄만 전환이 끝날 때까지 붙잡아 둔다.
            extra = _TRANSITION_DUR if i < n_slides - 1 else 0.0
            _make_slide_clip(img_path, seg_dur, clip_path, tmp,
                             is_video=vid_flag, hold_until=seg_dur + extra)
            clips.append(clip_path)

        _LAST_META["hook"] = segments[0] if segments else ""

        # 자막 큐를 **전체 타임라인 절대 시각**으로 만든다. 클립 안이 아니라 합성 후에
        # 그리므로, 각 세그먼트 시작 시각을 더해줘야 음성과 맞는다.
        cues: list[tuple[str, float, float]] = []
        elapsed = 0.0
        for seg_text, seg_dur in zip(segments, seg_durs):
            for line, t0, t1 in _caption_cues(seg_text, seg_dur):
                cues.append((line, elapsed + t0, elapsed + t1))
            elapsed += seg_dur

        _assemble(clips, audio_path, out_path, tmp, [r[2] for r in runs], transitions, cues,
                  title_sub=title_sub, title_main=title_main)

    log.info(f"영상 생성 완료: {out_path}")
    return out_path


# ── 업로드 메타데이터 ────────────────────────────────────────────────────────
#
# 참고한 쇼핑쇼츠 제작 스펙의 요구사항:
#   제목    "클릭을 유도하는 문구 + 검색 키워드 #키워드" 형식
#   본문    검색 키워드가 들어가도록 3~8줄
#   해시태그 검색 키워드 5개 필수
#
# 예전엔 블로그 제목을 그대로 썼는데("2026년 전기밥솥 추천 TOP 5 #Shorts"), 그건 검색용
# 제목이지 피드에서 손가락을 멈추게 하는 문구가 아니다. 훅은 이미 문제·감정 중심으로
# 만들어 두었으므로(_HOOKS_PROBLEM 등) 그대로 제목에 쓴다.
_YT_TITLE_MAX = 100      # 유튜브 제목 길이 상한(해시태그 포함)


def _search_keywords(category: str) -> list[str]:
    """카테고리에서 검색 키워드 5개를 만든다."""
    c = (category or "").strip()
    if not c:
        return ["쇼핑", "추천템", "생활꿀템", "가성비", "쿠팡추천"]
    return [c, f"{c}추천", f"{c}순위", f"{c}가성비", "생활꿀템"]


def _youtube_description(*, hook: str, category: str, products: list[dict],
                         hero_link: str, blog_url: str, linkinbio_url: str,
                         duration: float, credits: list[str] | None = None,
                         long_url: str = "") -> str:
    """쇼츠 설명란.

    유튜브는 접힌 상태에서 **앞 2~3줄만** 보여준다. 그 자리에 같은 말을 두 번 쓰면
    안 된다 — 예전 설명란은 1줄이 훅("덤벨세트 살 때 뭐부터 보세요?"), 2줄이
    "덤벨세트 고를 때 뭘 보는지 40초로 정리했습니다"로 사실상 같은 문장이었다.

    그리고 그 "40초"는 하드코딩이었다. 실제 영상은 27~38초라 매번 틀린 숫자가
    나갔다. 지금은 실측 길이를 반올림해서 쓴다.

    본문에 **영상에서 소개한 제품 목록**을 넣는다. 영상은 히어로 하나만 보여주지만
    글에는 5개가 있으므로, 나머지를 찾을 수 있게 블로그 링크를 같이 건다 —
    쇼츠에서 바로 사지 않는 사람도 블로그로 넘어가면 비교표를 본다.

    **쿠팡 링크를 직접 넣지 않는다.** 유튜브는 쇼츠 설명란·댓글의 URL 을 클릭할 수
    없게 막았고(2023-08~), 제휴 링크만 반복 게시하는 계정은 스팸 정책 대상이다.
    그래서 쇼츠는 "프로필 링크(추천 모음) → 블로그 비교글 → 구매"로 보낸다. 주소는
    텍스트로만 남긴다. `hero_link` 는 호출부 호환을 위해 받기만 한다.
    관련 롱폼이 있으면 `long_url` 로 넘긴다 — 쇼츠에서 롱폼으로 가는 게 정석 퍼널이다.

    제휴 고지는 **생략할 수 없다**(공정위 심사지침 + 쿠팡 파트너스 정책).
    링크인바이오·블로그를 거쳐 제휴 링크로 이어지므로 여전히 필요하다."""
    secs = max(int(round(duration)), 1)
    lines = [
        (hook or f"{category} 고르는 법").rstrip("."),
        f"{category or '추천 상품'} 고를 때 뭘 보고 골라야 하는지 {secs}초로 정리했습니다.",
    ]

    names = [(_clean_name(p.get("name", "")) or "").strip() for p in (products or [])]
    names = [n for n in names if n][:5]
    if names:
        lines += ["", "영상에서 다룬 제품"]
        lines += [f"{i}. {n[:44]}" for i, n in enumerate(names, 1)]

    lines += ["", "▸ 1위 제품과 전체 비교표는 채널 프로필 링크(추천 모음)에 있습니다."]
    if long_url:
        lines.append(f"▸ 자세한 비교 영상: {long_url}")
    if blog_url:
        lines.append(f"▸ 비교표·가격 이력: {blog_url}")
    if linkinbio_url:
        lines.append(f"▸ 추천 모음: {linkinbio_url}")

    # #Shorts 는 쇼츠 피드 분류에 쓰인다. 나머지는 검색어와 맞춘다.
    tags = ["#Shorts"] + [f"#{t.replace(' ', '')}" for t in _search_keywords(category)[:3]]
    lines += ["", " ".join(tags)]

    lines += ["", "이 영상은 쿠팡 파트너스 활동의 일환으로, 이를 통해 소정의 수수료를 지급받을 수 있습니다."]
    if credits:
        lines += [""] + list(credits)
    return "\n".join(lines)


def _youtube_title(hook: str, category: str) -> str:
    """클릭 유도 문구(훅) + 검색 키워드 해시태그."""
    lead = re.sub(r"[.!?]+$", "", (hook or "").strip()) or (category or "추천 상품")
    kws = _search_keywords(category)[:2]
    tags = " ".join(f"#{k}" for k in kws)
    title = f"{lead} {tags}".strip()
    if len(title) > _YT_TITLE_MAX:
        # 해시태그는 검색에 필요하니 지키고 앞 문구를 줄인다.
        room = _YT_TITLE_MAX - len(tags) - 1
        title = f"{lead[:max(room, 0)].rstrip()} {tags}"
    return title


def main():
    ap = argparse.ArgumentParser(description="발행글 → 유튜브 쇼츠 생성 + 업로드")
    ap.add_argument("--post-json", required=True, help="post 데이터 JSON 파일 경로 (id, title, html_content 포함)")
    ap.add_argument("--post-url", required=True, help="원본 발행글 URL (설명란에 포함)")
    ap.add_argument("--tts-provider", choices=["edge", "openai"], default="edge")
    ap.add_argument("--voice", default="")
    ap.add_argument("--openai-key", default="")
    ap.add_argument("--privacy", choices=["unlisted", "public", "private"], default="unlisted")
    ap.add_argument("--dry-run", action="store_true", help="영상만 로컬에 생성, 업로드는 하지 않음")
    ap.add_argument("--force", action="store_true", help="이미 업로드된 글이어도 재처리")
    ap.add_argument("--product-clip", default="",
                    help="상품 구간을 대체할 사전 렌더 mp4 (Remotion 하이브리드용)")
    ap.add_argument("--pexels-key", default="",
                    help="Pexels API 키 (미지정 시 PEXELS_API_KEY 환경변수 → credentials/media.json 순으로 탐색). "
                         "없으면 B-roll 없이 상품 이미지만으로 렌더링한다.")
    ap.add_argument("--long-url", default="",
                    help="관련 롱폼 영상 주소 (있으면 설명란에 넣는다 — 쇼츠→롱폼→블로그 퍼널)")
    ap.add_argument("--linkinbio-url", default=DEFAULT_LINKINBIO_URL,
                     help="설명란에 넣을 링크인바이오 주소 (기본: NAS 설정값과 동일)")
    args = ap.parse_args()

    post = json.loads(Path(args.post_json).read_text(encoding="utf-8"))
    post_id = int(post["id"])
    title = post["title"]
    html = post["html_content"]

    existing = state_store.get(post_id)
    if existing and not args.force:
        log.info(f"[post#{post_id}] 이미 업로드됨: {existing.get('url')}")
        print(existing.get("url", ""))
        return

    video_path = render_video(post_id, title, html, args.tts_provider, args.voice,
                              args.openai_key, broll.load_keys(args.pexels_key),
                              product_clip=Path(args.product_clip) if args.product_clip else None)
    if not video_path:
        sys.exit(1)

    if args.dry_run:
        log.info("--dry-run 지정됨 — 업로드 생략")
        print(str(video_path))
        return

    import youtube_upload
    # 소재 출처. Pexels는 표기가 의무는 아니지만 권장이고, ccMixter의 CC BY 음원은
    # **표기가 의무**다 — 링크까지 있어야 라이선스를 지킨 것이 된다.
    credits = broll.attribution_for(_LAST_META["broll_ids"])
    if _LAST_BGM[0]:
        credits.append(bgm_lib.credit(_LAST_BGM[0]))
    category = _LAST_META["category"]
    keywords = _search_keywords(category)
    yt_title = _youtube_title(_LAST_META["hook"], category)
    # 설명란은 `_youtube_description` 하나로 만든다(캐릭터 쇼츠와 같은 규칙).
    # 예전엔 여기서 따로 조립하면서 쿠팡 딥링크를 바로 넣고 "40초"를 하드코딩했다 —
    # 쇼츠 설명란 링크는 클릭이 안 되고, 실제 길이는 27~38초였다.
    description = _youtube_description(
        hook=_LAST_META["hook"] or title, category=category,
        products=_extract_products_from_post(html), hero_link="",
        blog_url=args.post_url, linkinbio_url=args.linkinbio_url,
        duration=_video_duration_by_frames(video_path), credits=credits,
        long_url=args.long_url)
    result = youtube_upload.upload(
        video_path,
        title=yt_title,
        description=description,
        tags=keywords + ["Shorts"],
        privacy=args.privacy,
    )
    state_store.record(post_id, {
        "youtube_video_id": result["video_id"],
        "url": result["url"],
        "title": title,
        "published_at": datetime.datetime.now().isoformat(),
    })
    log.info(f"업로드 완료: {result['url']}")
    print(result["url"])


if __name__ == "__main__":
    main()
