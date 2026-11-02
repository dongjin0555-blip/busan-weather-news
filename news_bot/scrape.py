"""연합뉴스 RSS에서 부산·울산·경남 기상/재해 뉴스를 골라 수집 (API 키 불필요)."""
import html
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import config as C

UA = {"User-Agent": "Mozilla/5.0 (busan-weather-news-dashboard)"}


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def fetch_rss(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return ET.fromstring(r.read())


def parse_dt(text):
    """RFC822 또는 'YYYY-MM-DD HH:MM:SS' 형식 (시간대 없으면 KST로 간주)."""
    try:
        dt = parsedate_to_datetime(text)
    except Exception:
        dt = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(text.strip(), fmt)
                break
            except Exception:
                pass
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))
    return dt


DATELINE = re.compile(r"^\(([^=)]{1,12})=연합뉴스\)")


def split_desc(desc):
    """RSS 요약 '(송고지=연합뉴스) 기자 = 본문' 을 (송고지, 본문 첫 문장 부분)으로 분리."""
    m = DATELINE.match(desc)
    place = m.group(1) if m else ""
    body = re.sub(r"^\([^)]*\)\s*[^=]{0,40}=\s*", "", desc) if m else desc
    return place, body[:150]


def _regions(text):
    text = text.replace("부산물", "")  # '영농부산물' 등이 부산으로 잡히는 것 방지
    return [r for r, ns in C.REGIONS.items() if any(n in text for n in ns)]


def classify(title, desc=""):
    """(지역, 분류 라벨 리스트, 키워드, 중요도 점수, 제외 사유) 반환. 분류가 없으면 라벨 리스트는 빈 값.

    지역 판단: 제목·송고지 우선. 본문 첫 문장에서만 나온 지역은 기상/재해/사고 키워드가 있을 때만 인정
    (일반 기사 본문에 곁다리로 나온 지명에 걸리는 오탐 방지).
    """
    place, body = split_desc(desc)
    text = f"{title} {body}"
    strong = _regions(f"{title} {place}")
    weak = [r for r in _regions(body) if r not in strong]
    ex = next((w for w in C.EXCLUDE if w in text), None)
    a = [k for k in C.CAUSE if k in text]
    b = [k for k in C.DAMAGE if k in text]
    c = [k for k in C.NEEDS_DATA if k in text]
    is_cause = bool(a and (b or c))
    is_alert = any(t in text for t in C.ALERT_TERMS) and any(t in text for t in C.ALERT_ACTIONS)
    regions = strong + (weak if (a or b or c or is_alert) else [])
    kinds = []
    if ex or not regions:
        pass
    elif is_cause:
        kinds = [C.KIND_CAUSE]
    elif is_alert:
        kinds = [C.KIND_ALERT]
    elif c and any(m in text for m in C.INCIDENT_MARKERS):
        kinds = [C.KIND_DATA]
    score = sum(w for t, w in C.IMPORTANT_TERMS.items() if t in text)
    reason = f"제외어({ex})" if ex else ("지역 불일치" if not regions else "기상/사고 조합 없음")
    return regions, kinds, list(dict.fromkeys(a + b + c)), score, reason


def _fetch(url):
    try:
        return list(fetch_rss(url).iter("item"))
    except Exception as e:
        print(f"fetch fail [{url}]: {e}", file=sys.stderr)
        return []


rejected = []  # 가장 최근 collect()에서 지역은 맞지만 분류에서 탈락한 기사 (튜닝용)


def collect(max_age_hours=None):
    """최근 기사 dict 리스트 (링크 기준 중복 제거, 오래된 순). 탈락 기사는 `rejected`에 담김."""
    limit = timedelta(hours=max_age_hours or C.FETCH_HOURS)
    now = datetime.now(timezone.utc)
    items, rej = {}, {}
    for url in C.FEED_URLS:
        for it in _fetch(url):
            dt = parse_dt(it.findtext("pubDate") or "")
            if dt is None or now - dt > limit:
                continue
            title, desc = clean(it.findtext("title")), clean(it.findtext("description"))
            regions, kinds, kws, score, reason = classify(title, desc)
            link = (it.findtext("link") or "").split("?")[0]
            if not link or not regions:
                continue
            if not kinds:
                rej[link] = dict(link=link, title=title, dt=dt.isoformat(), regions=regions, reason=reason)
                continue
            items[link] = dict(link=link, title=title, desc=desc, dt=dt.isoformat(),
                               regions=regions, categories=kinds, keywords=kws, score=score,
                               important=kinds[0] == C.KIND_CAUSE or (kinds[0] == C.KIND_ALERT and "해제" not in title))
    rejected[:] = sorted(rej.values(), key=lambda x: x["dt"])
    return sorted(items.values(), key=lambda x: x["dt"])
