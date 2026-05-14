"""
KCMO Weekly - madini_html_collector.py
Korea Critical Minerals ODA Weekly

탄자니아 광물부(madini.go.tz)의 보도자료 본문 페이지를 직접 수집합니다.
이전 pdf_collector.py 접근(PDF 직접 크롤링)이 사이트 구조와 맞지 않아
방향을 전환한 것입니다.

작동 원리:
1. 광물부 메인 페이지(/) 방문해서 본문 URL들(/page/{uuid}/) 수집
2. 각 본문 페이지 방문해서 제목·날짜·본문 텍스트 추출
3. 30일 신선도 필터 적용 (최근 30일 이내만)
4. processed_pages.json 레지스트리로 중복 방지
5. raw_*.json에 article로 병합

핵심 차이점 (pdf_collector.py 대비):
- PDF 다운로드/추출 단계 없음 (HTML 본문이 곧 1차 자료)
- pdfplumber 의존성 없음 (requests + BeautifulSoup만 사용)
- 훨씬 빠르고 안정적

출력:
  data/processed_pages.json - 처리한 페이지 URL 추적
  data/madini_pages_YYYY-MM-DD.json - 그 주의 수집 결과
"""
import os
import sys
import json
import re
import hashlib
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# -----------------------------------------------------------------
# Config
# -----------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR
DATA_DIR = ROOT_DIR / "data"
PROCESSED_REGISTRY = DATA_DIR / "processed_pages.json"
DATA_DIR.mkdir(exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (compatible; KCMO-Weekly/1.0; "
    "+https://dolmudaddy.github.io/korea-oda-minerals/)"
)

# 타임아웃과 재시도 - madini.go.tz 응답이 느림
REQUEST_TIMEOUT = 90  # 30s에서 90s로 증가
RETRY_COUNT = 3
RETRY_BACKOFF = 5  # seconds

FRESHNESS_DAYS = 30

# 메인 페이지에서 본문 페이지 URL을 발견할 진입점
# 메인 페이지가 최신 보도자료 + Latest News + Latest Updates를 모두 노출함
ENTRY_POINTS = [
    "https://www.madini.go.tz/",
    "https://www.madini.go.tz/otherpage/?p=latest-news",
    "https://www.madini.go.tz/otherpage/?p=latest-updates",
    "https://www.madini.go.tz/otherpage/?p=press-release",
    "https://www.madini.go.tz/otherpage/?p=public-notes",
]

# 본문 페이지 URL 패턴: /page/{uuid}/
PAGE_URL_PATTERN = re.compile(
    r"https?://www\.madini\.go\.tz/page/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
    r"[0-9a-f]{4}-[0-9a-f]{12}/?",
    re.IGNORECASE,
)


# -----------------------------------------------------------------
# Registry management
# -----------------------------------------------------------------
def load_registry():
    if not PROCESSED_REGISTRY.exists():
        return {}
    try:
        with open(PROCESSED_REGISTRY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_registry(registry):
    with open(PROCESSED_REGISTRY, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


# -----------------------------------------------------------------
# HTTP with retry
# -----------------------------------------------------------------
def fetch_with_retry(url, session):
    """타임아웃·연결 오류에 대한 재시도 로직."""
    last_exc = None
    for attempt in range(RETRY_COUNT):
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            return r
        except (requests.Timeout, requests.ConnectionError,
                requests.HTTPError) as e:
            last_exc = e
            if attempt < RETRY_COUNT - 1:
                wait = RETRY_BACKOFF * (attempt + 1)
                print(f"    [retry {attempt+1}/{RETRY_COUNT}] waiting {wait}s after {type(e).__name__}")
                time.sleep(wait)
    print(f"    [FAIL] all {RETRY_COUNT} attempts failed: {last_exc}")
    return None


# -----------------------------------------------------------------
# Discover page URLs from entry points
# -----------------------------------------------------------------
def discover_page_urls(entry_url, session):
    """진입점 페이지에서 /page/{uuid}/ URL들을 모두 추출."""
    r = fetch_with_retry(entry_url, session)
    if r is None:
        return []

    # HTML에서 패턴 매칭으로 URL 추출 (정규식)
    matches = PAGE_URL_PATTERN.findall(r.text)

    # URL 정규화 (끝의 / 통일)
    urls = []
    seen = set()
    for m in matches:
        normalized = m.rstrip("/") + "/"
        if normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)

    return urls


# -----------------------------------------------------------------
# Parse individual page
# -----------------------------------------------------------------
DATE_REGEX_PATTERNS = [
    # "March 19, 2026, 12:30 p.m." 또는 "Feb. 6, 2026, 3:18 p.m."
    re.compile(
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})",
        re.IGNORECASE,
    ),
    # "2026-03-19" or "19/03/2026"
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
    re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})"),
]

MONTH_NAMES = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_date_from_text(text):
    """텍스트에서 날짜 추출. 못 찾으면 None."""
    if not text:
        return None

    # 패턴 1: 영문 월 이름
    m = re.search(
        r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})",
        text, re.IGNORECASE,
    )
    if m:
        try:
            month = MONTH_NAMES[m.group(1).lower()[:3]]
            day = int(m.group(2))
            year = int(m.group(3))
            return datetime(year, month, day, tzinfo=timezone.utc)
        except (KeyError, ValueError):
            pass

    # 패턴 2: ISO
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)),
                            int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def parse_page_content(page_url, session):
    """본문 페이지에서 제목·날짜·본문 텍스트 추출.

    Returns:
        dict with keys: title, body, published_date, raw_html_size
        or None on fetch failure
    """
    r = fetch_with_retry(page_url, session)
    if r is None:
        return None

    soup = BeautifulSoup(r.content, "lxml")

    # 1. 제목 추출 - <title> 태그 또는 페이지 내 <h1>/<h2>/<h3>
    title = ""
    if soup.title:
        title = soup.title.get_text(strip=True)
        # 사이트 공통 부분 제거
        title = title.replace("Ministry of Minerals - Republic of Tanzania", "").strip(" -|")
    if not title:
        for tag in ["h1", "h2", "h3"]:
            h = soup.find(tag)
            if h:
                title = h.get_text(strip=True)
                if title and len(title) > 10:
                    break

    # 2. 본문 추출 - <main>, <article>, 또는 <div class="content"> 등
    body = ""
    # 가장 흔한 본문 컨테이너 후보들
    main_candidates = [
        soup.find("main"),
        soup.find("article"),
        soup.find("div", class_=re.compile(r"content|main|body|article", re.IGNORECASE)),
    ]
    body_node = next((n for n in main_candidates if n is not None), None)

    if body_node is None:
        # fallback: 페이지 전체에서 텍스트 추출
        body_node = soup.body or soup

    # 네비게이션·푸터 등 제외
    for unwanted in body_node.find_all(["nav", "header", "footer", "script", "style", "aside"]):
        unwanted.decompose()

    body_text = body_node.get_text(separator="\n", strip=True)
    # 공백 정규화
    body_text = re.sub(r"\n{3,}", "\n\n", body_text)
    body_text = re.sub(r" {2,}", " ", body_text)
    body = body_text

    # 3. 날짜 추출 - 페이지 본문에서 발견된 첫 번째 날짜
    # 본문 처음 1000자에서 찾기 (보통 헤더 근처에 있음)
    published_date = parse_date_from_text(body[:2000])

    return {
        "title": title[:300] if title else "",
        "body": body,
        "published_date": published_date,
        "raw_html_size": len(r.content),
    }


# -----------------------------------------------------------------
# Score page article
# -----------------------------------------------------------------
KOREA_KEYWORDS = ["Korea", "Kikorea", "Jamhuri ya Korea", "KIGAM", "KOICA", "EDCF"]
ODA_KEYWORDS = {
    "ushirikiano wa maendeleo": 4,
    "makubaliano": 3,
    "mkataba": 3,
    "ubia": 3,
    "msaada wa kiufundi": 4,
    "ODA": 5,
    "MoU": 3,
    "uwekezaji": 2,
    "madini ya kimkakati": 3,  # 전략광물
    "ardhi adimu": 3,  # 희토류
}


def score_page_article(article):
    """페이지 article에 점수 부여."""
    text = f"{article['title']} {article.get('summary_raw', '')}"
    text_lower = text.lower()

    score = article.get("tier_weight", 5)  # Tier 1 = 5
    score += article.get("priority_boost", 0)
    score += 3  # local_language_bonus (스와힐리어)

    # 한국 키워드
    for kw in KOREA_KEYWORDS:
        if kw.lower() in text_lower:
            score += 5
            break

    # ODA 키워드 (가중치)
    for kw, w in ODA_KEYWORDS.items():
        if kw.lower() in text_lower:
            score += w

    # 신선도 보너스
    try:
        pub_date = datetime.strptime(article["published"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days_old = (datetime.now(timezone.utc) - pub_date).days
        if days_old <= 3:
            score += 2
        elif days_old <= 7:
            score += 1
    except Exception:
        pass

    return score


# -----------------------------------------------------------------
# Page processing
# -----------------------------------------------------------------
def make_page_id(url):
    """URL 기반 고유 ID (UUID 자체를 활용하면 더 깔끔)."""
    # /page/{uuid}/ 에서 uuid 추출
    m = re.search(r"/page/([0-9a-f-]{36})/?", url, re.IGNORECASE)
    if m:
        # UUID의 처음 12자만 사용 (충분히 고유)
        return m.group(1).replace("-", "")[:12]
    # fallback
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]


def process_page(page_url, session, registry, cutoff_date):
    """본문 페이지 하나를 처리. article dict 또는 None 반환."""
    page_id = make_page_id(page_url)

    # 중복 체크
    if page_id in registry:
        return None

    print(f"  [page] {page_url}")
    parsed = parse_page_content(page_url, session)
    if parsed is None:
        return None

    # 본문 너무 짧으면 거부
    if not parsed["body"] or len(parsed["body"]) < 100:
        print(f"    [SKIP] body too short ({len(parsed['body'])} chars)")
        registry[page_id] = {
            "url": page_url,
            "skipped_reason": "empty_body",
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        return None

    # 신선도 체크
    pub_date = parsed["published_date"]
    if pub_date is None:
        print(f"    [SKIP] no date found in page content")
        # 날짜가 없으면 일단 건너뛰지만 레지스트리에는 기록 (재시도 방지)
        registry[page_id] = {
            "url": page_url,
            "skipped_reason": "no_date",
            "title": parsed["title"][:100],
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        return None

    if pub_date < cutoff_date:
        print(f"    [SKIP] stale: {pub_date.strftime('%Y-%m-%d')} < cutoff")
        registry[page_id] = {
            "url": page_url,
            "skipped_reason": "stale",
            "title": parsed["title"][:100],
            "pub_date": pub_date.isoformat(),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        return None

    # 정상 처리
    print(f"    [OK] {pub_date.strftime('%Y-%m-%d')} | {len(parsed['body'])} chars | {parsed['title'][:60]}")

    article = {
        "id": page_id,
        "title": parsed["title"] or "(제목 미상)",
        "url": page_url,
        "source": "Wizara ya Madini (광물부 본문)",
        "source_language": "sw",
        "country": "Tanzania",
        "tier_weight": 5,
        "summary_raw": parsed["body"][:3000],  # 토큰 절약
        "published": pub_date.strftime("%Y-%m-%d"),
        "score": None,
        "source_type": "html_page",
        "priority_boost": 3,
    }

    # 레지스트리 기록
    registry[page_id] = {
        "url": page_url,
        "title": parsed["title"][:100],
        "pub_date": pub_date.isoformat(),
        "body_length": len(parsed["body"]),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    return article


# -----------------------------------------------------------------
# Main
# -----------------------------------------------------------------
def main():
    print("=" * 60)
    print("KCMO Weekly - Madini Ministry HTML Collector")
    print("Target: madini.go.tz (page bodies, last 30 days)")
    print("=" * 60)

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DAYS)
    print(f"Cutoff date: {cutoff_date.strftime('%Y-%m-%d')}")

    registry = load_registry()
    print(f"Registry: {len(registry)} previously processed pages")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # 1. 진입점에서 본문 URL 발견
    print(f"\n=== Phase 1: Discovering page URLs ===")
    all_urls = set()
    for entry in ENTRY_POINTS:
        print(f"\n[entry] {entry}")
        urls = discover_page_urls(entry, session)
        print(f"  found {len(urls)} page URL(s)")
        all_urls.update(urls)
        time.sleep(1)  # 사이트에 부담 주지 않기 위한 지연

    print(f"\nTotal unique page URLs: {len(all_urls)}")

    # 2. 각 본문 페이지 처리
    print(f"\n=== Phase 2: Processing page bodies ===")
    new_articles = []
    stats = {"urls_found": len(all_urls), "already_known": 0,
             "fetched": 0, "stale": 0, "no_date": 0, "qualified": 0}

    for page_url in sorted(all_urls):
        page_id = make_page_id(page_url)
        if page_id in registry:
            stats["already_known"] += 1
            continue

        stats["fetched"] += 1
        article = process_page(page_url, session, registry, cutoff_date)

        if article is None:
            reason = registry.get(page_id, {}).get("skipped_reason")
            if reason == "stale":
                stats["stale"] += 1
            elif reason == "no_date":
                stats["no_date"] += 1
            continue

        article["score"] = score_page_article(article)
        new_articles.append(article)
        stats["qualified"] += 1

        time.sleep(1)  # 사이트 부담 완화

        # 중간 저장 (긴 실행 시 안전)
        if stats["qualified"] % 5 == 0:
            save_registry(registry)

    save_registry(registry)

    # 3. 결과 저장
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_file = DATA_DIR / f"madini_pages_{today}.json"

    output_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "madini.go.tz HTML body collector",
        "stats": stats,
        "total": len(new_articles),
        "articles": new_articles,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # 4. raw_*.json에 병합 (summarize.py가 자동으로 처리하도록)
    if new_articles:
        raw_file = DATA_DIR / f"raw_{today}.json"
        if raw_file.exists():
            try:
                with open(raw_file, encoding="utf-8") as f:
                    raw_data = json.load(f)

                existing_ids = {a.get("id") for a in raw_data.get("articles", [])}
                merged = 0
                for art in new_articles:
                    if art["id"] not in existing_ids:
                        raw_data["articles"].append(art)
                        merged += 1

                raw_data["articles"].sort(key=lambda a: a.get("score", 0), reverse=True)
                raw_data["total"] = len(raw_data["articles"])
                raw_data.setdefault("stats", {})
                raw_data["stats"]["madini_pages_merged"] = merged
                raw_data["madini_collection_at"] = datetime.now(timezone.utc).isoformat()

                with open(raw_file, "w", encoding="utf-8") as f:
                    json.dump(raw_data, f, ensure_ascii=False, indent=2)

                print(f"\nMerged {merged} article(s) into {raw_file.name}")
            except Exception as e:
                print(f"\n[WARN] merge failed: {e}")
                print(f"Articles preserved in {output_file.name}")
        else:
            print(f"\n[INFO] raw_{today}.json not found. Articles in {output_file.name}")

    # 통계
    print(f"\n{'='*60}")
    print(f"URLs discovered:     {stats['urls_found']}")
    print(f"  - already known:   {stats['already_known']}")
    print(f"  - newly fetched:   {stats['fetched']}")
    print(f"    · stale:         {stats['stale']}")
    print(f"    · no date:       {stats['no_date']}")
    print(f"    · qualified:     {stats['qualified']}")
    print(f"Output:              {output_file.name}")
    print(f"Registry size:       {len(registry)}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
