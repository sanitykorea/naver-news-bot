#!/usr/bin/env python3
"""네이버 뉴스 검색(최신순) → 새 기사만 텔레그램 채널로 발송."""
import html, json, os, pathlib, re, sys, urllib.error, urllib.parse, urllib.request

HERE = pathlib.Path(__file__).parent
ENV, SEEN = HERE / ".env", HERE / "seen.json"
KEEP = 1000  # ponytail: 파일 하나로 중복 방지. 키워드/발송량 커지면 sqlite로.

if ENV.exists():  # ponytail: python-dotenv 대신 4줄
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))

KEYWORDS = [k.strip() for k in os.environ.get("KEYWORDS", "성소수자").split(",") if k.strip()]

# ponytail: 키워드별 제외어. 국가명 + 헤드라인용 한자 약칭 + 주요 도시/지역.
# 도시까지 넣는 이유: "파리 명물 흉상" 처럼 제목에 국가명이 안 나오는 해외 기사를 잡기 위해.
EXCLUDE = {"녹색당": ("영국", "英", "런던", "잉글랜드", "스코틀랜드", "웨일스",
                     "프랑스", "佛", "파리", "마르세유", "리옹",
                     "호주", "濠", "豪", "시드니", "멜버른", "캔버라",
                     "미국", "美", "워싱턴", "뉴욕", "백악관", "실리콘밸리",
                     "캐나다", "加", "토론토", "밴쿠버", "오타와",
                     "독일", "獨", "베를린", "뮌헨", "함부르크")}
# ponytail: 위치+빈도 휴리스틱. 제목/리드에 나오면 그 기사의 주제고,
# 중반 이후 한두 번은 비교 사례라 통과시킨다. 오탐이 잦으면 숫자만 조절할 것.
LEAD_PARAS = 2      # 리드로 볼 문단 수
MENTION_LIMIT = 3   # 본문 전체에서 이 횟수 이상 나오면 비중이 높다고 본다
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
QUOTE_MAX = 700
# ponytail: 키워드를 추가하면 그 키워드의 과거 기사가 통째로 "새 기사"가 된다.
# 한 번에 이만큼 넘으면 발송을 건너뛰고 기록만 한다 (첫 실행과 같은 처리).
MAX_BURST = 30


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


def excluded(kw, title, paras, desc=""):
    """제외 사유 문자열, 통과면 None."""
    words = EXCLUDE.get(kw, ())
    if not words:
        return None
    if any(w in title for w in words):
        return "제목"
    lead = " ".join(paras[:LEAD_PARAS]) or desc  # 본문을 못 읽으면 검색 요약으로 대신
    if any(w in lead for w in words):
        return "리드"
    body = " ".join(paras)
    n = sum(body.count(w) for w in words)
    return f"본문 {n}회" if n >= MENTION_LIMIT else None


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
    return press, [p.strip() for p in body.split("\n") if len(p.strip()) > 30]


def quote_for(kw, paras):
    """키워드가 나오는 첫 문단, 없으면 첫 문단.
    본문을 못 읽으면 빈 값 — 링크 미리보기가 요약을 대신하므로 인용구를 생략한다."""
    hit = next((p for p in paras if kw in p), paras[0] if paras else "")
    return hit[:QUOTE_MAX] + ("…" if len(hit) > QUOTE_MAX else "")


def format_msg(press, title, link, quote):
    head = f"[{press}] {title}" if press else title
    block = f"<blockquote>{html.escape(quote)}</blockquote>\n\n" if quote else ""
    return f"<b>{html.escape(head)}</b>\n\n{block}{link}"


def send(msg):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
        data=json.dumps({"chat_id": os.environ["TG_CHAT"], "text": msg,
                         "parse_mode": "HTML"}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
    except urllib.error.HTTPError as e:  # 텔레그램 에러 사유를 그대로 보여준다
        raise SystemExit(f"텔레그램 발송 실패 {e.code}: {e.read().decode()}")


def main():
    first_run = not SEEN.exists()
    seen = [] if first_run else json.loads(SEEN.read_text())
    known, fresh, queue = set(seen), [], []
    for kw in KEYWORDS:
        for title, link, desc in search(kw):
            if link in known:
                continue
            known.add(link)
            fresh.append(link)
            if first_run:
                continue
            press, paras = article(link)
            why = excluded(kw, title, paras, desc)
            if why:  # 제외건도 seen 에는 남겨 다시 안 보게 한다
                print(f"  제외({why}): {title[:40]}")
                continue
            queue.append((press, title, link, quote_for(kw, paras)))

    if len(queue) > MAX_BURST:
        print(f"발송 대상 {len(queue)}건 — {MAX_BURST}건을 넘어 발송을 건너뛰고 기록만 한다.")
        print("(키워드를 추가했다면 정상. 다음 실행부터 새 기사만 발송된다)")
        queue = []
    for press, title, link, quote in reversed(queue):  # 오래된 것부터
        send(format_msg(press, title, link, quote))

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
    assert excluded("녹색당", "英 총선서 녹색당 약진", []) == "제목"
    assert excluded("녹색당", "흉상 성추행 논란", ["파리 명물이 수난이다" + "x" * 30]) == "리드"
    assert excluded("녹색당", "국내 기사", ["국내" * 20] * 3 + ["독일 미국 영국 사례"]) == "본문 3회"
    assert excluded("녹색당", "국내 기사", ["국내" * 20] * 3 + ["독일 사례도 있다"]) is None
    assert excluded("녹색당", "제목", [], "파리 특파원") == "리드"  # 본문 없으면 요약으로
    assert excluded("성소수자", "미국 대법원 판결", []) is None  # 다른 키워드엔 제외어 없음
    paras = ["녹색당 후보가 출마했다" + "x" * 30, "다른 문단" + "y" * 30]
    assert quote_for("녹색당", paras) == paras[0]
    assert quote_for("없는말", paras) == paras[0]      # 못 찾으면 첫 문단
    assert quote_for("녹색당", []) == ""               # 본문 없으면 인용구 생략
    assert len(quote_for("녹", ["녹" * 900])) == QUOTE_MAX + 1
    assert format_msg("한겨레", "제목", "http://x", "인용") == (
        "<b>[한겨레] 제목</b>\n\n<blockquote>인용</blockquote>\n\nhttp://x")
    assert format_msg("", "제목", "http://x", "") == "<b>제목</b>\n\nhttp://x"
    assert clean("<b>퀴어</b>퍼레이드 &amp; 축제") == "퀴어퍼레이드 & 축제"
    assert format_msg("한겨레", "제목", "http://x", "인용") == (
        "<b>[한겨레] 제목</b>\n\n<blockquote>인용</blockquote>\n\nhttp://x")
    assert format_msg("", "제목", "http://x", "") == "<b>제목</b>\n\nhttp://x"
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
