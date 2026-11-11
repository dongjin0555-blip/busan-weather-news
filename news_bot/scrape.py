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


DESK_PLACES = ("서울", "세종", "전국")  # 전국 데스크 송고: 본문에 나온 지명을 사건 장소로 인정


def _regions(text):
    text = text.replace("부산물", "")  # '영농부산물' 등이 부산으로 잡히는 것 방지
    text = re.sub(r"\S+\s?(?:방향|행)(?=[\s,.…·)]|$)", " ", text)  # '창원 방향', '부산행' 등 목적지는 사건 장소가 아님
    return [r for r, ns in C.REGIONS.items() if any(n in text for n in ns)]


def _strip_noise(s):
    """'포장마차'의 '장마', '산불진화대'의 '산불·진화' 처럼 사건이 아닌 글자 일치 제거."""
    for noise in ("포장마차", "포차", "진화대", "산불감시", "감시원", "의용소방대"):
        s = s.replace(noise, " ")
    return s


def _is_prep(ttext):
    """대비·예방·우려성 제목: 실제 사건 표시어(발생·사망·발효 등)가 제목에 없으면 사건이 아님."""
    return any(w in ttext for w in C.PREP_WORDS) and not any(m in ttext for m in C.INCIDENT_MARKERS + C.ALERT_ACTIONS)


def title_ok(title):
    """제목만으로 본 최소 조건: 기상·재해·사고 키워드가 있고 제외어가 없어야 함 (저장된 기사 재점검용)."""
    t = _strip_noise(title)
    return any(k in t for k in C.KEYWORDS) and not any(w in t for w in C.EXCLUDE) and not _is_prep(t)


def _fire_ok(c, text):
    """'화재'류 키워드로만 걸린 기사는 규모·확산·특수시설 신호(또는 'N시간 만에')가 있어야 인정."""
    if any(k not in C.FIRE_ONLY_TERMS for k in c):
        return True  # 산불·선박·익수 등 기상 직결 사고 키워드가 함께 있음
    return any(cue in text for cue in C.FIRE_SCALE_CUES) or bool(re.search(r"\d+\s?시간", text))


def classify(title, desc=""):
    """(지역, 분류 라벨 리스트, 키워드, 중요도 점수, 제외 사유) 반환. 분류가 없으면 라벨 리스트는 빈 값.

    지역 판단: 제목·송고지 우선. 본문 첫 문장에서만 나온 지역은 기상/재해/사고 키워드가 있을 때만 인정
    (일반 기사 본문에 곁다리로 나온 지명에 걸리는 오탐 방지).
    """
    place, body = split_desc(desc)
    text = _strip_noise(f"{title} {body}")
    strong = _regions(f"{title} {place}")
    elsewhere = bool(place) and not any(d in place for d in DESK_PLACES) and not _regions(place)
    weak = [] if elsewhere else [r for r in _regions(body) if r not in strong]  # 타 지역 송고면 본문 지명 무시
    # 제목에 기상·재해·사고 키워드가 하나라도 있어야 기사로 인정 (본문에만 나온 '블랙아이스 우려' 같은 언급으로는 통과 불가)
    ttext = _strip_noise(title)
    title_signal = any(k in ttext for k in C.KEYWORDS)
    ex = next((w for w in C.EXCLUDE if w in text), None)
    a = [k for k in C.CAUSE if k in ttext]  # 기상 원인어는 제목에 있을 때만 인정 (본문의 '블랙아이스 우려' 등 무시)
    b = [k for k in C.DAMAGE if k in text]
    c = [k for k in C.NEEDS_DATA if k in ttext]  # 사고 유형도 제목 기준 (본문 속 '불이 났' 등으로는 통과 불가)
    is_cause = bool(a and (b or c))
    is_alert = any(t in ttext for t in C.ALERT_TERMS) and any(t in text for t in C.ALERT_ACTIONS)
    regions = strong + (weak if (a or b or c or is_alert) else [])
    prep = _is_prep(ttext)
    kinds = []
    if ex or not regions or not title_signal or prep:
        pass
    elif is_cause:
        kinds = [C.KIND_CAUSE]
    elif is_alert:
        kinds = [C.KIND_ALERT]
    elif c and any(m in text for m in C.INCIDENT_MARKERS) and _fire_ok(c, text):
        kinds = [C.KIND_DATA]
    score = sum(w for t, w in C.IMPORTANT_TERMS.items() if t in text)
    reason = (f"제외어({ex})" if ex else "지역 불일치" if not regions
              else "제목에 기상·사고 키워드 없음" if not title_signal else "대비·예방성 기사" if prep else "기상/사고 조합 없음")
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
