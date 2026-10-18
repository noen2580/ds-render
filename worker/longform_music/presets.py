"""카테고리별 음악 기획 — 곡마다 다른 프롬프트, 영상 제목·설명·태그.

곡이 전부 같은 프롬프트면 3시간 내내 비슷한 소리가 되고, 유튜브의 '반복·대량생산(비진정성)' 판정에도
불리하다. 그래서 악기·질감·배경 소리·조성을 조합해 곡마다 다르게 만들고, 곡 이름(챕터)도 거기서 뽑는다.
조합은 seed 로 고정해서 같은 작업을 다시 돌려도 같은 기획이 나온다(이어서 생성할 때 필요).
"""
from __future__ import annotations

import random

COMMON_TAIL = ("Instrumental only: no vocals, no singing, no humming, no spoken words, no lyrics. "
               "No drums, no percussion hits, no sudden loud moments, no abrupt changes, no silence gaps. "
               "Steady quiet volume from start to finish, soft fade-in and a long gentle fade-out. "
               "About three minutes long.")

SLEEP = {
    "name": "sleep",
    "base": ("Calm ambient sleep music, very slow tempo around 50 BPM, warm and spacious, "
             "minimal melodic movement, slowly evolving harmony"),
    # (곡 이름에 쓸 짧은 라벨, 프롬프트 조각)
    "lead": [
        ("Felt Piano", "soft felt piano notes spaced far apart"),
        ("Warm Pads", "soft sustained ambient pad chords, airy and warm"),
        ("Soft Strings", "distant muted string ensemble playing long held notes"),
        ("Ambient Guitar", "clean ambient electric guitar swells with long reverb"),
        ("Celesta", "gentle celesta and music-box tones, very sparse"),
        ("Low Drone", "deep low drone with subtle shimmering overtones"),
        ("Harp", "gentle plucked harp notes, slow and far apart"),
        ("Rhodes", "mellow electric piano chords with soft tremolo"),
    ],
    "texture": [
        ("Rain", "light steady rain in the background"),
        ("Ocean", "slow distant ocean waves"),
        ("Night", "quiet night crickets far away"),
        ("Wind", "soft wind through trees"),
        ("Still", "no nature sounds, pure tone"),
        ("Stream", "a calm gentle stream"),
    ],
    "key": ["in D major", "in F major", "in A minor", "in E-flat major", "in C major", "in B-flat major",
            "in G major", "in D minor"],
    # 제목·썸네일 글자 짝. 작업 이름으로 하나를 고른다(variant).
    # 2026-10-11 조사(research/2026-10-11-sleep-top): 최근 2년 상위 영상은 '효과 약속'으로 시작하는 약 90자 제목,
    # "N Hours" 를 제목에 넣으면 하루 조회수 중앙값 0.5배, 썸네일은 글자 없이 또는 2~3단어.
    # 의학적 주장(치료·멜라토닌 분비·DNA 등)은 쓰지 않는다 — 유튜브 의료 허위정보 정책.
    "variants": [
        ("Fall Into Deep Sleep Instantly • Stop Overthinking, Calm Your Mind • Soft Night Ambient Music",
         ["SLEEP INSTANTLY"]),
        ("Can't Sleep? Try This for 3 Minutes • Deep Sleep Music to Quiet a Busy Mind & Beat Insomnia",
         ["TRY 3 MINUTES"]),
        ("Goodbye Insomnia • Fall Into Deep Sleep, Release Stress & Anxiety • Calm Ambient Sleep Music",
         []),
        ("Sleep Tonight Without Overthinking • Peaceful Music to Relax Body & Mind • Moonlit Night Ambience",
         ["STOP OVERTHINKING"]),
        ("Drift Into Deep Sleep • Relaxing Music for Insomnia, Stress Relief & a Calm Mind • Night Ambient",
         ["DEEP SLEEP"]),
        ("Fall Asleep Fast • Soothing Sleep Music to Let Go of the Day • Gentle Ambient for Deep Rest",
         []),
    ],
    "tags": ["sleep music", "deep sleep music", "fall asleep fast", "relaxing music", "ambient music",
             "calm music", "insomnia", "insomnia relief", "stop overthinking", "stress relief",
             "anxiety relief", "relaxing sleep music", "sleeping music", "music for sleep", "night ambience",
             "peaceful music", "soothing music", "calm sleep", "fall asleep instantly", "meditation music",
             "{hours} hours sleep music", "moonlit hush"],
    "category_id": "10",            # Music
    "language": "en",
    # 설명: 상위 영상은 약 1,500자(2026-10-11 조사). {duration} 은 길이 말(Three hours 등)로 바뀐다.
    "description_head": (
        "{duration} of calm, slowly evolving ambient music to help you fall asleep, stay asleep and let go "
        "of a busy mind.\n\n"
        "Every track in this mix is different: soft strings, warm pads, gentle harp, celesta and mellow "
        "keys, blended with {sound}. "
        "The volume stays low and steady, with long crossfades between tracks and no sudden sounds, so "
        "nothing pulls you out of sleep.\n\n"
        "How to listen\n"
        "• Start it as you get into bed and keep the volume just above a whisper.\n"
        "• Dim the screen or turn your phone face down. The picture stays calm and dark all night.\n"
        "• Breathe slowly: in for four, out for six. Let the music carry the thoughts away.\n"
        "• Also lovely for naps, reading, meditation, studying or a quiet evening.\n\n"
        "If this helps you rest, save it to your sleep playlist and subscribe to Moonlit Hush for new "
        "calm sleep music every week. Sweet dreams.\n\n"
        "This music is for relaxation only and is not a medical treatment. If you have ongoing sleep "
        "problems, please talk to a doctor.\n"
    ),
    "sound": "quiet nature sounds like light rain, distant waves, wind and night crickets",
    "hashtags": "#sleepmusic #deepsleep #relaxingmusic",
    # 업로드 뒤 넣을 재생목록(없으면 비공개로 만든다 — 공개 전환은 Somi 가 스튜디오에서)
    "playlist": ("Deep Sleep Music • Calm Ambient for Sleep",
                 "Calm ambient sleep music by Moonlit Hush: soft pads, strings, harp and gentle nature sounds."),
    "description_disclosure": (
        "Music generated with Google Lyria (AI) and arranged, checked and mixed by us.\n"
    ),
    # 배경·썸네일 이미지(Imagen). 작업 이름으로 하나를 골라 영상마다 장면이 다르다.
    # 배경·썸네일 이미지. 상위 썸네일은 '어두운 밤 + 빛나는 포인트', 채도·대비가 높다(칙칙한 남색 사진은 묻힌다).
    "background_style": ("Wide cinematic 16:9 digital artwork at night, magical and dreamy, deep dark blue and "
                         "violet sky with luminous glowing highlights, vivid saturated colours, strong contrast "
                         "between dark shadows and soft glowing light, very peaceful, no people, no text, "
                         "no watermark, ultra detailed"),
    "backgrounds": [
        "a bioluminescent beach with glowing cyan waves under a starry sky and the milky way",
        "an ancient tree in a dark forest surrounded by hundreds of glowing fireflies",
        "a still mountain lake mirroring a huge bright full moon and a sky full of stars",
        "a cozy bedroom window at night with warm lamp light, rain drops on the glass and a dark misty forest outside",
        "a calm lake under a vivid purple and blue galaxy with a shooting star",
        "a small wooden cabin with glowing windows in a snowy forest under the northern lights",
        "glowing blue flowers in a quiet meadow at night under a large crescent moon",
        "soft glowing clouds drifting over a dark ocean with moonlight shimmering on the water",
    ],
}

def _theme(name: str, texture: list, backgrounds: list, variants: list, sound: str, playlist: tuple,
           tags: list, hashtags: str, lead: list | None = None) -> dict:
    """SLEEP 을 바탕으로 배경 소리·장면·제목만 바꾼 테마(재생목록 하나 = 테마 하나).
    texture 는 같은 테마 안에서도 소리가 조금씩 다르게 여러 변형을 둔다."""
    keep = [t for t in SLEEP["tags"] if t not in ("insomnia relief", "fall asleep instantly", "calm sleep")]
    return {**SLEEP, "name": name, "texture": texture, "backgrounds": backgrounds, "variants": variants,
            "sound": sound, "playlist": playlist, "tags": (tags + keep)[:24], "hashtags": hashtags,
            **({"lead": lead} if lead else {})}


# 2026-10-12 Somi: 재생목록을 채우게 테마별 영상 추가. 조사에서 rain 1.6배, night 1.4배, space 1.5배(하루 조회수 중앙값).
RAIN = _theme(
    "sleep-rain",
    [("Window Rain", "soft rain tapping gently on a window"), ("Leaf Rain", "light rain falling on leaves"),
     ("Roof Rain", "gentle rain on a wooden roof, steady and soft"), ("Night Rain", "calm night rain far away"),
     ("Drizzle", "very light drizzle, barely audible")],
    ["a cozy wooden cabin window at night with warm lamp light, rain drops running down the glass and a dark misty forest outside",
     "a quiet lake at night in soft rain, rain ripples glowing under a pale moon behind thin clouds",
     "a rainy cobblestone street at night with warm glowing lanterns reflected in the wet stones",
     "a glass greenhouse at night in the rain, glowing plants and fairy lights inside, rain drops on the glass",
     "a misty pine forest in gentle rain at night, soft blue light and glowing raindrops"],
    [("Soft Rain & Calm Music for Deep Sleep • Fall Asleep Fast, Stop Overthinking • Rainy Night Ambience",
      ["RAIN & SLEEP"]),
     ("Fall Asleep to Gentle Rain • Relaxing Sleep Music for Insomnia & a Quiet Mind • Cozy Rainy Night",
      []),
     ("Rain on the Window • Peaceful Sleep Music to Melt Stress Away • Fall Into Deep Sleep Tonight",
      ["RAINY NIGHT"])],
    "soft rain in the background: rain on a window, on leaves and on a wooden roof, never loud",
    ("Rain Sleep Music • Soft Rain & Calm Music",
     "Gentle rain sounds blended with calm ambient music for deep sleep, by Moonlit Hush."),
    ["rain sounds", "rain sleep music", "rain sounds for sleeping", "rainy night", "relaxing rain"],
    "#rainsounds #sleepmusic #deepsleep")

OCEAN = _theme(
    "sleep-ocean",
    [("Soft Waves", "slow soft ocean waves on a sandy shore"), ("Far Sea", "distant ocean waves, very calm"),
     ("Night Tide", "gentle night tide washing in and out"), ("Lagoon", "tiny calm waves in a quiet lagoon")],
    ["a bioluminescent beach with glowing cyan waves under a starry sky and the milky way",
     "a calm moonlit ocean with a silver path of moonlight on the water and soft glowing clouds",
     "a quiet tropical lagoon at night with glowing turquoise water and a sky full of stars",
     "a lighthouse on a calm sea at night with a warm glowing beam and gentle waves",
     "soft glowing clouds drifting over a dark ocean with moonlight shimmering on the water"],
    [("Ocean Waves & Calm Music for Deep Sleep • Let Go of Stress, Fall Asleep Fast • Moonlit Sea",
      ["OCEAN SLEEP"]),
     ("Fall Asleep to Gentle Waves • Relaxing Sleep Music to Quiet Your Mind • Calm Night by the Sea",
      []),
     ("Drift Away With the Tide • Peaceful Ocean Sleep Music for Insomnia & Stress • Glowing Night Beach",
      ["DRIFT AWAY"])],
    "slow, gentle ocean waves in the background, from soft shore waves to a distant calm sea",
    ("Ocean Sleep Music • Calm Waves & Ambient",
     "Slow ocean waves blended with calm ambient music for deep sleep, by Moonlit Hush."),
    ["ocean waves", "ocean sleep music", "sea sounds", "waves for sleeping", "beach at night"],
    "#oceanwaves #sleepmusic #deepsleep")

FOREST = _theme(
    "sleep-forest",
    [("Crickets", "quiet night crickets far away"), ("Forest Wind", "soft wind through tall trees"),
     ("Creek", "a calm gentle forest creek"), ("Owl Night", "a peaceful night forest, a very distant owl now and then")],
    ["an ancient tree in a dark forest surrounded by hundreds of glowing fireflies",
     "a quiet forest clearing at night with glowing mushrooms, fireflies and soft moonlight",
     "a calm forest stream at night with glowing stones and fireflies above the water",
     "a small wooden cabin with glowing windows in a snowy forest under the northern lights",
     "tall pine trees under a huge full moon with soft blue mist between the trunks"],
    [("Peaceful Night Forest • Calm Sleep Music With Crickets & Soft Wind • Fall Into Deep Sleep",
      ["NIGHT FOREST"]),
     ("Fireflies & Calm Music for Deep Sleep • Quiet Your Mind, Stop Overthinking • Enchanted Night Forest",
      []),
     ("Fall Asleep in a Quiet Forest • Relaxing Sleep Music for Insomnia & Stress • Gentle Night Sounds",
      ["FOREST SLEEP"])],
    "quiet night forest sounds: far-away crickets, soft wind in the trees and a gentle creek",
    ("Night Forest Sleep Music • Crickets, Wind & Calm Music",
     "Peaceful night forest sounds with calm ambient music for deep sleep, by Moonlit Hush."),
    ["forest sounds", "night forest", "crickets sounds", "nature sounds for sleep", "fireflies"],
    "#naturesounds #sleepmusic #deepsleep")

SPACE = _theme(
    "sleep-space",
    [("Deep Space", "no nature sounds, pure soft tone"), ("Starlight", "faint shimmering high tones like starlight"),
     ("Nebula", "soft airy noise like a far-away cosmic wind"), ("Orbit", "slow wide stereo movement, floating")],
    ["a calm lake under a vivid purple and blue galaxy with a shooting star",
     "a glowing nebula in deep space in soft violet, blue and pink, with countless stars",
     "the earth seen from space at night with a thin glowing blue atmosphere and the milky way",
     "a ringed planet floating in deep space with soft glowing rings and distant stars",
     "a quiet alien desert under two moons and a sky full of glowing galaxies"],
    [("Floating in Space • Deep Sleep Music to Quiet a Busy Mind • Calm Cosmic Ambient for Sleep",
      ["FLOAT AWAY"]),
     ("Drift Into Deep Sleep Among the Stars • Relaxing Space Ambient for Insomnia & Stress Relief",
      []),
     ("Cosmic Sleep Music • Let Go of the Day, Fall Asleep Fast • Peaceful Galaxy Ambience",
      ["COSMIC SLEEP"])],
    "soft cosmic textures: shimmering high tones, airy far-away hum and slow floating sound",
    ("Space Sleep Music • Cosmic Ambient for Deep Sleep",
     "Floating cosmic ambient music for deep sleep and calm, by Moonlit Hush."),
    ["space ambient", "space music for sleep", "cosmic music", "galaxy ambience", "deep space"],
    "#spaceambient #sleepmusic #deepsleep",
    lead=[l for l in SLEEP["lead"] if l[0] in ("Warm Pads", "Soft Strings", "Celesta", "Low Drone",
                                                 "Ambient Guitar", "Rhodes")])

CATEGORIES = {"sleep": SLEEP, "sleep-rain": RAIN, "sleep-ocean": OCEAN, "sleep-forest": FOREST,
              "sleep-space": SPACE}


def plan_tracks(category: str, count: int, seed: int = 0) -> list[dict]:
    """곡 count 개의 기획. 같은 (리드, 질감) 조합이 붙어 나오지 않게 섞는다."""
    c = CATEGORIES[category]
    rnd = random.Random(seed)
    combos = [(l, t) for l in c["lead"] for t in c["texture"]]
    rnd.shuffle(combos)
    out, prev = [], None
    i = 0
    while len(out) < count:
        if i >= len(combos):                    # 조합보다 곡이 많으면 다시 섞어서 이어 간다
            rnd.shuffle(combos)
            i = 0
        lead, tex = combos[i]
        i += 1
        if prev and (lead[0] == prev[0][0] or tex[0] == prev[1][0]) and len(combos) > 2:
            # 바로 앞 곡과 악기나 배경이 같으면 뒤의 다른 조합과 자리를 바꾼다
            for j in range(i, len(combos)):
                if combos[j][0][0] != prev[0][0] and combos[j][1][0] != prev[1][0]:
                    combos[i - 1], combos[j] = combos[j], combos[i - 1]
                    lead, tex = combos[i - 1]
                    break
        key = rnd.choice(c["key"])
        n = len(out) + 1
        out.append({
            "id": f"t{n:03d}",
            "name": f"{lead[0]} & {tex[0]}",
            "prompt": f"{c['base']}, {lead[1]}, {tex[1]}, {key}. {COMMON_TAIL}",
        })
        prev = (lead, tex)
    return out


def variant(category: str, job: str) -> tuple[str, list[str]]:
    """작업 이름으로 (제목, 썸네일 글자)를 고른다. 같은 작업은 늘 같은 짝."""
    import zlib
    v = CATEGORIES[category]["variants"]
    return v[zlib.crc32(("title:" + job).encode()) % len(v)]


NUMBER_WORDS = {1: "One hour", 2: "Two hours", 3: "Three hours", 4: "Four hours", 5: "Five hours",
                6: "Six hours", 7: "Seven hours", 8: "Eight hours", 9: "Nine hours", 10: "Ten hours",
                11: "Eleven hours", 12: "Twelve hours"}


def duration_words(sec: float) -> str:
    h = sec / 3600
    return NUMBER_WORDS.get(round(h), f"{h:g} hours") if abs(h - round(h)) < 0.05 else f"{h:.1f} hours"


def tags(category: str, sec: float) -> list[str]:
    h = round(sec / 3600)
    return [t.replace("{hours}", str(h)) for t in CATEGORIES[category]["tags"]]


def title(category: str, job: str) -> str:
    """variant 제목 + 시리즈 번호(작업 이름이 sleep-002 처럼 숫자로 끝나면 #2). 100자를 넘으면 번호는 뺀다."""
    import re
    t = variant(category, job)[0]
    n = re.search(r"-(\d+)$", job)
    if n and len(t) + len(f" #{int(n.group(1))}") <= 100:
        t += f" #{int(n.group(1))}"
    return t


def background_prompt(category: str, job: str) -> str:
    """작업 이름으로 장면 하나를 고른다(같은 작업은 늘 같은 장면, 작업마다 다른 장면)."""
    import zlib
    c = CATEGORIES[category]
    scene = c["backgrounds"][zlib.crc32(job.encode()) % len(c["backgrounds"])]
    return f"{c['background_style']}. Scene: {scene}."
