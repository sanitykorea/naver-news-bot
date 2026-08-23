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

# ponytail: 키워드별 제외어. 기사 "제목"에 하나라도 있으면 발송 안 함. 늘어나면 여기만 추가.
# 헤드라인은 한자 약칭을 자주 쓰므로 같이 넣는다 (호주는 濠/豪 둘 다 쓰임).
EXCLUDE = {"녹색당": ("영국", "英", "프랑스", "佛", "호주", "濠", "豪",
                     "미국", "美", "캐나다", "加", "독일", "獨")}
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
QUOTE_MAX = 700


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


def excluded(kw, title):
    return any(w in title for w in EXCLUDE.get(kw, ()))


def paragraphs(link):
    """네이버뉴스 본문 문단 목록. 언론사 원문 링크는 형식이 제각각이라 포기하고 빈 목록."""
    if "n.news.naver.com" not in link:
        return []
    try:
        req = urllib.request.Request(link, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            page = r.read().decode("utf-8", "replace")
    except Exception:
        return []
    m = re.search(r'<article[^>]*id="dic_area"[^>]*>(.*?)</article>', page, re.S)
    if not m:
        return []
    body = re.sub(r"<(script|style)\b.*?</\1>", "", m.group(1), flags=re.S)
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = html.unescape(re.sub(r"<[^>]+>", "", body))
    return [p.strip() for p in body.split("\n") if len(p.strip()) > 30]


def quote_for(kw, paras, desc):
    """키워드가 나오는 첫 문단. 본문을 못 읽으면 검색 결과 요약으로 대체."""
    hit = next((p for p in paras if kw in p), None) or desc
    return hit[:QUOTE_MAX] + ("…" if len(hit) > QUOTE_MAX else "")


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
            if first_run or excluded(kw, title):
                continue  # 제외건도 seen 에는 남겨 다시 안 보게 한다
            queue.append((title, link, quote_for(kw, paragraphs(link), desc)))

    for title, link, quote in reversed(queue):  # 오래된 것부터
        send(f"{html.escape(title)}\n{link}\n\n<blockquote>{html.escape(quote)}</blockquote>")

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
    assert excluded("녹색당", "英 총선서 녹색당 약진")
    assert excluded("녹색당", "독일 녹색당 지지율")
    assert not excluded("녹색당", "고양에는 골프장보다 숲이 더 필요하다")
    assert not excluded("성소수자", "미국 대법원 판결")  # 다른 키워드엔 제외어 없음
    paras = ["녹색당 후보가 출마했다" + "x" * 30, "다른 문단" + "y" * 30]
    assert quote_for("녹색당", paras, "요약") == paras[0]
    assert quote_for("없는말", paras, "요약") == "요약"
    assert quote_for("녹색당", [], "요약") == "요약"
    assert len(quote_for("녹", ["녹" * 900], "")) == QUOTE_MAX + 1
    assert clean("<b>퀴어</b>퍼레이드 &amp; 축제") == "퀴어퍼레이드 & 축제"
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
