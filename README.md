# 네이버 뉴스 → 텔레그램 채널

API 키 없음. 네이버 뉴스 검색 결과(최신순) HTML을 긁어서 새 기사만 발송한다.

## 준비 (텔레그램만)
@BotFather → `/newbot` → 토큰 받기. 채널 만들고 봇을 **관리자**로 추가(게시 권한).
`TG_CHAT`은 공개 채널이면 `@채널아이디`, 비공개면 숫자 ID.

## 실행
```
KEYWORDS="성소수자,퀴어,트랜스젠더" TG_TOKEN=... TG_CHAT=@my_channel python3 bot.py
```
첫 실행은 발송 없이 `seen.json`만 만든다(과거 기사 폭탄 방지). 두 번째부터 새 기사만 발송.
키워드당 최신 10건씩 확인하므로 30분~1시간 주기면 충분하다.

## 자동화
- **맥에서**: `crontab -e` → `*/30 * * * * cd /Users/scottyoon/Claude_WORKSPACE/naver-news-bot && KEYWORDS="..." TG_TOKEN=... TG_CHAT=... /usr/bin/python3 bot.py`
  (맥이 깨어 있을 때만 동작)
- **GitHub Actions**: `.github/workflows/news.yml`. Secrets에 `TG_TOKEN`/`TG_CHAT`,
  Variables에 `KEYWORDS` 등록. 단 네이버가 클라우드 IP를 막을 수 있으니 첫 실행 로그에
  `결과 0건` 경고가 뜨는지 확인할 것. 막히면 맥 cron이나 집 서버로.

## 깨질 때
네이버가 검색 페이지 HTML을 바꾸면 `결과 0건` 경고가 뜬다. `bot.py`의 `TITLE` 정규식만 고치면 된다.
`python3 bot.py --test` 로 파서 자체 점검.
