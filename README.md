# 네이버 뉴스 → 텔레그램 채널

네이버 검색 API로 키워드별 최신 기사를 확인해 새 것만 텔레그램 채널로 보낸다.

## 설정
```
cp .env.example .env
```
`.env` 를 열어 값만 채운다 (NAVER_ID/NAVER_SECRET, TG_TOKEN, TG_CHAT, KEYWORDS).
`.env` 는 `.gitignore` 에 있으니 커밋되지 않는다. 키를 채팅·이슈·커밋에 붙여넣지 말 것.

- `TG_CHAT`: 공개 채널이면 `@채널아이디`, 비공개면 숫자 ID
- 봇은 채널 **관리자**(게시 권한)로 추가되어 있어야 한다

## 실행
```
python3 bot.py
```
첫 실행은 발송 없이 `seen.json`만 만든다(과거 기사 폭탄 방지). 두 번째부터 새 기사만 발송.
키워드당 최신 30건 확인. 무료 한도 25,000회/일이라 10분 주기로 돌려도 남는다.

## 자동화
- **맥**: `crontab -e` → `*/30 * * * * /usr/bin/python3 bot.py`
  (`.env` 를 읽으므로 cron 에 키를 쓸 필요 없음. 맥이 깨어 있을 때만 동작)
- **GitHub Actions**: `.github/workflows/news.yml`. 저장소 Settings > Secrets 에
  `NAVER_ID` `NAVER_SECRET` `TG_TOKEN` `TG_CHAT`, Variables 에 `KEYWORDS` 등록.
  30분마다 실행하고 `seen.json` 을 커밋해 상태를 유지한다.

## 참고
`git log` 에 API 키 없이 검색 페이지를 파싱하는 이전 버전이 남아 있다 (`git show HEAD~1:bot.py`).
