#!/usr/bin/env python3
"""네이버 뉴스 검색(최신순) → 새 기사만 텔레그램 채널로 발송."""
import html, json, os, pathlib, re, sys, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone

# ponytail: 네이버가 이미 연예·스포츠를 별도 도메인으로 분리해뒀다.
# 그 분류를 그대로 쓴다 — 제목으로 추측하는 것보다 정확하다.
ENT_SPORTS_DOMAINS = ("entertain.naver.com", "sports.naver.com")


def is_ent_sports(link):
    return urllib.parse.urlparse(link).netloc.endswith(ENT_SPORTS_DOMAINS)


# 언론사명에 "경제"가 없어도 경제지인 곳들
EXTRA_ECONOMY_PRESS = ("파이낸셜뉴스",)
# 기업 홍보성 기사(사회공헌·수출 실적 등)에 흔한 제목 어휘 — 어느 키워드든 걸리면 제외
BUSINESS_NOISE = ("증권", "수출", "수주", "호재", "사회공헌")


def is_economy_press(press):
    return "경제" in press or press in EXTRA_ECONOMY_PRESS


def is_business_noise(title):
    return any(w in title for w in BUSINESS_NOISE)

HERE = pathlib.Path(__file__).parent
ENV, SEEN, STATE = HERE / ".env", HERE / "seen.json", HERE / "state.json"
KEYWORDS_FILE = HERE / "keywords.txt"
KEEP = 1000  # ponytail: 파일 하나로 중복 방지. 키워드/발송량 커지면 sqlite로.

if ENV.exists():  # ponytail: python-dotenv 대신 4줄
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

def load_keywords():
    # KEYWORDS 환경변수가 있으면 그걸 우선한다(로컬 임시 테스트용).
    # 평소엔 keywords.txt 를 쓴다 — 저장소에서 바로 고칠 수 있게 비밀값 밖으로 뺀 것.
    if os.environ.get("KEYWORDS"):
        return [k.strip() for k in os.environ["KEYWORDS"].split(",") if k.strip()]
    if KEYWORDS_FILE.exists():
        return [ln.strip() for ln in KEYWORDS_FILE.read_text().splitlines()
                if ln.strip() and not ln.startswith("#")]
    return []


KEYWORDS = load_keywords()

# ponytail: 키워드별 제외어. 국가명 + 헤드라인용 한자 약칭 + 주요 도시/지역.
# 도시까지 넣는 이유: "파리 명물 흉상" 처럼 제목에 국가명이 안 나오는 해외 기사를 잡기 위해.
EXCLUDE = {"녹색당": ("영국", "英", "런던", "잉글랜드", "스코틀랜드", "웨일스",
                     "프랑스", "佛", "파리", "마르세유", "리옹",
                     "호주", "濠", "豪", "시드니", "멜버른", "캔버라",
                     "미국", "美", "워싱턴", "뉴욕", "백악관", "실리콘밸리",
                     "캐나다", "加", "토론토", "밴쿠버", "오타와",
                     "독일", "獨", "베를린", "뮌헨", "함부르크")}
# ponytail: 검색어가 더 긴 단어에 먹혀 딸려오는 오탐. 그 긴 단어를 지우고도
# 검색어가 남아야 진짜 관련 기사다. 위치·빈도와 무관하게 매칭 자체를 본다.
SWALLOWED_BY = {"차별금지법": ("장애인차별금지법",)}
# ponytail: "녹색당"만 언급되고 실제로는 무관한 기사(예: 인물 소개에 이력으로만 등장)를
# 거른다. 둘 중 하나면 통과 — (1) 당이 행위자로 등장(제목·리드에 언급) (2) 녹색당이
# 실제로 다루는 정책 영역과 겹침. 둘 다 아니면 이름만 스친 기사로 보고 제외한다.
# kgreens.org 전국당 논평(2025~2026) 실제 제목에서 뽑은 어휘. 짐작이 아니라 실제 활동 기록 기준.
GREEN_PARTY_TOPICS = (
    "기후위기", "기후정의", "기후불복종", "탄소중립", "온실가스", "탈핵", "신규핵발전소",
    "핵발전", "원전", "양수발전소", "재생에너지", "전력수급기본계획", "새만금신공항", "신공항",
    "생태", "환경", "생물다양성", "동물권", "채식",
    "노동자", "비정규직", "최저임금", "노란봉투법", "중대재해", "산재", "위험의 외주화",
    "파업", "이주노동자", "다단계 하청", "노동절", "직접고용",
    "페미니즘", "성평등", "성소수자", "퀴어", "차별금지법", "여성혐오", "임신중지",
    "동성애", "장애인", "이주민", "난민", "학생인권",
    "공공주택", "반지하", "복지", "자살률", "촉법소년",
    "개헌", "봉쇄조항", "선거연합", "지방선거", "공직선거법", "법사위", "탄핵", "파면",
    "폭염", "폭우", "참사", "안전 사각지대",
    "기본소득", "지방분권", "직접민주주의", "주민자치", "협동조합", "먹거리", "반전", "평화",
)
# ponytail: 위치+빈도 휴리스틱. 제목/리드에 나오면 그 기사의 주제고,
# 중반 이후 한두 번은 비교 사례라 통과시킨다. 오탐이 잦으면 숫자만 조절할 것.
LEAD_PARAS = 2      # 리드로 볼 문단 수
MENTION_LIMIT = 3   # 본문 전체에서 이 횟수 이상 나오면 비중이 높다고 본다
# "英 녹색당 정책 논쟁" 처럼 해외 기사라도 "녹색당" 자체가 2회 이상 나오면
# (독일 뷘트니스 90/디그뤼넨을 "독일 녹색당"으로 부르는 경우 등) 주요하게 다뤄진 걸로
# 보고 국가 제외를 무시하고 보낸다. 1회뿐이면 그냥 스쳐가는 언급으로 본다.
FOREIGN_OVERRIDE_MENTIONS = 2
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
QUOTE_MAX = 700
# ponytail: 키워드를 추가하면 그 키워드의 과거 기사가 통째로 "새 기사"가 된다.
# 한 번에 이만큼 넘으면 발송을 건너뛰고 기록만 한다 (첫 실행과 같은 처리).
MAX_BURST = 30
DIGEST_MAX = 60  # 모아보기 한 구간에 이만큼 넘게 쌓이면 폭탄 방지로 건너뛴다
# 네이버 뉴스 페이지가 없는 기사는 즉시 보내지 않고 모아뒀다가 3시간마다 묶어서 보낸다.
KST = timezone(timedelta(hours=9))
DIGEST_HOURS = 3
MSG_MAX = 3800  # 텔레그램 한 메시지 4096자 제한 안쪽으로

# 같은 사안을 여러 매체가 받아쓸 때의 우선순위. 앞 묶음일수록 우선.
PRESS_TIERS = (("경향신문", "한겨레", "프레시안", "오마이뉴스"),
               ("연합뉴스", "뉴시스", "뉴스1", "연합뉴스TV"))
# ponytail: 제목 2글자 뭉치의 자카드 유사도로 같은 사안을 묶는다. 실측상
# 같은 사안 최대 0.61 / 다른 사안 최대 0.06 이라 0.18 이면 넉넉히 갈린다.
TOPIC_SIM = 0.18
TOPICS_KEEP = 300


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def search(kw):
    q = urllib.parse.urlencode({"query": kw, "display": 30, "sort": "date", "format": "json"})
    # NCP(NAVER API HUB) 발급 키. developers.naver.com 키를 쓸 거면
    # openapi.naver.com/v1/search/news.json + X-Naver-Client-Id/Secret 으로.
    req = urllib.request.Request(
        f"https://naverapihub.apigw.ntruss.com/search/v1/news?{q}",
        headers={"X-NCP-APIGW-API-KEY-ID": os.environ["NAVER_ID"],
                 "X-NCP-APIGW-API-KEY": os.environ["NAVER_SECRET"]})
    with urllib.request.urlopen(req, timeout=20) as r:
        items = json.load(r)["items"]
    # 네이버뉴스 페이지가 있으면 그 링크, 없으면 언론사 원문
    return [(clean(i["title"]), i.get("link") or i["originallink"], clean(i["description"])) for i in items]


def spurious(kw, text):
    if kw not in SWALLOWED_BY:
        return False
    text = text.replace(" ", "")  # "차별 금지법" 처럼 띄어 쓴 표기도 같게 본다
    for w in SWALLOWED_BY[kw]:
        text = text.replace(w, "")
    return kw not in text


def on_topic(kw, text):
    """네이버 검색은 정확한 문구가 아니라 관련도로 매칭한다.
    검색어(공백 무시)가 실제로 텍스트에 붙어 있는 경우만 진짜 관련 기사로 본다."""
    norm = lambda t: re.sub(r"\s+", "", t)
    return norm(kw) in norm(text)


def excluded(kw, title, paras, desc=""):
    """제외 사유 문자열, 통과면 None."""
    lead = " ".join(paras[:LEAD_PARAS]) or desc  # 본문을 못 읽으면 검색 요약으로 대신
    body = " ".join(paras)

    if kw == "녹색당":
        # 제목 또는 리드(첫 문단들)에 있으면 행위자로 본다. 예: "충북녹색당 등 이른바
        # '진보 3당'은 기자회견을 열고..." — 제목엔 "진보 3당"이라고만 쓰여도 리드에서
        # 실제 당사자임이 드러난다. 본문 중간에서만 나오면(이력 소개 등) 정책 겹침으로 판단.
        actor = kw in title or kw in lead
        on_topic_area = any(w in title + desc + body for w in GREEN_PARTY_TOPICS)
        if not (actor or on_topic_area):
            return "접점없음"

    words = EXCLUDE.get(kw, ())
    if not words:
        return None
    if (title + desc + body).count(kw) >= FOREIGN_OVERRIDE_MENTIONS:
        return None  # 녹색당 자체가 여러 번 등장 — 해외 기사라도 주요하게 다룬 것으로 본다
    if any(w in title for w in words):
        return "제목"
    if any(w in lead for w in words):
        return "리드"
    n = sum(body.count(w) for w in words)
    return f"본문 {n}회" if n >= MENTION_LIMIT else None


# ponytail: 기사 문단에 늘 따라붙는 군더더기. 문단 앞뒤에 붙은 것만 떼고 본문 중간은 안 건드린다.
BYLINE = re.compile(r"[\s/·]*[가-힣]{2,5}\s*(?:기자|특파원|객원기자|선임기자|논설위원|PD|앵커)\s*$")
EMAIL = re.compile(r"\s*[\w.+-]+@[\w.-]+\.\w+\s*$")
DATELINE = re.compile(r"^\[[^\]]{1,30}\]\s*(?:[가-힣]{2,5}\s*기자\s*=?\s*)?")


def tidy(para):
    para = DATELINE.sub("", para.strip())
    for _ in range(2):  # 이메일 뒤에 기자명이 또 오는 경우가 있다
        para = BYLINE.sub("", EMAIL.sub("", para)).strip()
    return para


def article(link):
    """(언론사, 본문 문단들). 언론사 원문 링크는 형식이 제각각이라 포기하고 빈 값."""
    if "n.news.naver.com" not in link:
        return "", []
    try:
        req = urllib.request.Request(link, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            page = r.read().decode("utf-8", "replace")
    except Exception:
        return "", []
    # <meta property="og:article:author" content="경향신문 | 네이버">
    a = re.search(r'og:article:author" content="([^"|]+)', page)
    press = html.unescape(a.group(1)).strip() if a else ""
    m = re.search(r'<article[^>]*id="dic_area"[^>]*>(.*?)</article>', page, re.S)
    if not m:
        return press, []
    body = re.sub(r"<(script|style)\b.*?</\1>", "", m.group(1), flags=re.S)
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = html.unescape(re.sub(r"<[^>]+>", "", body))
    return press, [t for t in (tidy(p) for p in body.split("\n")) if len(t) > 30]


def quote_for(kw, paras):
    """키워드가 나오는 첫 문단, 없으면 첫 문단.
    본문을 못 읽으면 빈 값 — 링크 미리보기가 요약을 대신하므로 인용구를 생략한다."""
    hit = next((p for p in paras if kw in p), paras[0] if paras else "")
    return hit[:QUOTE_MAX] + ("…" if len(hit) > QUOTE_MAX else "")


def format_msg(press, title, link, quote):
    head = f"[{press}] {title}" if press else title
    block = f"<blockquote>{html.escape(quote)}</blockquote>\n\n" if quote else ""
    return f"<b>{html.escape(head)}</b>\n\n{block}{link}"


def press_rank(press):
    for i, tier in enumerate(PRESS_TIERS):
        if press in tier:
            return i
    return len(PRESS_TIERS)


def shingles(title):
    t = re.sub(r"[^가-힣A-Za-z0-9]", "", title)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def same_topic(a, b):
    A, B = shingles(a), shingles(b)
    return bool(A | B) and len(A & B) / len(A | B) >= TOPIC_SIM


def pick_by_press(cands, topics):
    """(보낼 것, 갱신된 사안 목록).
    진보언론(순위 0)은 같은 사안이라도 매번 다시 보낸다.
    그 외는 이미 보낸 것보다 더 우선하는 매체일 때만 다시 보낸다."""
    topics = [list(t) for t in topics]
    keep = set()
    for i in sorted(range(len(cands)), key=lambda i: cands[i][0]):  # 우선 매체부터 판단
        rank, title = cands[i][0], cands[i][1]
        hit = next((t for t in topics if same_topic(title, t[0])), None)
        if hit is None:
            topics.insert(0, [title, rank])
            keep.add(i)
        elif rank == 0 or rank < hit[1]:
            hit[1] = min(hit[1], rank)
            keep.add(i)
    return keep, topics[:TOPICS_KEEP]


def slot(now):
    """지금이 속한 3시간 구간의 시작(KST). 0·3·6·9·12·15·18·21시."""
    return now.astimezone(KST).replace(minute=0, second=0, microsecond=0) \
             - timedelta(hours=now.astimezone(KST).hour % DIGEST_HOURS)


def digest_messages(items, at):
    """키워드별로 묶은 모아보기. 길면 여러 통으로 나눈다. 항목이 없으면 빈 리스트 —
    헤더만 있는 빈 메시지를 보내던 버그가 있었다: lines에 헤더 한 줄만 있어도
    청크 만드는 루프가 그걸 유효한 메시지 하나로 쳐서 반환해버렸다."""
    if not items:
        return []
    ampm, h12 = ("오전", at.hour) if at.hour < 12 else ("오후", at.hour - 12)
    lines = [f"📰 <b>{ampm} {h12 or 12}시의 키워드 뉴스 보기</b>"]
    groups = {}
    for kw, title, link in items:
        groups.setdefault(kw, []).append((title, link))
    for arts in groups.values():
        lines.append("")  # 키워드명은 안 쓰고 빈 줄로만 묶음을 구분한다
        for title, link in arts:
            lines.append(f'• <a href="{html.escape(link, quote=True)}">'
                         f"<b>{html.escape(title)}</b></a>")
    msgs, cur = [], ""
    for ln in lines:
        if not cur and not ln:
            continue  # 메시지 첫 줄이 빈 줄이 되지 않게
        if cur and len(cur) + len(ln) + 1 > MSG_MAX:
            msgs.append(cur)
            cur = ln
        else:
            cur = f"{cur}\n{ln}" if cur else ln
    return msgs + [cur] if cur else msgs


DIGEST_DISABLED = False  # 빈 메시지 버그(digest_messages 공백 처리) + 시각 불일치 안전장치로 재개


def flush_digest(state, now):
    """3시간 구간이 바뀌었으면 모아둔 기사를 보내고 비운다.
    지금은 DIGEST_DISABLED=True 라서 실제 send()는 절대 호출하지 않는다 —
    구간 갱신과 digest 비우기만 하고 넘어간다(계속 쌓이기만 하는 것도 막는다)."""
    here = slot(now)
    last = state.get("slot")
    if last is None:  # 처음이면 기준만 잡고 다음 구간부터
        state["slot"] = here.isoformat()
        return state
    if datetime.fromisoformat(last) >= here:
        return state
    items = state["digest"]
    if DIGEST_DISABLED:
        if items:
            print(f"모아보기 비활성화 상태 — {len(items)}건 발송하지 않고 버림")
        state["slot"], state["digest"] = here.isoformat(), []
        return state
    if not items:  # 보낼 게 없으면 헤더만 있는 빈 메시지도 안 보낸다
        state["slot"] = here.isoformat()
        return state
    # 안전장치: 보내려는 라벨(here)이 "진짜 지금"과 다르면 무슨 정신 나간 상태로
    # 계산된 값이라는 뜻이니 보내지 않는다. now 인자가 어디서 잘못 꼬였든 여기서 막힌다.
    fresh = slot(datetime.now(KST))
    if here != fresh:
        print(f"모아보기 시각 불일치 — 계산값 {here.isoformat()} / 실제 현재 {fresh.isoformat()}. 발송하지 않는다.")
        state["slot"], state["digest"] = here.isoformat(), []
        return state
    if len(items) > DIGEST_MAX:
        print(f"모아보기 대상 {len(items)}건 — {DIGEST_MAX}건을 넘어 발송을 건너뛰고 기록만 한다.")
        print("(키워드를 추가했다면 정상. 다음 구간부터 정상 분량만 모인다)")
        items = []
    for msg in digest_messages(items, here):
        send(msg, preview=False)
    if items:
        print(f"모아보기 {len(items)}건 발송")
    state["slot"], state["digest"] = here.isoformat(), []
    return state


def send(msg, preview=True):
    """실패해도 죽지 않는다 — 여기서 죽으면 그 아래의 상태 저장이 안 돌아서,
    다음 실행이 같은 항목을 다시 보내려다 또 실패하는 무한 반복에 빠진다.
    429(과다 요청)는 텔레그램이 알려주는 시간만큼 기다렸다 한 번 재시도한다."""
    data = json.dumps({"chat_id": os.environ["TG_CHAT"], "text": msg,
                       "parse_mode": "HTML",
                       "disable_web_page_preview": not preview}).encode()
    url = f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage"
    for attempt in range(2):
        try:
            urllib.request.urlopen(
                urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}),
                timeout=20).read()
            return True
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code == 429 and attempt == 0:
                wait = json.loads(body).get("parameters", {}).get("retry_after", 5)
                time.sleep(min(wait, 30))
                continue
            print(f"  텔레그램 발송 실패 {e.code}: {body[:200]}")
            return False
        except Exception as e:
            print(f"  텔레그램 발송 실패(네트워크): {e}")
            return False
    return False


def main():
    # 시크릿이 없으면 GitHub 는 빈 문자열을 넘긴다. 조용히 성공하는 대신 여기서 죽는다.
    missing = [k for k in ("NAVER_ID", "NAVER_SECRET", "TG_TOKEN", "TG_CHAT") if not os.environ.get(k)]
    if not KEYWORDS:
        missing.append("KEYWORDS (keywords.txt 비어있음)")
    if missing:
        raise SystemExit("설정 누락: " + ", ".join(missing))

    seen = json.loads(SEEN.read_text()) if SEEN.exists() else []
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state.setdefault("digest", [])
    state.setdefault("topics", [])
    first_run = not seen  # 빈 목록도 첫 실행. 있으나 마나 한 파일에 속아 전체를 발송하지 않는다
    known, fresh, queue = set(seen), [], []
    for kw in KEYWORDS:
        for title, link, desc in search(kw):
            if link in known:
                continue
            known.add(link)
            fresh.append(link)
            if first_run or is_ent_sports(link):
                continue  # 순수 연예·스포츠 기사는 보내지 않는다
            if is_business_noise(title):  # 증권·수출·수주·호재·사회공헌 등 기업 홍보성 제목
                print(f"  제외(기업 홍보성): {title[:40]}")
                continue
            if "n.news.naver.com" not in link:
                # 본문을 못 읽으므로 제목과 검색 요약만으로 같은 필터를 건다
                if (on_topic(kw, title + desc) and not spurious(kw, title + desc)
                        and not excluded(kw, title, [], desc)):
                    state["digest"].append([kw, title, link])  # 3시간마다 묶어서 발송
                continue
            press, paras = article(link)
            if is_economy_press(press):  # 매일경제·아시아경제·한국경제·파이낸셜뉴스 등 제외
                print(f"  제외(경제지 {press}): {title[:36]}")
                continue
            body_all = title + desc + " ".join(paras)
            why = ("검색어와 무관" if not on_topic(kw, body_all) else
                   "검색어 오탐" if spurious(kw, body_all) else
                   excluded(kw, title, paras, desc))
            if why:  # 제외건도 seen 에는 남겨 다시 안 보게 한다
                print(f"  제외({why}): {title[:40]}")
                continue
            queue.append((press_rank(press), title, press, link, quote_for(kw, paras)))

    keep, state["topics"] = pick_by_press(queue, state["topics"])
    for i, (rank, title, *_) in enumerate(queue):
        if i not in keep:
            print(f"  중복(같은 사안, 이미 상위 매체 발송): {title[:36]}")
    queue = [c for i, c in enumerate(queue) if i in keep]

    if len(queue) > MAX_BURST:
        print(f"발송 대상 {len(queue)}건 — {MAX_BURST}건을 넘어 발송을 건너뛰고 기록만 한다.")
        print("(키워드를 추가했다면 정상. 다음 실행부터 새 기사만 발송된다)")
        queue = []
    try:
        for _, title, press, link, quote in reversed(queue):  # 오래된 것부터
            send(format_msg(press, title, link, quote))
        if os.environ.get("FORCE_DIGEST", "").lower() == "true" and state.get("slot"):
            # 지금 슬롯을 "아직 처리 안 한 것"으로 되돌려서 flush_digest 가 다시 보내게 한다.
            state["slot"] = (datetime.fromisoformat(state["slot"]) - timedelta(hours=1)).isoformat()
            print("FORCE_DIGEST — 이번 구간 모아보기를 다시 발송한다")
        state = flush_digest(state, datetime.now(KST))
    finally:
        # 위에서 무슨 일이 있었든(네트워크 오류 등) 여기까지는 항상 실행돼
        # 이미 보낸 것/처리한 것이 다음 실행에서 중복되지 않게 한다.
        STATE.write_text(json.dumps(state, ensure_ascii=False))
        SEEN.write_text(json.dumps((fresh + seen)[:KEEP], ensure_ascii=False))
    print(f"새 기사 {len(fresh)}건 / " + ("저장만 (첫 실행)" if first_run else f"발송 {len(queue)}건"))


def chatid():
    """채널을 봇 관리자로 추가하고 아무 글이나 올린 뒤 실행하면 숫자 ID를 알려준다."""
    with urllib.request.urlopen(
            f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/getUpdates", timeout=30) as r:
        ups = json.load(r)["result"]
    seen_chats = {u[k]["chat"]["id"]: u[k]["chat"]
                  for u in ups for k in ("channel_post", "message", "my_chat_member") if k in u}
    if not seen_chats:
        print("업데이트 없음 — 봇을 채널 관리자로 추가하고 채널에 아무 글이나 올린 뒤 다시 실행")
    for cid, c in seen_chats.items():
        print(f"TG_CHAT={cid}   ({c['type']}: {c.get('title') or c.get('username')})")


def check():
    """키 값은 출력하지 않고 형태와 인증만 점검."""
    for k in ("NAVER_ID", "NAVER_SECRET", "TG_TOKEN", "TG_CHAT"):
        v = os.environ.get(k)
        print(f"{k}: {'없음' if v is None else str(len(v)) + '자'}")
    try:
        print("네이버 검색 API:", len(search("테스트")), "건 — 정상")
    except urllib.error.HTTPError as e:
        print("네이버 검색 API 실패:", e.code, e.read().decode()[:150])


def selftest():
    assert press_rank("한겨레") == 0 and press_rank("뉴시스") == 1 and press_rank("더팩트") == 2
    a = "인권위 “사법경찰리 독자적 조서 작성은 위법”…경찰수사규칙 개정 권고"
    b = '인권위 "경사 이하 경찰관 단독 조서 작성 관행 개정해야" 권고'
    c = "군포시, 배리어프리 키오스크 안심택배함 전격 도입"
    assert same_topic(a, b) and not same_topic(a, c)
    # 한 실행에 같은 사안 3건: 우선 매체 하나만 나간다
    keep, tops = pick_by_press([(2, a), (0, b), (1, a)], [])
    assert keep == {1} and tops[0][1] == 0
    # 이미 그 외 매체로 나간 사안 → 진보언론이 뒤늦게 나오면 다시 보낸다
    keep, tops = pick_by_press([(0, b)], [[a, 2]])
    assert keep == {0} and tops[0][1] == 0
    # 통신사·그 외는 같은 등급이 또 오면 안 보낸다
    assert pick_by_press([(2, b)], [[a, 2]])[0] == set()
    assert pick_by_press([(1, b)], [[a, 1]])[0] == set()
    # 진보언론은 이미 진보언론으로 나갔어도 또 나오면 다시 보낸다
    assert pick_by_press([(0, b)], [[a, 0]])[0] == {0}
    huge = [["kw", f"제목{i}", f"http://{i}"] for i in range(DIGEST_MAX + 1)]
    st = flush_digest({"slot": (datetime(2026, 8, 24, 6, 0, tzinfo=KST)).isoformat(), "digest": huge},
                       datetime(2026, 8, 24, 9, 0, tzinfo=KST))
    assert st["digest"] == []  # 넘치면 보내지 않고 비우기만 한다
    at = datetime(2026, 8, 24, 9, 0, tzinfo=KST)
    assert slot(datetime(2026, 8, 24, 10, 59, tzinfo=KST)) == at
    assert slot(datetime(2026, 8, 24, 11, 1, tzinfo=KST)) == at
    assert slot(datetime(2026, 8, 24, 12, 0, tzinfo=KST)).hour == 12
    m = digest_messages([["녹색당", "제목1", "http://a"], ["녹색당", "제목2", "http://b"],
                         ["정의당", "제목3", "http://c"]], at)
    assert len(m) == 1 and m[0].startswith("📰 <b>오전 9시의 키워드 뉴스 보기</b>")
    assert "녹색당" not in m[0] and '<a href="http://a"><b>제목1</b></a>' in m[0]
    assert m[0].count("\n\n") == 2  # 묶음 사이 빈 줄
    assert len(digest_messages([["kw", "제" * 200, f"http://{i}"] for i in range(30)], at)) > 1
    assert all(len(x) <= MSG_MAX for x in
               digest_messages([["kw", "제" * 200, f"http://{i}"] for i in range(30)], at))
    assert spurious("차별금지법", "장애인차별금지법 개정 논의")
    assert not spurious("차별금지법", "장애인차별금지법과 차별금지법은 다르다")
    assert not spurious("차별금지법", "포괄적 차별 금지법 제정 논의")   # 띄어쓰기 허용
    assert press_rank("한겨레") == 0 and press_rank("뉴시스") == 1 and press_rank("더팩트") == 2
    a = "인권위 “사법경찰리 독자적 조서 작성은 위법”…경찰수사규칙 개정 권고"
    b = '인권위 "경사 이하 경찰관 단독 조서 작성 관행 개정해야" 권고'
    c = "군포시, 배리어프리 키오스크 안심택배함 전격 도입"
    assert same_topic(a, b) and not same_topic(a, c)
    # 한 실행에 같은 사안 3건: 우선 매체 하나만 나간다
    keep, tops = pick_by_press([(2, a), (0, b), (1, a)], [])
    assert keep == {1} and tops[0][1] == 0
    # 이미 그 외 매체로 나간 사안 → 진보언론이 뒤늦게 나오면 다시 보낸다
    keep, tops = pick_by_press([(0, b)], [[a, 2]])
    assert keep == {0} and tops[0][1] == 0
    # 통신사·그 외는 같은 등급이 또 오면 안 보낸다
    assert pick_by_press([(2, b)], [[a, 2]])[0] == set()
    assert pick_by_press([(1, b)], [[a, 1]])[0] == set()
    # 진보언론은 이미 진보언론으로 나갔어도 또 나오면 다시 보낸다
    assert pick_by_press([(0, b)], [[a, 0]])[0] == {0}
    huge = [["kw", f"제목{i}", f"http://{i}"] for i in range(DIGEST_MAX + 1)]
    st = flush_digest({"slot": (datetime(2026, 8, 24, 6, 0, tzinfo=KST)).isoformat(), "digest": huge},
                       datetime(2026, 8, 24, 9, 0, tzinfo=KST))
    assert st["digest"] == []  # 넘치면 보내지 않고 비우기만 한다
    at = datetime(2026, 8, 24, 9, 0, tzinfo=KST)
    assert slot(datetime(2026, 8, 24, 10, 59, tzinfo=KST)) == at
    assert slot(datetime(2026, 8, 24, 11, 1, tzinfo=KST)) == at
    assert slot(datetime(2026, 8, 24, 12, 0, tzinfo=KST)).hour == 12
    m = digest_messages([["녹색당", "제목1", "http://a"], ["녹색당", "제목2", "http://b"],
                         ["정의당", "제목3", "http://c"]], at)
    assert len(m) == 1 and m[0].startswith("📰 <b>오전 9시의 키워드 뉴스 보기</b>")
    assert "녹색당" not in m[0] and '<a href="http://a"><b>제목1</b></a>' in m[0]
    assert m[0].count("\n\n") == 2  # 묶음 사이 빈 줄
    assert len(digest_messages([["kw", "제" * 200, f"http://{i}"] for i in range(30)], at)) > 1
    assert all(len(x) <= MSG_MAX for x in
               digest_messages([["kw", "제" * 200, f"http://{i}"] for i in range(30)], at))
    assert spurious("차별금지법", "성정체성 차별 금지 명시해야")        # '법'이 없으면 오탐
    assert is_economy_press("매일경제") and is_economy_press("파이낸셜뉴스")
    assert not is_economy_press("한겨레")
    assert is_business_noise("OO기업, 사회공헌활동으로 지역사회 훈훈")
    assert is_business_noise("반도체 수출 호재에 코스피 껑충")
    assert not is_business_noise("녹색당 논평 발표")
    assert is_ent_sports("https://m.entertain.naver.com/article/382/0001289655")
    assert is_ent_sports("https://m.sports.naver.com/original/article/1")
    assert not is_ent_sports("https://n.news.naver.com/mnews/article/032/1")
    assert not on_topic("체제전환운동", "3인 체제로 전환하며 새로운 사운드를 고민")
    assert on_topic("체제전환운동", "체제전환운동 관련 성명을 발표했다")
    assert on_topic("체제전환운동", "체제전환\n운동 관련")  # 줄바꿈 등 공백은 무시
    assert not spurious("성소수자", "성소수자 관련 기사")  # 등록 안 된 키워드는 통과
    assert excluded("녹색당", "英 총선서 녹색당 약진", []) == "제목"  # 1회뿐 — 그냥 스침
    assert excluded("녹색당", "英 총선서 녹색당 약진", ["녹색당은 이번 선거에서 의석을 늘렸다" * 2]) is None  # 2회 이상 — 통과
    assert excluded("녹색당", "녹색당 언급, 흉상 성추행 논란", ["파리 명물이 수난이다" + "x" * 30]) == "리드"
    assert excluded("녹색당", "녹색당 언급, 국내 기사", ["국내" * 20] * 3 + ["독일 미국 영국 사례"]) == "본문 3회"
    assert excluded("녹색당", "녹색당 언급, 국내 기사", ["국내" * 20] * 3 + ["독일 사례도 있다"]) is None
    assert excluded("녹색당", "녹색당 제목", [], "파리 특파원") == "리드"  # 본문 없으면 요약으로
    assert excluded("성소수자", "미국 대법원 판결", []) is None  # 다른 키워드엔 제외어 없음
    # 녹색당: 행위자로 등장하거나 정책 영역이 겹치면 통과
    assert excluded("녹색당", "녹색당, 탈핵 촉구 성명 발표", []) is None       # 행위자
    assert excluded("녹색당", "제목", ["기후위기 대응 시급하다는 지적이 나온다" * 2], "") is None  # 정책 겹침(리드에 없어도)
    # 본문 중간(리드 밖)에서만 스치면 이력 소개로 보고 제외
    assert excluded("녹색당", "제목", ["국내" * 20, "국내" * 20, "녹색당 출신 사업가가 사기 혐의로 기소됐다" * 2], "") == "접점없음"
    # 리드에 있으면(당사자로 등장) 행위자로 인정 — "진보 3당" 처럼 제목엔 당명이 안 나올 수 있어서
    assert excluded("녹색당", "진보 3당, 임명 철회 촉구", ["충북녹색당 등 진보 3당은 기자회견을 열었다" * 2], "") is None
    paras = ["녹색당 후보가 출마했다" + "x" * 30, "다른 문단" + "y" * 30]
    assert quote_for("녹색당", paras) == paras[0]
    assert quote_for("없는말", paras) == paras[0]      # 못 찾으면 첫 문단
    assert quote_for("녹색당", []) == ""               # 본문 없으면 인용구 생략
    assert len(quote_for("녹", ["녹" * 900])) == QUOTE_MAX + 1
    assert format_msg("한겨레", "제목", "http://x", "인용") == (
        "<b>[한겨레] 제목</b>\n\n<blockquote>인용</blockquote>\n\nhttp://x")
    assert format_msg("", "제목", "http://x", "") == "<b>제목</b>\n\nhttp://x"
    assert tidy("인권침해 소지가 있다며 개정을 권고했다. /김태연 기자") == "인권침해 소지가 있다며 개정을 권고했다."
    assert tidy("[서울=뉴시스] 김태연 기자 = 인권위는 21일 밝혔다.") == "인권위는 21일 밝혔다."
    assert tidy("본문이다. hong@news.co.kr") == "본문이다."
    assert tidy("본문이다. 김태연 기자 hong@news.co.kr") == "본문이다."
    assert tidy("김 기자와 만난 자리에서 말했다") == "김 기자와 만난 자리에서 말했다"  # 중간은 안 건드림
    assert clean("<b>퀴어</b>퍼레이드 &amp; 축제") == "퀴어퍼레이드 & 축제"
    assert format_msg("한겨레", "제목", "http://x", "인용") == (
        "<b>[한겨레] 제목</b>\n\n<blockquote>인용</blockquote>\n\nhttp://x")
    assert format_msg("", "제목", "http://x", "") == "<b>제목</b>\n\nhttp://x"
    assert tidy("인권침해 소지가 있다며 개정을 권고했다. /김태연 기자") == "인권침해 소지가 있다며 개정을 권고했다."
    assert tidy("[서울=뉴시스] 김태연 기자 = 인권위는 21일 밝혔다.") == "인권위는 21일 밝혔다."
    assert tidy("본문이다. hong@news.co.kr") == "본문이다."
    assert tidy("본문이다. 김태연 기자 hong@news.co.kr") == "본문이다."
    assert tidy("김 기자와 만난 자리에서 말했다") == "김 기자와 만난 자리에서 말했다"  # 중간은 안 건드림
    assert clean("따옴표 &quot;테스트&quot; ") == '따옴표 "테스트"'
    print("ok")


if __name__ == "__main__":
    if "--test" in sys.argv:
        selftest()
    elif "--check" in sys.argv:
        check()
    elif "--chatid" in sys.argv:
        chatid()
    else:
        main()
