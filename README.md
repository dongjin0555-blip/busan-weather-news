# 부산·울산·경남 기상·재해 뉴스

연합뉴스 RSS에서 부산·울산·경남의 기상·재해 기사를 골라
- 텔레그램 채널로 묶음 메시지 전송 (`news_bot/notify.py`, 09:00~18:00 15분 간격)
- HTML 대시보드 (`index.html` + 누적 `data.json`, GitHub Pages)

## 구성
- `news_bot/config.py` 지역·키워드 그룹(기상 요인 / 피해 / 기상자료 확인 사고 / 제외어)·운영 시간
- `news_bot/scrape.py` RSS 수집·분류, `news_bot/notify.py` 텔레그램 전송·`data.json` 누적
- `.github/workflows/news.yml` 실행 워크플로 (수동 실행 `workflow_dispatch`, 외부 스케줄러가 5분마다 호출)

## 설정
1. Settings → Secrets and variables → Actions: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
2. Settings → Pages: Branch `main` / `(root)`
3. 외부 스케줄러(cron-job.org 등)가 POST `https://api.github.com/repos/<계정>/<저장소>/actions/workflows/news.yml/dispatches` 를 `{"ref":"main"}` 로 호출
4. Actions → weather-news-telegram → Run workflow, `test` = `true` 로 테스트 전송

로컬 확인: `python -m http.server` → http://localhost:8000/

## 갱신 방식
연합뉴스 RSS에는 새 기사 알림(푸시) 기능이 없어서, 외부 스케줄러가 짧은 간격(권장 5분)으로 워크플로를 호출해 확인합니다.
- 새 기사가 있을 때만 텔레그램 전송, `data.json` 저장(커밋), 홈페이지 재배포가 일어납니다. 새 기사가 없으면 아무것도 바뀌지 않습니다.
- 홈페이지 상단의 시각은 "마지막으로 새 기사가 반영된 시각"입니다. 탈락한 기사는 Actions 로그(`rejected [...]`)에서 확인합니다.
- cron-job.org 작업 3개
  - A (전송, 평일): `*/5 8-17 * * 1-5` — 08:00~17:55, 5분 간격. 08:00 첫 실행이 **밤사이·전날 기사를 날짜별로 묶어 아침 브리핑**으로 전송
  - B (전송, 평일): `0 18 * * 1-5` — 18:00 마지막 실행
  - C (수집만, 매일): `15 * * * *` , 요청 본문 `{"ref":"main","inputs":{"mode":"collect"}}` — 밤·주말에 전송 없이 기사만 모아 둠
  - 공휴일은 따로 제외하지 않습니다(평일이면 동작).
- 18시 이후·주말 기사는 C가 모아 두었다가 다음 평일 08:00 브리핑에 포함됩니다. (RSS는 최근 약 120건만 담고 있어 C가 없으면 밤사이 기사는 사라집니다)
