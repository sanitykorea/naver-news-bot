#!/usr/bin/env python3
"""네이버 뉴스 검색(최신순) → 새 기사만 텔레그램 채널로 발송. API 키 없음."""
import html, json, os, pathlib, re, sys, urllib.parse, urllib.request

KEYWORDS = [k.strip() for k in os.environ.get("KEYWORDS", "성소수자").split(",") if k.strip()]
SEEN = pathlib.Path(__file__).with_name("seen.json")
KEEP = 1000  # ponytail: 파일 하나로 중복 방지. 키워드/발송량 커지면 sqlite로.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"

# ponytail: 검색 API 대신 검색결과 HTML 파싱. 클래스명은 난독화라 안 쓰고,
# 제목 앵커의 data-heatmap-target=".tit" 만 앵커로 삼는다. 네이버가 바꾸면 여기만 고칠 것.
TITLE = re.compile(r'<a[^>]+href="(https?://[^"]+)"[^>]*data-heatmap-target="\.tit"[^>]*>(.*?)</a>', re.S)
NAVER_LINK = re.compile(r"https://n\.news\.naver\.com/mnews/article/[\d/]+")


def text(raw):
    return html.unescape(re.sub(r"<[^>]+>", "", raw)).replace("새 창 열림", "").strip()


def parse(page):
    """(제목, 링크) 목록. 네이버뉴스 페이지가 있으면 그 링크, 없으면 언론사 원문."""
    out, prev = [], 0
    for m in TITLE.finditer(page):
        chunk, prev = page[prev:m.end()], m.end()
        nav = NAVER_LINK.findall(chunk)
        out.append((text(m.group(2)), nav[-1] if nav else html.unescape(m.group(1))))
    return out


def search(kw):
    q = urllib.parse.urlencode({"where": "news", "query": kw, "sort": 1})
    req = urllib.request.Request(f"https://search.naver.com/search.naver?{q}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        return parse(r.read().decode("utf-8", "replace"))


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
        hits = search(kw)
        if not hits:
            print(f"경고: '{kw}' 결과 0건 — 네이버 HTML이 바뀌었을 수 있음", file=sys.stderr)
        for title, link in hits:
            if link not in known:
                known.add(link)
                new.append((kw, title, link))

    if not first_run:  # 첫 실행은 과거 기사 폭탄 방지용으로 목록만 저장
        for kw, title, link in reversed(new):
            send(f"<b>[{html.escape(kw)}]</b>\n{html.escape(title)}\n{link}")

    SEEN.write_text(json.dumps(([l for _, _, l in new] + seen)[:KEEP], ensure_ascii=False))
    print(f"{len(new)}건 {'저장' if first_run else '발송'}")


def selftest():
    page = ('<span><a href="https://n.news.naver.com/mnews/article/018/0006356362?sid=102">네이버뉴스</a></span>'
            '<a href="https://www.x.co.kr/1" data-heatmap-target=".tit"><span>제목 &amp; 하나</span>'
            '<span>새 창 열림</span></a>'
            '<a href="https://www.y.co.kr/2?a=1&amp;b=2" data-heatmap-target=".tit">제목 둘</a>')
    assert parse(page) == [("제목 & 하나", "https://n.news.naver.com/mnews/article/018/0006356362"),
                           ("제목 둘", "https://www.y.co.kr/2?a=1&b=2")], parse(page)
    print("ok")


if __name__ == "__main__":
    selftest() if "--test" in sys.argv else main()
