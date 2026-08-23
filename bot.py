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


def clean(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def search(kw):
    q = urllib.parse.urlencode({"query": kw, "display": 30, "sort": "date"})
    req = urllib.request.Request(
        f"https://openapi.naver.com/v1/search/news.json?{q}",
        headers={"X-Naver-Client-Id": os.environ["NAVER_ID"],
                 "X-Naver-Client-Secret": os.environ["NAVER_SECRET"]})
    with urllib.request.urlopen(req, timeout=20) as r:
        items = json.load(r)["items"]
    # 네이버뉴스 페이지가 있으면 그 링크, 없으면 언론사 원문
    return [(clean(i["title"]), i.get("link") or i["originallink"]) for i in items]


def send(msg):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{os.environ['TG_TOKEN']}/sendMessage",
        data=json.dumps({"chat_id": os.environ["TG_CHAT"], "text": msg,
                         "parse_mode": "HTML"}).encode(),
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=20).read()


def main():
    first_run = not SEEN.exists()
    seen = [] if first_run else json.loads(SEEN.read_text())
    known, new = set(seen), []
    for kw in KEYWORDS:
        for title, link in search(kw):
            if link not in known:
                known.add(link)
                new.append((kw, title, link))

    if not first_run:  # 첫 실행은 과거 기사 폭탄 방지용으로 목록만 저장
        for kw, title, link in reversed(new):  # 오래된 것부터
            send(f"<b>[{html.escape(kw)}]</b>\n{html.escape(title)}\n{link}")

    SEEN.write_text(json.dumps(([l for _, _, l in new] + seen)[:KEEP], ensure_ascii=False))
    print(f"{len(new)}건 {'저장' if first_run else '발송'}")


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
    assert clean("<b>퀴어</b>퍼레이드 &amp; 축제") == "퀴어퍼레이드 & 축제"
    assert clean("따옴표 &quot;테스트&quot; ") == '따옴표 "테스트"'
    print("ok")


if __name__ == "__main__":
    if "--test" in sys.argv:
        selftest()
    elif "--check" in sys.argv:
        check()
    else:
        main()
