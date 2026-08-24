# 네이버 뉴스 → 텔레그램 채널

키워드로 네이버 뉴스를 검색해 새 기사만 텔레그램 채널로 보낸다.
제목·링크 아래 본문 중 키워드가 나오는 문단을 인용구로 붙인다.
네이버 뉴스 페이지(`n.news.naver.com`)가 있는 기사는 나오는 대로 한 건씩 보낸다.
없는 기사는 모아뒀다가 3시간마다(KST 0·3·6·9·12·15·18·21시) 키워드별로 묶어 한 통으로 보낸다.

## 같은 사안 중복
통신사 기사를 여러 매체가 받아쓰면 제목이 비슷한 기사가 줄줄이 나온다.
제목의 2글자 뭉치 자카드 유사도(`TOPIC_SIM`)로 같은 사안을 묶고, 매체 우선순위를 매긴다.

| 순위 | 매체 |
|---|---|
| 0 | 경향신문, 한겨레, 프레시안, 오마이뉴스 |
| 1 | 연합뉴스, 뉴시스, 뉴스1 |
| 2 | 그 외 |

한 사안은 기본적으로 한 번만 보낸다. 단:
- **더 우선하는 매체**가 뒤늦게 나오면 다시 보낸다 (그 외 매체 → 나중에 한겨레면 한겨레도 발송)
- **진보언론(순위 0)은 예외** — 같은 사안이라도 진보언론 기사면 매번 다시 보낸다.
  경향·한겨레·프레시안·오마이뉴스가 같은 사안을 각각 다뤄도 전부 발송된다는 뜻
- 통신사·그 외 매체는 이미 같은 등급으로 보낸 사안이 또 오면 보내지 않는다

## 설정
```
cp .env.example .env
```
`.env` 에 값을 채운다. `.gitignore` 에 있어 커밋되지 않는다.

- `NAVER_ID` / `NAVER_SECRET`: NCP 콘솔 > AI·NAVER API > Application > 인증 정보
  (NCP 발급 키는 `naverapihub.apigw.ntruss.com` + `X-NCP-APIGW-*` 헤더를 쓴다.
   developers.naver.com 키라면 `openapi.naver.com` + `X-Naver-Client-*` 로 바꿔야 한다)
- `TG_TOKEN`: @BotFather
- `TG_CHAT`: 숫자 채널 ID. 봇을 채널 관리자로 넣고 아무 글이나 올린 뒤 `python3 bot.py --chatid`
- `KEYWORDS`: 쉼표로 나열

## 실행
```
python3 bot.py            # 발송
python3 bot.py --check    # 키 인증 점검 (값은 출력하지 않음)
python3 bot.py --chatid   # 채널 숫자 ID 확인
python3 bot.py --test     # 필터·인용 로직 자체 점검
```
첫 실행은 발송 없이 `seen.json` 만 만든다(과거 기사 폭탄 방지).

## 해외 기사 제외
`EXCLUDE` 에 키워드별 제외어(국가명·한자 약칭·주요 도시)를 둔다. 판정은 3단계:

| 위치 | 처리 |
|---|---|
| 제목에 있음 | 제외 |
| 리드(첫 `LEAD_PARAS` 문단)에 있음 | 제외 |
| 본문 전체 `MENTION_LIMIT` 회 이상 | 제외 |
| 그 외 | 통과 (비교 사례로 한두 번 언급된 경우) |

제외된 기사는 실행 로그에 사유와 함께 찍힌다. 세다 싶으면 두 숫자만 올리면 된다.

## 자동화 (GitHub Actions)
`.github/workflows/news.yml` — 5분마다 실행(GitHub cron 최소 간격, 부하 시 지연될 수 있음).
상태(`seen.json`)는 커밋 대신 Actions 캐시에 보관한다.

저장소 Settings > Secrets and variables > Actions > Secrets 에 5개 등록:
`KEYWORDS` `NAVER_ID` `NAVER_SECRET` `TG_TOKEN` `TG_CHAT`
