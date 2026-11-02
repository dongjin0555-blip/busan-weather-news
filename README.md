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
- cron-job.org (평일만): 작업 A `*/5 9-17 * * 1-5` (월~금 09:00~17:55), 작업 B `0 18 * * 1-5` (월~금 18:00)
- 공휴일은 따로 제외하지 않습니다(평일이면 동작).
