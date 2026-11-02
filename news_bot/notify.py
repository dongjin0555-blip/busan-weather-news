"""새 기사를 모아 텔레그램 채널로 묶음(1개 메시지) 전송 (15분마다 실행).

환경변수: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (없으면 전송 없이 출력만 하는 dry-run)
전송 이력: news_bot/sent.json (링크 -> 기사 시각), 7일 보관
"""
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import config as C
import scrape

SENT_FILE = Path(__file__).with_name("sent.json")
DATA_FILE = Path(__file__).resolve().parent.parent / "data.json"   # 대시보드(index.html)가 읽는 파일
KEEP_DAYS = 14         # 대시보드용 기사 보관 일수
KEEP_REJECTED_DAYS = 2 # 제외된 기사 보관 일수
MAX_REJECTED = 300
KST = timezone(timedelta(hours=9))
MAX_PER_RUN = 40       # 1회 묶음에 담을 최대 기사 수
FIRST_RUN_HOURS = 3    # 이력 파일이 없을 때(첫 실행)는 최근 N시간 기사만 전송


def tg_send(token, chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    for _ in range(3):
        try:
            urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data, timeout=30).read()
            return
        except urllib.error.HTTPError as e:
            body = {}
            try:
                body = json.load(e)
            except Exception:
                pass
            if e.code != 429:
                # 텔레그램이 알려주는 정확한 사유를 로그에 남김 (토큰은 출력하지 않음)
                raise SystemExit(f"텔레그램 전송 실패 HTTP {e.code}: {body.get('description', '사유 없음')}")
            time.sleep(body.get("parameters", {}).get("retry_after", 5) + 1)
    raise RuntimeError("telegram rate limit")


def format_line(it):
    tags = "·".join(it["regions"]) + " / " + "·".join(it["categories"])
    head = "🚨" if it["important"] else "▪️"
    return (f'{head} <b>{html.escape(it["title"])}</b> ({html.escape(tags)}) '
            f'<a href="{html.escape(it["link"], quote=True)}">원문보기</a>')


def build_digest(items, now=None, limit=3800):
    """기사 여러 건을 하나의 메시지로 묶음 (주요 기사 먼저). 길이 초과 시에만 여러 메시지로 분할."""
    now = now or datetime.now(KST)
    ordered = sorted(items, key=lambda i: (not i["important"], i["dt"]))
    lines = [format_line(i) for i in ordered]
    head = f"📋 <b>기상·재해 뉴스 {len(items)}건</b> ({now:%m/%d %H:%M} 기준)\n"
    msgs, cur = [], head
    for ln in lines:
        if len(cur) + len(ln) + 2 > limit:
            msgs.append(cur)
            cur = ""
        cur += "\n" + ln + "\n"
    msgs.append(cur)
    if len(msgs) > 1:
        msgs = [m + f"\n({k}/{len(msgs)})" for k, m in enumerate(msgs, 1)]
    return msgs


def chat_label(token, chat_id):
    """전송 대상 채팅 이름 (테스트 메시지에서 올바른 채널로 가는지 확인용)."""
    try:
        q = urllib.parse.urlencode({"chat_id": chat_id})
        r = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getChat?{q}", timeout=30))["result"]
        name = r.get("title") or " ".join(filter(None, [r.get("first_name"), r.get("last_name")])) or "이름 없음"
        kind = {"channel": "채널", "supergroup": "그룹", "group": "그룹", "private": "개인 대화"}.get(r.get("type"), r.get("type", ""))
        user = f" (@{r['username']})" if r.get("username") else ""
        return f"{kind} '{name}'{user}"
    except Exception as e:
        return f"확인 실패({type(e).__name__})"


def run_test(token, chat_id):
    """연결 확인용: 이력과 무관하게 최신 기사 최대 3건을 묶어 보내고 이력은 건드리지 않는다."""
    items = scrape.collect()
    print(f"collected={len(items)}")
    if not items:
        # 기사가 없어도 텔레그램 연결 자체는 확인할 수 있게 안내 메시지를 보내고 정상 종료
        tg_send(token, chat_id, f"✅ <b>테스트 전송</b>\n전송 대상: {html.escape(chat_label(token, chat_id))}\n연결은 정상입니다. "
                "지금 연합뉴스 RSS에 조건(부산·울산·경남 기상·재해)에 맞는 기사가 없습니다. "
                "기사가 나오면 자동으로 이 채널에 전송됩니다.")
        print("sent test: no matching articles (connection ok)")
        return
    pick = sorted(items, key=lambda i: i["dt"])[-3:]
    for m in build_digest(pick):
        tg_send(token, chat_id, f"✅ <b>테스트 전송</b> → {html.escape(chat_label(token, chat_id))}\n" + m)
    print("sent test:", [i["title"] for i in pick])


def write_data(items, rejected):
    """대시보드용 누적 데이터 저장: 기존 기사와 병합하고 오래된 것은 정리."""
    try:
        old = json.loads(DATA_FILE.read_text())
    except Exception:
        old = {}
    now = datetime.now(timezone.utc)
    keep = lambda dt, days: now - datetime.fromisoformat(dt) <= timedelta(days=days)
    news = {i["link"]: i for i in old.get("items", [])}
    for it in items:
        news[it["link"]] = {k: it[k] for k in ("link", "title", "dt", "regions", "categories",
                                                "keywords", "score", "important")}
    rej = {i["link"]: i for i in old.get("rejected", [])}
    for it in rejected:
        rej[it["link"]] = {k: it[k] for k in ("link", "title", "dt", "regions", "reason")}
    out = {
        "updated": now.isoformat(),
        "items": sorted((i for i in news.values() if keep(i["dt"], KEEP_DAYS)),
                        key=lambda i: i["dt"], reverse=True),
        "rejected": sorted((i for i in rej.values() if keep(i["dt"], KEEP_REJECTED_DAYS)),
                           key=lambda i: i["dt"], reverse=True)[:MAX_REJECTED],
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")))


def run_window(token, chat_id, since, until):
    """구간 테스트: KST 'YYYY-MM-DD HH:MM' 두 시각 사이에 발행된 기사를 묶음으로 전송 (이력/데이터 파일은 건드리지 않음)."""
    def parse(v):
        return datetime.strptime(v.strip(), "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    t0, t1 = parse(since), parse(until)
    items = [i for i in scrape.collect(max_age_hours=96)
             if t0 <= datetime.fromisoformat(i["dt"]) <= t1]
    label = f"{t0:%m/%d %H:%M}~{t1:%m/%d %H:%M}"
    print(f"window {label}: {len(items)} items")
    if not items:
        tg_send(token, chat_id, f"✅ <b>구간 테스트</b> ({label})\n해당 구간에 연합뉴스 RSS에서 가져올 수 있는 "
                "조건 일치 기사가 없습니다. (RSS는 최신 기사 일부만 제공해, 오래된 기사는 이미 빠졌을 수 있습니다)")
        return
    for m in build_digest(items):
        tg_send(token, chat_id, f"✅ <b>구간 테스트</b> ({label})\n" + m)
    print("sent window test:", [i["title"] for i in items])


def within_hours(now=None):
    """KST 09:00~18:30 (18:00 슬롯이 조금 늦어져도 허용)."""
    now = now or datetime.now(KST)
    return C.COLLECT_START_HOUR * 60 <= now.hour * 60 + now.minute <= C.COLLECT_END_HOUR * 60 + 30


def debug_feed():
    """원본 RSS 요약 형식 점검용 (지역 분류 개선 근거). 전송/저장 없음."""
    for url in C.FEED_URLS:
        items = list(scrape.fetch_rss(url).iter("item"))
        print(f"feed {url}: {len(items)} items")
        for it in items[:12]:
            print("T:", scrape.clean(it.findtext("title")))
            print("D:", scrape.clean(it.findtext("description"))[:160])
            print("-")


def main():
    if os.environ.get("DEBUG_FEED"):
        return debug_feed()
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    dry = not (token and chat_id)
    if "--only-hours" in sys.argv and not within_hours():
        # GitHub 스케줄이 늦게 실행되어도 운영 시간 밖에는 전송하지 않음 (다음 운영 시간에 이어서 전송)
        print("운영 시간(09:00~18:30 KST) 밖이라 건너뜁니다")
        return
    if os.environ.get("WIN_SINCE") and os.environ.get("WIN_UNTIL"):
        if dry:
            raise SystemExit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없습니다")
        return run_window(token, chat_id, os.environ["WIN_SINCE"], os.environ["WIN_UNTIL"])
    if "--test" in sys.argv:
        if dry:
            raise SystemExit("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 가 없습니다")
        return run_test(token, chat_id)
    first = not SENT_FILE.exists()
    sent = {} if first else json.loads(SENT_FILE.read_text())

    items = scrape.collect()
    write_data(items, scrape.rejected)  # 전송 성공 여부와 무관하게 대시보드 데이터는 항상 갱신
    if first:
        limit = (datetime.now(timezone.utc) - timedelta(hours=FIRST_RUN_HOURS)).isoformat()
        for it in items:  # 첫 실행: 오래된 기사는 보낸 것으로 처리해 폭주 방지
            if it["dt"] < limit:
                sent[it["link"]] = it["dt"]
    new = [i for i in items if i["link"] not in sent]
    new.sort(key=lambda i: i["dt"])
    new = new[-MAX_PER_RUN:]
    print(f"collected={len(items)} new={len(new)} dry_run={dry}")

    if new:
        msgs = build_digest(new)
        if dry:
            print("\n----\n".join(msgs))
        else:
            for m in msgs:
                tg_send(token, chat_id, m)
                time.sleep(1.5)
            for it in new:
                sent[it["link"]] = it["dt"]

    if not dry:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        sent = {k: v for k, v in sent.items() if v > cutoff}
        SENT_FILE.write_text(json.dumps(sent, ensure_ascii=False, indent=0))


if __name__ == "__main__":
    main()
