"""Pexels에서 카테고리에 맞는 세로 실사 영상(B-roll)을 받아온다.

왜 필요한가 — 쿠팡 제휴 API는 상품당 이미지를 1장만 준다(productImage). 그래서 영상
전체가 사진 한 장에 줌만 걸린 화면이 되는데, 조회수가 잘 나오는 쇼츠는 사람이 실제로
쓰는 장면이 움직이며 1~3초마다 화면이 바뀐다. 초반 3초에 움직임이 없으면 거기서 이탈한다.

왜 하필 Pexels인가 — 상품 영상을 외부(1688 등)에서 긁어오는 방식은 두 가지가 걸린다.
(1) 기술적으로 1688은 봇 차단(x5secdata punish)에 바로 걸려 자동 수집이 안 되고,
(2) 더 중요하게는 1688 물건은 중국 도매 OEM이라 우리가 링크하는 국내 브랜드 SKU와
    **다른 제품**이다 — 화면의 물건과 구매 링크의 물건이 다르면 그 자체로 오인이다.
Videvo는 403, Openverse는 영상 미취급, Mixkit은 API가 없다. Pixabay는 키가 발급되어
**두 번째 소스로 붙여 두었지만 어디까지나 폴백이다** — 실측한 인벤토리가 얇다:
`neck shoulder massage`는 기린·백조 목이 나왔고(태그에 neck만 걸림), `air fryer cooking`
`foot massage` `vacuum cleaner home`은 관련 영상이 사실상 없었다. 그래서 Pixabay는
검색어 단어가 **태그에 2개 이상** 걸릴 때만 채택한다 — 걸리지 않으면 조용히 포기한다.
무관한 화면을 억지로 넣느니 상품 사진이 낫다는 원칙은 여기서도 같다.
Coverr는 발급된 키가 401(Invalid API_KEY)로 거부되어 아직 붙이지 않았다 — 검증할 수
없는 소스를 미리 배선해두면 실패 경로만 늘어난다.

그래서 **상품을 특정해서 말하는 구간에는 절대 쓰지 않는다.** B-roll은 상품이 아니라
상황을 보여주는 용도다 — 훅("아직도 고민 중이세요?")과 마지막 CTA("뭐 쓰세요?")처럼
카테고리 얘기를 하는 구간에만 깔린다. 상품 공개·장점·추천 구간은 언제나 실제 쿠팡
상품 사진이어야 한다.

API 키: --pexels-key > 환경변수 PEXELS_API_KEY > credentials/pexels.json 순으로 찾는다.
키가 없으면 조용히 None을 돌려주고, 호출부는 기존 상품 이미지로 폴백한다 — B-roll은
어디까지나 부가 요소라 키가 없다고 영상 생성 자체가 실패하면 안 된다.
"""
import json
import logging
import os
from pathlib import Path

import httpx

log = logging.getLogger("youtube_shorts.broll")

HERE = Path(__file__).parent
CACHE_DIR = HERE / "cache" / "broll"
# 대시보드 설정(state.json의 media 블록)을 그대로 내려받은 파일. 소스가 늘어날 때마다
# 파일을 하나씩 더 만들지 않도록 한 파일에 모아둔다.
CRED_PATH = HERE / "credentials" / "media.json"
# 이전 버전이 쓰던 Pexels 전용 파일 — 남아 있으면 계속 읽는다.
LEGACY_PEXELS_PATH = HERE / "credentials" / "pexels.json"

PEXELS_URL = "https://api.pexels.com/videos/search"
PIXABAY_URL = "https://pixabay.com/api/videos/"
COVERR_URL = "https://api.coverr.co/videos"

# 소스별 크레딧 문구. 실제로 쓴 소스만 설명란에 넣는다 — 안 쓴 소스를 적으면 거짓이다.
ATTRIBUTIONS = {
    "px": "영상 소재: Pexels (https://www.pexels.com)",
    "pb": "영상 소재: Pixabay (https://pixabay.com)",
    "cv": "영상 소재: Coverr (https://coverr.co)",
}
_SOURCE_ORDER = ("px", "pb", "cv")
# 하위 호환 — 예전 호출부가 참조하던 이름.
ATTRIBUTION = ATTRIBUTIONS["px"]


def attribution_for(clip_ids) -> list[str]:
    """실제로 사용한 클립 id들로부터 필요한 크레딧 문구만 뽑는다."""
    used = {str(cid).split(":", 1)[0] for cid in clip_ids}
    return [ATTRIBUTIONS[k] for k in _SOURCE_ORDER if k in used]

# ── 카테고리 → (훅 검색어, CTA 검색어) ──────────────────────────────────────
#
# 키는 modules/trend/product_discovery.CATEGORIES 72개를 그대로 옮긴 것이다.
# 파이프라인이 만들 수 있는 카테고리가 유한하고 이미 알려져 있으므로, 번역이나 추론
# 없이 전부 직접 매핑한다.
#
# 왜 광역 검색어를 버렸나 — 예전엔 "생활가전 → home lifestyle daily" 식으로 뭉뚱그렸는데
# 실측 결과가 나빴다. `home lifestyle daily`는 발마사지기·선풍기·자전거 어디에 써도
# 주방/카페/식탁 장면만 나왔고(3개 카테고리가 동일한 결과), `foot massage`로 바꾸자
# 상위 4개가 전부 실제 발 마사지 장면이었다. 인벤토리가 없던 게 아니라 검색어가
# 뭉툭했던 것이다.
#
# 왜 검색어가 2개인가 — 슬롯마다 결과 풀을 갈라놓기 위해서다. 같은 검색어에 seed만
# 바꾸면 같은 결과 목록에서 고르게 되는데, Pexels는 한 촬영자가 같은 장소에서 찍은
# 시리즈를 연달아 돌려주는 일이 잦다(`kitchen cooking home`은 상위 5개가 전부 동일
# 촬영자였고, 실제로 텐트 영상은 훅과 CTA가 거의 같은 드론샷이었다).
# 첫 번째는 훅용 — "그래서 뭐가 불편한가"를 보여주는 사용/문제 장면.
# 두 번째는 CTA용 — "뭐 쓰세요?"에 얹을, 그 물건을 쓰고 난 뒤의 차분한 장면.
#
# 두 검색어 모두 **구체적인 사물이나 동작**을 반드시 포함한다. 추상적인 표현을 쓰면
# 아래 슬러그 필터로도 못 막는다 — 실측에서 "hot summer heat"는 불꽃 배경·실험실 비커·
# 주전자만 돌려줬고(선풍기는 하나도 없었다), "muscle recovery rest"는 폰 보는 남성이
# 걸렸다. 검색어에 주어가 없으면 Pexels가 채울 재료 자체가 없다.
_CATEGORY_QUERIES: dict[str, tuple[str, str]] = {
    # 생활가전
    "무선청소기":   ("vacuum cleaner home",       "cleaning floor home"),
    "로봇청소기":   ("robot vacuum floor",        "vacuum cleaning carpet"),
    "공기청정기":   ("air purifier room",         "open window fresh air"),
    "가습기":       ("humidifier steam room",     "sleeping bedroom night"),
    "제습기":       ("rain window humid",         "wet laundry indoor"),
    "선풍기":       ("electric fan summer",       "woman relaxing fan"),
    "전기요":       ("warm blanket bed",          "winter blanket sofa"),
    "온수매트":     ("warm bed blanket",          "sleeping warm bed"),
    "빨래건조대":   ("laundry drying clothes",    "folding clothes laundry"),
    "스탠드조명":   ("desk lamp light",           "reading lamp night"),
    # 음향
    "블루투스이어폰": ("wireless earbuds music",  "headphones walking street"),
    "블루투스스피커": ("bluetooth speaker music", "speaker music room"),
    # 주방
    "전기포트":     ("kettle boiling water",      "pouring tea cup"),
    "에어프라이어": ("air fryer cooking",         "fried potato snack"),
    "커피머신":     ("coffee machine espresso",   "pouring coffee cup"),
    "전기밥솥":     ("cooking rice pot",          "steamed rice bowl"),
    "인덕션":       ("induction cooktop pan",     "boiling pot stove"),
    "믹서기":       ("blender smoothie fruit",    "pouring smoothie glass"),
    "토스터기":     ("toast bread breakfast",     "breakfast bread table"),
    "전기그릴":     ("grilling meat pan",         "grilled meat plate"),
    "밀폐용기":     ("food container meal prep",  "packing lunch box"),
    "칼세트":       ("chef knife chopping",       "cutting vegetables board"),
    "프라이팬":     ("frying pan cooking",        "cooked food pan"),
    "냄비세트":     ("cooking pot soup",          "soup bowl table"),
    # PC / 디지털
    "노트북거치대": ("laptop desk setup",         "typing laptop desk"),
    "모니터암":     ("computer monitor desk",     "office desk monitor"),
    "게이밍마우스": ("gaming mouse computer",     "gaming setup keyboard"),
    "기계식키보드": ("mechanical keyboard typing", "typing keyboard desk"),
    "웹캠":         ("video call laptop",         "online meeting screen"),
    "USB허브":      ("laptop cable desk",         "connecting cable laptop"),
    "보조배터리":   ("phone charging battery",    "using phone outdoor"),
    "무선충전기":   ("wireless charging phone",   "phone charging desk"),
    "노트북파우치": ("laptop bag carrying",       "laptop cafe table"),
    "공유기":       ("wifi router internet",      "using laptop sofa"),
    "외장하드":     ("hard drive data",           "laptop files working"),
    "SSD":          ("computer hardware parts",   "building computer desk"),
    "마우스패드":   ("computer mouse desk",       "hand mouse working"),
    "USB메모리":    ("usb flash drive",           "plugging usb laptop"),
    # 미용 / 건강
    "전동칫솔":     ("brushing teeth bathroom",   "bathroom mirror morning"),
    "면도기":       ("man shaving bathroom",      "shaving face mirror"),
    "헤어드라이기": ("blow drying hair",          "brushing hair mirror"),
    "고데기":       ("hair styling curling",      "curly hair woman"),
    "안마기":       ("shoulder massage relax",    "massage back relax"),
    "체중계":       ("weight scale fitness",      "healthy salad bowl"),
    "발마사지기":   ("foot massage",              "resting feet sofa"),
    "목마사지기":   ("neck shoulder massage",     "neck pain office"),
    "제모기":       ("skin care legs",            "smooth skin legs"),
    "손톱깎이세트": ("nail care manicure",        "manicure hands table"),
    # 캠핑 / 운동
    "캠핑의자":     ("camping chair outdoor",     "campfire night friends"),
    "텐트":         ("camping tent nature",       "tent mountain morning"),
    "등산화":       ("hiking boots trail",        "hiking mountain path"),
    "런닝화":       ("running shoes street",      "running park morning"),
    "요가매트":     ("yoga mat exercise",         "yoga stretching floor"),
    "덤벨세트":     ("dumbbell workout home",     "lifting dumbbell gym"),
    "폼롤러":       ("stretching foam roller",    "yoga mat stretching floor"),
    "텀블러":       ("tumbler coffee travel",     "water bottle desk"),
    "아이스박스":   ("cooler box picnic",         "picnic beach summer"),
    "캠핑테이블":   ("camping table outdoor",     "picnic table food"),
    "배드민턴라켓": ("badminton playing sport",   "badminton court game"),
    "자전거헬멧":   ("bicycle helmet cycling",    "cycling road morning"),
    "스트레칭밴드": ("resistance band exercise",  "stretching band home"),
    "짐볼":         ("exercise ball workout",     "pilates ball gym"),
    "줄넘기":       ("jump rope exercise",        "skipping rope outdoor"),
    # 차량
    "차량용청소기": ("car interior cleaning",     "cleaning car seat"),
    "차량용거치대": ("phone car mount",           "driving car navigation"),
    "블랙박스":     ("driving car road",          "car driving highway"),
    "차량용방향제": ("car interior clean",        "car dashboard sunlight"),
    "타이어공기주입기": ("car tire wheel",        "checking tire car"),
    # 반려동물
    "고양이모래":   ("cat litter home",           "cat resting home"),
    "강아지사료":   ("dog eating food",           "dog playing home"),
    "펫드라이룸":   ("dog bath grooming",         "drying dog towel"),
    "고양이스크래처": ("cat scratching play",     "cat playing home"),
}

# 제목에서 뽑은 카테고리는 위 72개와 글자가 다를 수 있다("휴대용선풍기"는 "선풍기"를
# 포함하므로 부분일치로 잡히지만, "자전거타이어"는 어느 키의 부분문자열도 아니다).
# 부분일치로도 안 잡히는 것 중 실제로 나왔던 표현만 골라 별칭으로 둔다.
_ALIASES: dict[str, str] = {
    "자전거":   "자전거헬멧",
    "마사지기": "안마기",
    "청소기":   "무선청소기",
    "이어폰":   "블루투스이어폰",
    "스피커":   "블루투스스피커",
    "키보드":   "기계식키보드",
    "마우스":   "게이밍마우스",
    "충전기":   "무선충전기",
    "조명":     "스탠드조명",
    "커피":     "커피머신",
    "밥솥":     "전기밥솥",
    "보온병":   "텀블러",
    "물병":     "텀블러",
    "등산":     "등산화",
    "러닝화":   "런닝화",
    "캠핑":     "캠핑의자",
}

# 긴 키부터 검사해야 "전기밥솥"이 "밥솥"보다 먼저 잡힌다.
_MATCH_KEYS = sorted(_CATEGORY_QUERIES, key=len, reverse=True)
_ALIAS_KEYS = sorted(_ALIASES, key=len, reverse=True)


def queries_for_category(category: str) -> tuple[str, str] | None:
    """(훅 검색어, CTA 검색어). 매핑이 없으면 None — 이때는 B-roll을 쓰지 않는다.

    예전엔 못 찾으면 `home lifestyle daily`로 채웠는데, 발마사지기 영상에 앞치마 두른
    사람이 나오는 식으로 오히려 손해였다. 무관한 화면을 억지로 넣느니 상품 사진에
    Ken Burns를 거는 편이 낫다."""
    cat = (category or "").strip()
    if not cat:
        return None
    if cat in _CATEGORY_QUERIES:
        return _CATEGORY_QUERIES[cat]
    for key in _MATCH_KEYS:
        if key in cat or cat in key:
            return _CATEGORY_QUERIES[key]
    for alias in _ALIAS_KEYS:
        if alias in cat:
            return _CATEGORY_QUERIES[_ALIASES[alias]]
    return None


def canonical_category(category: str) -> str:
    """`_CATEGORY_QUERIES`의 정규 키를 돌려준다(없으면 입력 그대로).

    한국어 검색어로 쓸 말을 고를 때 필요하다. 제목에서 뽑은 카테고리는 "휴대용선풍기"
    처럼 변형일 수 있는데, Pexels에 그대로 넣으면 번역이 더 어긋난다 — 정규 키인
    "선풍기"가 더 안정적이다."""
    cat = (category or "").strip()
    if not cat:
        return ""
    if cat in _CATEGORY_QUERIES:
        return cat
    for key in _MATCH_KEYS:
        if key in cat or cat in key:
            return key
    for alias in _ALIAS_KEYS:
        if alias in cat:
            return _ALIASES[alias]
    return cat


def find_known_category(text: str) -> str:
    """텍스트 안에 들어있는 알려진 카테고리 이름을 돌려준다(긴 것 우선, 없으면 "").

    제목이 랭킹형("2026년 텐트 추천 TOP 5")이 아니면 make_shorts의 정규식이 카테고리를
    못 뽑는다 — 실측: "겨울철 필수템, 합리적인 소비를 위한 가성비 가습기 추천 및 구매
    가이드"가 빈 값이 나와 B-roll도 내레이션의 {category}도 통째로 죽었다.
    카테고리 집합이 유한하니 제목에서 직접 찾으면 된다."""
    t = text or ""
    for key in _MATCH_KEYS:
        if key in t:
            return key
    for alias in _ALIAS_KEYS:
        if alias in t:
            return _ALIASES[alias]
    return ""


def load_keys(cli_pexels: str = "") -> dict[str, str]:
    """소스별 API 키. 없는 소스는 키가 빈 문자열이고, 그 소스는 건너뛴다.

    B-roll은 부가 요소라 키가 하나도 없어도 영상 생성 자체는 성공해야 한다 —
    호출부는 상품 이미지로 폴백한다."""
    keys: dict[str, str] = {"pexels": "", "pixabay": "", "coverr": ""}

    if CRED_PATH.exists():
        try:
            data = json.loads(CRED_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"미디어 키 파일을 읽지 못함 [{CRED_PATH}]: {e}")
            data = {}
        for name in keys:
            block = data.get(name) or {}
            # 대시보드의 "B-roll 활성화" 토글을 그대로 반영한다 — 키를 지우지 않고도 끌 수
            # 있어야 한다(끄는 이유가 "키가 틀려서"가 아니라 "이번엔 안 쓰고 싶어서"일 때가 많다).
            # enabled 키 자체가 없으면 켜진 것으로 본다(수동으로 만든 파일 호환).
            if block.get("enabled", True) is False:
                continue
            keys[name] = (block.get("api_key") or "").strip()

    # 예전 Pexels 전용 파일 — media.json에 없을 때만 본다.
    if not keys["pexels"] and LEGACY_PEXELS_PATH.exists():
        try:
            data = json.loads(LEGACY_PEXELS_PATH.read_text(encoding="utf-8"))
            if data.get("enabled", True) is not False:
                keys["pexels"] = (data.get("api_key") or "").strip()
        except (json.JSONDecodeError, OSError) as e:
            log.warning(f"Pexels 키 파일을 읽지 못함 [{LEGACY_PEXELS_PATH}]: {e}")

    # 명시 인자와 환경변수가 파일보다 우선한다.
    env = os.environ.get("PEXELS_API_KEY", "").strip()
    if env:
        keys["pexels"] = env
    if cli_pexels:
        keys["pexels"] = cli_pexels
    env = os.environ.get("PIXABAY_API_KEY", "").strip()
    if env:
        keys["pixabay"] = env
    env = os.environ.get("COVERR_API_KEY", "").strip()
    if env:
        keys["coverr"] = env
    return keys


def load_api_key(cli_key: str = "") -> str:
    """하위 호환 — Pexels 키만 돌려준다."""
    return load_keys(cli_key)["pexels"]


def _pick_file(video: dict) -> dict | None:
    """Pexels 한 영상의 여러 화질 중 1080x1920에 가장 가까운 세로 파일을 고른다.

    4K 원본을 그대로 받으면 다운로드가 수십 MB로 커지고 어차피 1080x1920으로 크롭하며
    버린다. 세로가 아닌 파일은 크롭하면 좌우가 크게 잘려나가므로 아예 제외한다."""
    portrait = [f for f in video.get("video_files", [])
                if f.get("height", 0) > f.get("width", 0) and f.get("link")]
    if not portrait:
        return None
    return min(portrait, key=lambda f: abs(f["height"] - 1920) + abs(f["width"] - 1080))


# Pexels 결과는 관련도순이지만 뒤로 갈수록 급격히 어긋난다. 실측(`per_page=15`):
#   electric fan summer  13위 → "live music performance with electric guitarist" ("electric"만 걸림)
#   cooking rice pot     12위 → "delicious indian biryani with papad" (실제로 이게 뽑혀서 밥솥 영상에 커리가 나왔다)
# 그런데 Pexels URL 슬러그가 영상 내용을 그대로 적어둔다
# (https://www.pexels.com/video/aerial-view-of-camping-setup-in-pine-forest-35747854/).
# 그래서 (1) 검색어 단어가 슬러그에 하나도 없는 결과를 걷어내고 (2) 남은 것 중
# 상위 _RELEVANT_TOP_N개 안에서만 고른다. 다양성은 seed로 그 안에서 확보한다.
_RELEVANT_TOP_N = 8


def _tokens(query: str) -> list[str]:
    return [t for t in query.lower().split() if len(t) >= 3]


def _slug(video: dict) -> str:
    # ".../video/<슬러그>-<id>/" 형태
    parts = [p for p in (video.get("url") or "").split("/") if p]
    return parts[-1].lower() if parts else ""


def _by_relevance(videos: list[dict], query: str) -> list[dict]:
    tokens = _tokens(query)
    scored = [(sum(t in _slug(v) for t in tokens), v) for v in videos]
    # 일치 토큰이 많을수록 앞으로. 동점이면 Pexels의 원래 관련도 순서를 유지한다(안정 정렬).
    # "cooking rice pot"이면 "a-person-stirring-rice-in-a-pot"(3개)이
    # "traditional-indian-curry-and-rice-dishes"(1개)보다 앞선다.
    matched = [v for n, v in sorted(
        [(n, v) for n, v in scored if n], key=lambda pair: -pair[0])]
    # 슬러그가 검색어와 하나도 안 겹치는 경우가 전부라면(드묾) 원래 순서를 그대로 쓴다 —
    # 관련 없는 걸 넣느니 낫지만, 여기서 빈 리스트를 돌려주면 멀쩡한 결과까지 버리게 된다.
    return (matched or videos)[:_RELEVANT_TOP_N]


# ── 소스별 후보 검색 ────────────────────────────────────────────────────────
# 각 함수는 [(clip_id, 다운로드 URL, 길이, 설명)]을 관련도 순으로 돌려준다.
# clip_id에는 "px:123" / "pb:456" 처럼 소스 접두어를 붙인다 — 두 소스의 숫자 id가
# 겹칠 수 있어서 캐시 파일명과 중복 방지 집합이 서로 섞이면 안 된다.


def _pexels_request(term: str, api_key: str) -> list[dict] | None:
    """None은 '키가 거부됨'(더 시도하지 말 것), []는 '결과 없음'."""
    try:
        r = httpx.get(
            PEXELS_URL,
            params={"query": term, "orientation": "portrait", "per_page": 15},
            headers={"Authorization": api_key},
            timeout=30,
        )
        if r.status_code == 401:
            log.warning("Pexels API 키가 거부됨(401) — 이 소스는 건너뜀")
            return None
        r.raise_for_status()
        return r.json().get("videos", []) or []
    except Exception as e:
        log.warning(f"Pexels 검색 실패 [{term}]: {e}")
        return []


# Pexels는 한국어 검색어를 받아 내부에서 번역해 찾는다. 한국어를 **병행**하는 이유는
# 한 단어에 담긴 맥락이 영어 3단어보다 정확할 때가 있어서다 — `전기밥솥`은 실내 주방
# 장면을 주는데 우리 영어 검색어 `cooking rice pot`은 **야외 장작불**을 준다.
#
# 그렇다고 한국어로 갈아타면 안 된다. 실측(12개 카테고리, 영어 토큰 게이트 적용 후
# 살아남은 결과 수):
#     영어만 116건 / 한국어만 84건 / 합집합 185건
# 한국어 단독은 영어보다 **나쁘다** — `폼롤러`는 개가 누워 있는 영상(0건 통과),
# `무선충전기`는 공원 분수를 준다. 복합명사 번역이 무너지는 케이스가 꽤 있다.
# 이득은 어디까지나 **합집합**에 있다(+59%). 후보 풀이 넓어지면 글마다 다른 클립이
# 걸릴 여지가 커진다 — seed로 top 8 안에서 고르는 구조라 풀 크기가 곧 다양성이다.
#
# 관련도 채점은 **영어 검색어 토큰으로만** 한다. Pexels URL 슬러그가 영어라서
# 한국어 토큰으로는 아무것도 안 걸리고, 그러면 `_by_relevance`가 통째로 무력화되어
# (매칭 0건 → 원본 순서 그대로) 밥솥에 커리가 나오던 시절로 돌아간다.
# 실제로 이 영어 게이트가 한국어 검색의 쓰레기를 걸러준다 — `목마사지기`의
# "woman-holding-an-orange"는 massage/neck/shoulder가 하나도 없어 탈락한다.
def _search_pexels(query: str, api_key: str, min_duration: float,
                   exclude: set, ko_query: str = "") -> list[tuple]:
    videos: list[dict] = []
    seen: set = set()
    for term in ([query, ko_query] if ko_query else [query]):
        got = _pexels_request(term, api_key)
        if got is None:                  # 키 거부 — 두 번째 요청도 의미 없다
            return []
        for v in got:
            vid = v.get("id")
            if vid in seen:
                continue
            seen.add(vid)
            videos.append(v)

    videos = [v for v in videos if f"px:{v.get('id')}" not in exclude]
    # 세그먼트보다 짧은 클립은 루프가 눈에 띄게 반복되므로 가능하면 피한다.
    # 조건을 만족하는 게 하나도 없으면 길이 조건을 버린다(루프라도 있는 게 낫다).
    candidates = [v for v in videos if v.get("duration", 0) >= min_duration] or videos
    out = []
    for v in _by_relevance(candidates, query):
        vf = _pick_file(v)
        if not vf:
            continue
        out.append((f"px:{v['id']}", vf["link"], v.get("duration", 0),
                    f"{vf['width']}x{vf['height']} by "
                    f"{v.get('user', {}).get('name', '?')}"))
    return out


# Pixabay는 검색어와 무관한 결과를 관련도 상위에 섞어 돌려준다 — 태그에 단어 하나만
# 걸려도 올라온다(실측: `neck shoulder massage` 상위에 기린 목·백조 목·새의 목).
# 그래서 **태그에 검색어 단어가 2개 이상** 걸린 것만 채택한다. 이 조건에 걸리는 게
# 없으면 그 카테고리에는 Pixabay 인벤토리가 없는 것이므로 조용히 포기한다.
_PIXABAY_MIN_TAG_HITS = 2


def _search_pixabay(query: str, api_key: str, min_duration: float,
                    exclude: set) -> list[tuple]:
    try:
        r = httpx.get(
            PIXABAY_URL,
            params={"key": api_key, "q": query, "per_page": 30,
                    "safesearch": "true", "video_type": "film"},
            timeout=30,
        )
        if r.status_code in (400, 401, 403):
            log.warning(f"Pixabay API 키가 거부됨({r.status_code}) — 이 소스는 건너뜀")
            return []
        r.raise_for_status()
        hits = r.json().get("hits", []) or []
    except Exception as e:
        log.warning(f"Pixabay 검색 실패 [{query}]: {e}")
        return []

    tokens = _tokens(query)
    need = min(_PIXABAY_MIN_TAG_HITS, len(tokens)) or 1
    scored = []
    for h in hits:
        if f"pb:{h.get('id')}" in exclude:
            continue
        tags = (h.get("tags") or "").lower()
        n = sum(t in tags for t in tokens)
        if n < need:
            continue
        scored.append((n, h))
    scored.sort(key=lambda pair: -pair[0])

    out = []
    for _n, h in scored[:_RELEVANT_TOP_N]:
        files = h.get("videos") or {}
        # Pixabay는 세로 인벤토리가 거의 없다(실측: 50건 중 1~2건). 우리는 어차피
        # 정사각 카드로 센터 크롭하므로 가로 소재도 그대로 쓴다 — 다만 높이가 1080에
        # 가까운 파일을 골라 불필요하게 큰 4K를 받지 않는다.
        best = None
        for key in ("large", "medium", "small", "tiny"):
            f = files.get(key) or {}
            if not f.get("url"):
                continue
            if best is None or abs(f.get("height", 0) - 1080) < abs(best.get("height", 0) - 1080):
                best = f
        if not best:
            continue
        out.append((f"pb:{h['id']}", best["url"], h.get("duration", 0),
                    f"{best.get('width')}x{best.get('height')} by {h.get('user', '?')}"))
    # 길이 조건은 여기서도 "가능하면"이다 — 만족하는 게 없으면 조건을 버린다.
    longer = [c for c in out if c[2] >= min_duration]
    return longer or out


# Coverr는 검색어를 **AND**로 매칭한다 — 단어가 전부 들어간 영상만 돌려준다.
# 실측(무료 키, 쿼터 소진 전):
#   "cooking rice pot" 0건 / "cooking rice" 9건 / "cooking" 474건
#   "wireless charging phone" 0건 / "wireless charging" 3건 / "wireless" 72건
#   "neck shoulder massage" 0건 / "neck shoulder" 0건 / "neck" 34건
#   "air fryer cooking" 0건 / "air fryer" 0건
# 우리 검색어는 3단어라 그대로 넣으면 대부분 0건이다. 그래서 **2단어 → 1단어**로
# 좁혀가며 시도한다. 대신 단어를 줄인 만큼 무관한 결과가 섞이므로("air"는 하늘·구름이
# 2183건), 아래 태그 게이트로 **원래 3단어 중 2개 이상**이 걸린 것만 채택한다.
#
# 무료 키에는 시간당 쿼터가 있다(403 {"message":"Exceeded query limit"} — 실제로 조사
# 중에 소진시켰다). 그래서 Coverr는 **마지막 순위**다: Pexels·Pixabay가 모두 비었을
# 때만 호출해서 요청 수를 최소로 유지한다.
_COVERR_MIN_TAG_HITS = 2


def _coverr_blob(h: dict) -> str:
    return " ".join([h.get("title") or "", h.get("description") or "",
                     " ".join(h.get("tags") or [])]).lower()


def _search_coverr(query: str, api_key: str, min_duration: float,
                   exclude: set) -> list[tuple]:
    tokens = _tokens(query)
    need = min(_COVERR_MIN_TAG_HITS, len(tokens)) or 1
    words = query.split()
    # 3단어 그대로는 실측상 거의 항상 0건이라 건너뛰고 2단어부터 시작한다 — 쿼터가
    # 빠듯해서 어차피 빌 요청을 미리 태우지 않는다.
    attempts = []
    if len(words) >= 2:
        attempts.append(" ".join(words[:2]))
    attempts.append(words[0])

    hits: list[dict] = []
    for term in attempts:
        try:
            r = httpx.get(COVERR_URL,
                          params={"query": term, "page_size": 30,
                                  "urls": "true", "api_key": api_key},
                          timeout=30)
            if r.status_code == 403:
                log.warning("Coverr 쿼터 소진 또는 키 거부(403) — 이 소스는 건너뜀")
                return []
            if r.status_code == 401:
                log.warning("Coverr API 키가 거부됨(401) — 이 소스는 건너뜀")
                return []
            r.raise_for_status()
            hits = r.json().get("hits", []) or []
        except Exception as e:
            log.warning(f"Coverr 검색 실패 [{term}]: {e}")
            return []
        if hits:
            break

    scored = []
    for h in hits:
        cid = f"cv:{h.get('id')}"
        if cid in exclude:
            continue
        # API가 기본으로 무료 영상만(is_premium:false) 걸러 주지만, 유료 소재를 실수로
        # 쓰면 라이선스 위반이라 한 번 더 확인한다.
        if h.get("is_premium"):
            continue
        n = sum(t in _coverr_blob(h) for t in tokens)
        if n < need:
            continue
        scored.append((n, h))
    scored.sort(key=lambda pair: -pair[0])

    out = []
    for _n, h in scored[:_RELEVANT_TOP_N]:
        url = (h.get("urls") or {}).get("mp4")
        if not url:
            continue
        try:
            dur = float(h.get("duration") or 0)
        except (TypeError, ValueError):
            dur = 0.0
        # Coverr는 세로 소재가 거의 없다(is_vertical). 우리는 정사각 카드로 센터
        # 크롭하므로 가로 소재도 그대로 쓴다 — Pixabay와 같은 이유다.
        out.append((f"cv:{h['id']}", url, dur, f"{h.get('title', '?')}"))
    longer = [c for c in out if c[2] >= min_duration]
    return longer or out


def _download(clip_id: str, url: str, out_path: Path) -> bool:
    """캐시는 clip_id 기준 — 같은 클립이 다른 글/다른 슬롯에서 다시 걸려도 한 번만 받는다."""
    cached = CACHE_DIR / f"{clip_id.replace(':', '_')}.mp4"
    if not (cached.exists() and cached.stat().st_size > 0):
        try:
            with httpx.stream("GET", url, timeout=60, follow_redirects=True) as resp:
                resp.raise_for_status()
                CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with cached.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
        except Exception as e:
            cached.unlink(missing_ok=True)
            log.warning(f"B-roll 다운로드 실패 [{clip_id}]: {e}")
            return False
    else:
        log.info(f"B-roll 캐시 사용 [{clip_id}]")
    out_path.write_bytes(cached.read_bytes())
    return True


def fetch(category: str, out_path: Path, keys, slot: str = "hook",
          seed: int = 0, min_duration: float = 0.0,
          exclude_ids: set | None = None) -> tuple[Path, str] | None:
    """카테고리에 맞는 실사 영상 1개를 받아 out_path에 저장하고 (경로, clip_id)를 돌려준다.

    slot은 "hook" | "cta" — 검색어가 갈라져 슬롯마다 다른 결과 풀에서 고른다.
    exclude_ids는 같은 영상 안에서 이미 쓴 clip_id — 검색어를 갈라도 겹칠 수 있어
    최종 방어선으로 한 번 더 막는다.
    seed는 글마다 다른 클립이 걸리게 하는 용도다 — 항상 1등 결과만 쓰면 모든 영상이
    같은 장면으로 시작해서 채널 전체가 복붙처럼 보인다.

    소스 순서는 **Pexels → Pixabay → Coverr**이고, 앞 소스가 완전히 비었을 때만 다음으로
    넘어간다. 한 후보 풀에 합치지 않는 이유는 뒤쪽 소스의 관련도가 확연히 낮아서 섞으면
    Pexels의 좋은 결과를 밀어내기 때문이고, Coverr가 맨 뒤인 이유는 무료 키에 시간당
    쿼터가 있어 요청 수를 아껴야 하기 때문이다.

    실패(키 없음/매핑 없음/네트워크/결과 없음)하면 None. 호출부는 상품 이미지로 폴백한다."""
    if isinstance(keys, str):        # 하위 호환 — 예전엔 Pexels 키 문자열만 받았다
        keys = {"pexels": keys, "pixabay": "", "coverr": ""}
    if not any(keys.values()):
        return None
    queries = queries_for_category(category)
    if not queries:
        log.info(f"B-roll 검색어 매핑 없음 [{category}] — 상품 이미지로 진행")
        return None
    query = queries[1] if slot == "cta" else queries[0]
    exclude_ids = exclude_ids or set()

    # 한국어 병행은 Pexels에만 건다. Pixabay는 실측상 이득이 없었다 —
    # 같은 12개 카테고리 기준 영어만 68건 / 합집합 69건(+1)이라 요청만 두 배가 된다.
    # (한국어를 넣으면 `전기밥솥`이 풍력발전, `에어프라이어`가 비행기를 준다.)
    ko = canonical_category(category)
    candidates: list[tuple] = []
    for name, search in (("pexels", _search_pexels),
                         ("pixabay", _search_pixabay),
                         ("coverr", _search_coverr)):
        if not keys.get(name):
            continue
        if name == "pexels":
            candidates = _search_pexels(query, keys[name], min_duration,
                                        exclude_ids, ko_query=ko)
        else:
            candidates = search(query, keys[name], min_duration, exclude_ids)
        if candidates:
            if name != "pexels":
                log.info(f"{name}로 폴백 [{query}] — 앞 소스에 후보 없음")
            break
    if not candidates:
        log.warning(f"B-roll 후보 없음 [{query}] — 상품 이미지로 진행")
        return None

    clip_id, url, dur, desc = candidates[seed % len(candidates)]
    if not _download(clip_id, url, out_path):
        return None
    log.info(f"B-roll {slot} [{query}] {clip_id} {desc} {dur}초")
    return out_path, clip_id
