# 부산·울산·경남 기상·재해 뉴스

연합뉴스 RSS에서 부산·울산·경남의 기상·재해 기사를 골라
- 텔레그램 채널로 묶음 메시지 전송 (`news_bot/notify.py`, 09:00~18:00 15분 간격)
- HTML 대시보드 (`index.html` + 누적 `data.json`, GitHub Pages)

## 구성
- `news_bot/config.py` 지역·키워드 그룹(기상 요인 / 피해 / 기상자료 확인 사고 / 제외어)·운영 시간
- `news_bot/scrape.py` RSS 수집·분류, `news_bot/notify.py` 텔레그램 전송·`data.json` 누적
- `.github/workflows/news.yml` 실행 워크플로 (수동 실행 `workflow_dispatch`, 외부 스케줄러가 15분마다 호출)

## 설정
1. Settings → Secrets and variables → Actions: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
2. Settings → Pages: Branch `main` / `(root)`
3. 외부 스케줄러(cron-job.org 등)가 POST `https://api.github.com/repos/<계정>/<저장소>/actions/workflows/news.yml/dispatches` 를 `{"ref":"main"}` 로 호출
4. Actions → weather-news-telegram → Run workflow, `test` = `true` 로 테스트 전송

로컬 확인: `python -m http.server` → http://localhost:8000/
