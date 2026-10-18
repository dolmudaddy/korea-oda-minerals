"""
KCMO Weekly - madini_html_collector.py
Korea Critical Minerals ODA Weekly

탄자니아 광물부(madini.go.tz)의 보도자료 본문 페이지를 직접 수집합니다.
이전 pdf_collector.py 접근(PDF 직접 크롤링)이 사이트 구조와 맞지 않아
방향을 전환한 것입니다.

작동 원리 (2026-10 사이트 개편 후 JSON API 방식):
1. 공개 API(/api/v1/public/news/?category=...)에서 카테고리별 기사 목록 수집
   (2026-10 사이트가 Next.js로 개편되어 목록 HTML에는 기사 링크가 없음)
2. 30일 신선도 필터를 목록의 published_at으로 먼저 적용 (본문 요청 절약)
3. 남은 기사만 by-slug API로 본문(body HTML) 받아 텍스트 추출
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

# 2026-10 사이트 개편: 옛 /otherpage/?p=... 와 /page/{uuid}/ 는 404.
# 목록·본문 모두 공개 JSON API에서 받는다.
SITE_BASE = "https://www.madini.go.tz"
API_LIST = SITE_BASE + "/api/v1/public/news/"
API_DETAIL = SITE_BASE + "/api/v1/public/news/by-slug/{slug}/"
CATEGORIES = ["press-release", "latest-news", "latest-updates", "public-notes"]
LIST_PAGE_SIZE = 50  # 최신순 정렬이라 첫 페이지면 30일치를 충분히 덮음


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
# Discover articles via API
# -----------------------------------------------------------------
def discover_items(category, session):
    """카테고리 목록 API에서 기사 메타데이터(id·slug·title·published_at) 목록."""
    r = fetch_with_retry(f"{API_LIST}?category={category}&page_size={LIST_PAGE_SIZE}", session)
    if r is None:
        return []
    try:
        return r.json().get("results", [])
    except ValueError:
        print(f"    [FAIL] list API returned non-JSON")
        return []


def parse_published(item):
    """'2026-07-31T03:00:00+03:00' → UTC datetime. 실패 시 None."""
    try:
        return datetime.fromisoformat(item["published_at"]).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError):
        return None


def item_url(item):
    """사람이 여는 기사 주소. 사이트 프런트엔드의 /news/{slug} 경로 (전 카테고리 공통)."""
    return f"{SITE_BASE}/news/{item['slug']}"


# -----------------------------------------------------------------
# Parse individual article body
# -----------------------------------------------------------------
def fetch_body(item, session):
    """by-slug API에서 본문 HTML을 받아 텍스트로. 실패 시 None."""
    r = fetch_with_retry(API_DETAIL.format(slug=item["slug"]), session)
    if r is None:
        return None
    try:
        data = r.json().get("data") or {}
    except ValueError:
        return None
    html = data.get("body") or ""
    body_text = BeautifulSoup(html, "lxml").get_text(separator="\n", strip=True)
    body_text = re.sub(r"\n{3,}", "\n\n", body_text)
    body_text = re.sub(r" {2,}", " ", body_text)
    if not body_text:
        body_text = data.get("excerpt") or item.get("excerpt") or ""
    return body_text


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
def make_page_id(item):
    """API 기사 id(UUID)의 처음 12자 (충분히 고유)."""
    if item.get("id"):
        return item["id"].replace("-", "")[:12]
    return hashlib.md5(item_url(item).encode("utf-8")).hexdigest()[:12]


def process_page(item, session, registry, cutoff_date):
    """API 기사 하나를 처리. article dict 또는 None 반환."""
    page_id = make_page_id(item)
    page_url = item_url(item)
    title = (item.get("title") or "").strip()

    # 중복 체크
    if page_id in registry:
        return None

    # 신선도 체크 (목록의 published_at으로 먼저 — 본문 요청 절약)
    pub_date = parse_published(item)
    if pub_date is None:
        print(f"    [SKIP] no published_at: {title[:60]}")
        registry[page_id] = {
            "url": page_url,
            "skipped_reason": "no_date",
            "title": title[:100],
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        return None

    if pub_date < cutoff_date:
        # 오래된 기사는 레지스트리에 남기지 않는다 (매주 목록 상단만 보므로 비용 없음)
        return "stale"

    print(f"  [page] {page_url}")
    body = fetch_body(item, session)
    if body is None:
        return None

    # 본문 너무 짧으면 거부
    if len(body) < 100:
        print(f"    [SKIP] body too short ({len(body)} chars)")
        registry[page_id] = {
            "url": page_url,
            "skipped_reason": "empty_body",
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        return None

    # 정상 처리
    print(f"    [OK] {pub_date.strftime('%Y-%m-%d')} | {len(body)} chars | {title[:60]}")

    article = {
        "id": page_id,
        "title": title or "(제목 미상)",
        "url": page_url,
        "source": "Wizara ya Madini (광물부 본문)",
        "source_language": "sw",
        "country": "Tanzania",
        "tier_weight": 5,
        "summary_raw": body[:3000],  # 토큰 절약
        "published": pub_date.strftime("%Y-%m-%d"),
        "score": None,
        "source_type": "html_page",
        "priority_boost": 3,
    }

    # 레지스트리 기록
    registry[page_id] = {
        "url": page_url,
        "title": title[:100],
        "pub_date": pub_date.isoformat(),
        "body_length": len(body),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    return article


# -----------------------------------------------------------------
# Main
# -----------------------------------------------------------------
def main():
    print("=" * 60)
    print("KCMO Weekly - Madini Ministry HTML Collector")
    print("Target: madini.go.tz public news API (last 30 days)")
    print("=" * 60)

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DAYS)
    print(f"Cutoff date: {cutoff_date.strftime('%Y-%m-%d')}")

    registry = load_registry()
    print(f"Registry: {len(registry)} previously processed pages")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # 1. 카테고리별 목록 API에서 기사 발견
    print(f"\n=== Phase 1: Discovering articles via API ===")
    items_by_id = {}
    for category in CATEGORIES:
        print(f"\n[category] {category}")
        items = discover_items(category, session)
        print(f"  found {len(items)} item(s)")
        for it in items:
            if it.get("slug"):
                items_by_id.setdefault(it.get("id") or it["slug"], it)
        time.sleep(1)  # 사이트에 부담 주지 않기 위한 지연

    all_items = sorted(items_by_id.values(), key=lambda it: it.get("published_at") or "", reverse=True)
    print(f"\nTotal unique articles: {len(all_items)}")
    if all_items:
        print(f"Newest on site:        {all_items[0].get('published_at', '')[:10]} | {all_items[0].get('title', '')[:60]}")

    # 2. 각 기사 본문 처리
    print(f"\n=== Phase 2: Processing article bodies ===")
    new_articles = []
    stats = {"urls_found": len(all_items), "already_known": 0,
             "fetched": 0, "stale": 0, "no_date": 0, "qualified": 0}

    for item in all_items:
        page_id = make_page_id(item)
        if page_id in registry:
            stats["already_known"] += 1
            continue

        article = process_page(item, session, registry, cutoff_date)

        if article == "stale":
            stats["stale"] += 1
            continue
        stats["fetched"] += 1
        if article is None:
            if registry.get(page_id, {}).get("skipped_reason") == "no_date":
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
