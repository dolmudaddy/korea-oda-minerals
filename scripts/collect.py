"""
KCMO Weekly - collect.py
Korea Critical Minerals ODA Weekly

Collects articles from 7 target ODA countries with Korea-cooperation focus.
Supports both RSS feeds and HTML listing pages (multi-language).

Phase A: Tanzania only - establishes the pattern.

──────────────────────────────────────────────────────────────────────
변경 이력
──────────────────────────────────────────────────────────────────────
2026-05-15 (v5, A+B integrated):
  [A] 핵심광물 필수 통과 필터 추가 — score_article 초입에서 critical
      mineral keyword 매칭 0개면 즉시 폐기.
  [B] 정부 인용 보너스 추가 — 한국 +3, 7개국 협력국 +5, 카드당 +8 상한.

2026-05-15 (v6.2, keyword expansion based on real log analysis):
  박사님 실제 GitHub Actions 로그 분석 후 sources.yaml 키워드 사전 확장.
  v6 폐기 카드 39건 중 33건 복구. 노이즈 9건 중 8건 차단.
  collect.py 자체 로직은 v6와 동일 (4단계 필터 구조).
  핵심 변경 (모두 sources.yaml에서):
    - core_minerals에 일반 광업 용어(mining/mineral 등) + 7개국 주요
      광업 회사명(Oyu Tolgoi, Rio Tinto, Kazatomprom 등) 추가
    - core_minerals_wordbound에 'ore', 'miner' 추가 (부분일치 사고 차단)
    - domain_terms에 한국어 띄어쓰기 변형(핵심 광물, 자원 외교 등) 추가
    - exclusion_terms에 정치 일반 차단(victory day 등)

2026-05-15 (v6, keyword redesign):
  [A] 핵심광물 필터 4단계 재설계 — 박사님 실제 폐기/통과 케이스 분석
      후 키워드 사전 본질적 재구성:
        1. exclusion_terms: 광업 무관 영역 차단
           (gold reserves, HPV, film, railway tariff 등)
        2. exclusion_wordbound: 짧은 약어 단어 경계 매칭 (HPV 등)
        3. core_minerals: 광종 직접 언급 (희소금속, 리튬, gold mining 등)
        4. core_minerals_wordbound: REE/PGM 등 약어 단어 경계
        5. domain_terms: KCMO 도메인 어휘 (자원외교, 산업기술협력,
           광물자원, 핵심광물, critical mineral, supply chain 등)
      박사님 폐기 8건 모두 복구, 잘못 통과 5건 모두 차단.
  [B] partner_keywords 단어 경계 자동 처리 — 5자 이하 영문 대문자
      약어(DOM, VNA, MOIT 등)는 자동으로 \b 정규식 적용해서 
      "domestic", "vnaij" 같은 부정확 매칭 방지.
──────────────────────────────────────────────────────────────────────
"""
import feedparser
import requests
import yaml
import hashlib
import json
import re
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
import time

# -----------------------------------------------------------------
# Config
# -----------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR
SOURCES_FILE = ROOT_DIR / "sources.yaml"
OUTPUT_DIR = ROOT_DIR / "data"
OUTPUT_DIR.mkdir(exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (compatible; KCMO-Weekly/0.1; "
    "+https://dolmudaddy.github.io/korea-oda-minerals/)"
)
REQUEST_TIMEOUT = 20

# -----------------------------------------------------------------
# Load sources
# -----------------------------------------------------------------
def load_sources():
    with open(SOURCES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


# -----------------------------------------------------------------
# Country detection (mandatory filter)
# -----------------------------------------------------------------
TARGET_COUNTRIES = [
    "Tanzania", "Indonesia", "Vietnam", "Mongolia",
    "Kazakhstan", "Uzbekistan", "Laos",
    # Korean names
    "탄자니아", "인도네시아", "베트남", "몽골",
    "카자흐스탄", "우즈베키스탄", "라오스",
]


def detect_country(text):
    """Return the matched country name or None."""
    text_lower = text.lower()
    for country in TARGET_COUNTRIES:
        if country.lower() in text_lower:
            # Normalize to English
            mapping = {
                "탄자니아": "Tanzania", "인도네시아": "Indonesia",
                "베트남": "Vietnam", "몽골": "Mongolia",
                "카자흐스탄": "Kazakhstan", "우즈베키스탄": "Uzbekistan",
                "라오스": "Laos",
            }
            return mapping.get(country, country)
    return None


# -----------------------------------------------------------------
# [A] 핵심광물 필수 통과 필터 (2026-05-15 추가)
# -----------------------------------------------------------------
def has_critical_mineral(text, scoring_cfg):
    """카드 텍스트가 KCMO 핵심광물 카드인지 판정 (v6 재설계).

    4단계 필터로 박사님 폐기/통과 케이스 정확히 분류:
        1. exclusion_terms 매칭 → 즉시 폐기 (광업 무관)
        2. exclusion_wordbound 매칭 (HPV 등 단어 경계) → 즉시 폐기
        3. core_minerals 매칭 → 통과 (광종 직접 언급)
        4. core_minerals_wordbound 매칭 (REE 등 단어 경계) → 통과
        5. domain_terms 매칭 → 통과 (KCMO 도메인 어휘)
        6. 둘 다 없음 → 폐기 (no critical mineral keyword)

    Args:
        text: 원본 텍스트 (제목 + 요약, 소문자화 안 됨)
        scoring_cfg: scoring 설정 딕셔너리

    Returns:
        (decision, reason)
        decision: "PASS" or "PURGE"
        reason: 매칭된 키워드 또는 폐기 사유 (로깅용)
    """
    cfg = scoring_cfg.get("critical_mineral_keywords", {})
    if not cfg.get("enabled", False):
        # 비활성화 시 통과 (이전 호환)
        return "PASS", "filter disabled"

    text_lower = text.lower()

    # Step 1: exclusion_terms (부분일치) → 폐기
    for term in cfg.get("exclusion_terms", []) or []:
        if term and term.lower() in text_lower:
            return "PURGE", f"exclude: '{term}'"

    # Step 2: exclusion_wordbound (단어 경계) → 폐기
    for term in cfg.get("exclusion_wordbound", []) or []:
        if not term:
            continue
        pattern = r'\b' + re.escape(term) + r'\b'
        if re.search(pattern, text, re.IGNORECASE):
            return "PURGE", f"exclude-wb: '{term}'"

    # Step 3: core_minerals (부분일치) → 통과
    for term in cfg.get("core_minerals", []) or []:
        if term and term.lower() in text_lower:
            return "PASS", f"core: '{term}'"

    # Step 4: core_minerals_wordbound (단어 경계) → 통과
    for term in cfg.get("core_minerals_wordbound", []) or []:
        if not term:
            continue
        pattern = r'\b' + re.escape(term) + r'\b'
        if re.search(pattern, text, re.IGNORECASE):
            return "PASS", f"core-wb: '{term}'"

    # Step 5: domain_terms (부분일치) → 통과
    for term in cfg.get("domain_terms", []) or []:
        if term and term.lower() in text_lower:
            return "PASS", f"domain: '{term}'"

    # Step 6: 어디에도 매칭 안 됨 → 폐기
    return "PURGE", "no critical mineral keyword"


# -----------------------------------------------------------------
# [B] 정부 인용 보너스 (2026-05-15 추가)
# -----------------------------------------------------------------
def compute_gov_citation_bonus(article_text, scoring_cfg):
    """정부 1차 자료 인용 보너스 계산.

    Returns:
        (bonus_score, korea_matches, partner_matches)

    - 한국 정부 인용: korea_score / 매칭
    - 7개국 협력국 정부 인용: partner_score / 매칭
    - max_hits_per_category로 같은 카테고리 중복 가산 제한
    - max_total_bonus로 카드당 보너스 상한 적용
    """
    cfg = scoring_cfg.get("government_citation_bonus", {})
    if not cfg.get("enabled", False):
        return 0, [], []

    # 단어 경계 매칭은 원본 텍스트, 부분일치는 lower 사용
    text_lower = article_text.lower()

    korea_score = int(cfg.get("korea_score", 3))
    partner_score = int(cfg.get("partner_score", 5))
    max_hits = int(cfg.get("max_hits_per_category", 1))
    max_total = int(cfg.get("max_total_bonus", 8))

    bonus = 0
    kr_matched = []
    pt_matched = []

    # 짧은 영문 약어는 단어 경계로 매칭 (DOM이 "domestic"에 잘못
    # 매칭되는 문제 해결). 5자 이하 영문 대문자 약어를 자동 감지.
    def _matches(kw, text_l, text_orig):
        """키워드가 텍스트에 매칭되는지 검사.
        짧은 영문 약어(5자 이하 대문자)는 단어 경계 적용, 그 외는 부분일치.
        """
        if not kw:
            return False
        # ASCII + 대문자 약어 + 5자 이하 → 단어 경계 필수
        is_short_abbr = (
            len(kw) <= 5
            and kw.isascii()
            and kw.isupper()
            and kw.isalpha()
        )
        if is_short_abbr:
            pattern = r'\b' + re.escape(kw) + r'\b'
            return bool(re.search(pattern, text_orig))
        else:
            return kw.lower() in text_l

    # 한국 정부 인용
    hits = 0
    for kw in cfg.get("korea_keywords", []) or []:
        if _matches(kw, text_lower, article_text):
            hits += 1
            kr_matched.append(kw)
            if hits >= max_hits:
                break
    if hits > 0:
        bonus += korea_score * hits

    # 협력국 정부 인용
    hits = 0
    for kw in cfg.get("partner_keywords", []) or []:
        if _matches(kw, text_lower, article_text):
            hits += 1
            pt_matched.append(kw)
            if hits >= max_hits:
                break
    if hits > 0:
        bonus += partner_score * hits

    # 카드당 보너스 상한
    bonus = min(bonus, max_total)
    return bonus, kr_matched, pt_matched


# -----------------------------------------------------------------
# Scoring
# -----------------------------------------------------------------
def score_article(article, source_meta, scoring_cfg):
    """Compute relevance score. Returns score (int) or None if dropped."""
    text = f"{article['title']} {article.get('summary_raw', '')}"
    text_lower = text.lower()

    # 1. Country match - mandatory
    country = detect_country(text)
    if not country:
        return None, None
    article["country"] = country

    # ─────────────────────────────────────────────────────────────
    # [A] 핵심광물 키워드 필터 (v6 재설계, 2026-05-15)
    # ─────────────────────────────────────────────────────────────
    # 4단계 필터:
    #   1. exclusion (gold reserves, HPV, film 등) → 폐기
    #   2. core_minerals (광종 직접 언급) → 통과
    #   3. domain_terms (자원외교·산업기술협력 등 KCMO 어휘) → 통과
    #   4. 어디에도 매칭 안 됨 → 폐기
    #
    # 박사님 폐기 케이스 (gold reserves, HPV, film, railway tariff)와
    # 통과 케이스 (희소금속협력센터, KIAT 산업기술협력, 광물자원 협력)
    # 모두 검증 완료.
    cm_decision, cm_reason = has_critical_mineral(text, scoring_cfg)
    if cm_decision == "PURGE":
        # 폐기 사유 로그 — 박사님이 결과 검토 시 어떤 키워드로
        # 걸렸는지 추적 가능
        print(f"    [PURGED-{cm_reason}] {article['title'][:55]}")
        return None, None
    # ─────────────────────────────────────────────────────────────

    score = 0

    # 2. Tier weight (base score from source)
    score += source_meta.get("tier_weight", 1)

    # 3. Source priority boost
    score += source_meta.get("priority_boost", 0)

    # 4. Local language bonus (Swahili/Indonesian/etc original source)
    if source_meta.get("language") in ["sw", "id", "vi", "mn", "kk", "uz", "lo"]:
        score += scoring_cfg.get("local_language_bonus", 3)

    # 5. Korea keywords
    korea_terms = scoring_cfg.get("korea_keywords", {}).get("terms", {})
    korea_weight = scoring_cfg.get("korea_keywords", {}).get("weight", 5)
    for lang, terms in korea_terms.items():
        for term in terms:
            if term.lower() in text_lower:
                score += korea_weight
                break  # one match per language is enough

    # 6. ODA keywords
    oda_keywords = scoring_cfg.get("oda_keywords", {})
    for lang, kw_dict in oda_keywords.items():
        for kw, weight in kw_dict.items():
            if kw.lower() in text_lower:
                score += weight

    # 7. Recency bonus
    pub_date = article.get("published_dt")
    if pub_date:
        delta_days = (datetime.now(timezone.utc) - pub_date).days
        recency = scoring_cfg.get("recency_bonus", {})
        if delta_days <= 3:
            score += recency.get("within_3_days", 0)
        elif delta_days <= 7:
            score += recency.get("within_7_days", 0)

        # Drop if too old
        freshness = scoring_cfg.get("freshness_days", 30)
        if delta_days > freshness:
            return None, None

    # ─────────────────────────────────────────────────────────────
    # [B] 정부 인용 보너스 (2026-05-15 추가)
    # ─────────────────────────────────────────────────────────────
    # 기존 점수 계산이 모두 끝난 시점에 가산. 광물 1차 필터 통과한
    # 카드 중 정부 1차 자료 인용 흔적이 있으면 상위로 끌어올림.
    gov_bonus, kr_match, pt_match = compute_gov_citation_bonus(
        text, scoring_cfg
    )
    if gov_bonus > 0:
        score += gov_bonus
        tag = []
        if kr_match:
            tag.append(f"KR:{kr_match}")
        if pt_match:
            tag.append(f"PT:{pt_match}")
        print(f"    [gov-bonus] +{gov_bonus}  {' '.join(tag)}")
    # ─────────────────────────────────────────────────────────────

    return score, country


# -----------------------------------------------------------------
# HTML scraping (for sites without RSS)
# -----------------------------------------------------------------
def scrape_html_listing(url, language="en", limit=20):
    """Fetch an HTML page and extract article-like items.

    Generic heuristic: find anchors with non-trivial text inside
    typical news-listing containers. Filters out obvious nav links.
    """
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT,
                         headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
    except Exception as e:
        print(f"  [WARN] fetch failed: {url} ({e})")
        return []

    soup = BeautifulSoup(r.content, "lxml")
    items = []

    # Strategy: collect all links with meaningful anchor text,
    # de-duplicate, and keep ones that look like article links
    # (path contains digits, slugs, or known article-marker patterns).
    seen_urls = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        text = a.get_text(strip=True)

        # Skip empty or nav-like links
        if not text or len(text) < 15:
            continue
        if text.lower() in ["read more", "more", "next", "previous",
                            "home", "about", "contact"]:
            continue

        # Resolve to absolute URL
        full_url = urljoin(url, href)
        if full_url in seen_urls:
            continue
        seen_urls.add(full_url)

        # Filter: must be same domain or PDF
        parsed = urlparse(full_url)
        source_domain = urlparse(url).netloc
        if parsed.netloc and parsed.netloc != source_domain:
            continue

        items.append({
            "title": text,
            "url": full_url,
            "summary_raw": text,  # HTML scrape rarely gives summary
            "published": None,
            "published_dt": None,
        })

        if len(items) >= limit:
            break

    return items


# -----------------------------------------------------------------
# RSS feed parser
# -----------------------------------------------------------------
def fetch_rss(url):
    try:
        feed = feedparser.parse(url, agent=USER_AGENT)
        items = []
        for entry in feed.entries[:30]:
            pub_dt = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            items.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                "summary_raw": entry.get("summary", "")[:1000],
                "published": entry.get("published", ""),
                "published_dt": pub_dt,
            })
        return items
    except Exception as e:
        print(f"  [WARN] RSS parse failed: {url} ({e})")
        return []


# -----------------------------------------------------------------
# Main collection loop
# -----------------------------------------------------------------
def make_article_id(url):
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:8]


def collect_from_source(source, tier_weight, scoring_cfg, results, stats):
    """Process one source and append qualifying articles to results."""
    url = source["url"]
    rss = source.get("rss")
    method = source.get("scrape_method", "rss" if rss else "html_listing")
    language = source.get("language", "en")
    source_name = source["name"]

    print(f"\n[{source_name}] {url}")
    stats["sources_tried"] += 1

    # Fetch
    if method == "rss" and rss:
        items = fetch_rss(rss)
    elif method == "html_listing":
        items = scrape_html_listing(url, language=language)
    elif method == "pdf_directory":
        # Phase A scope: skip PDF dir crawl for now (handled separately)
        print("  [SKIP] pdf_directory handler not yet implemented")
        return
    else:
        print(f"  [SKIP] unknown method: {method}")
        return

    print(f"  fetched {len(items)} items")
    stats["items_fetched"] += len(items)

    # Build source meta for scoring
    source_meta = {
        "tier_weight": tier_weight,
        "priority_boost": source.get("priority_boost", 0),
        "language": language,
    }

    qualified = 0
    for item in items:
        score, country = score_article(item, source_meta, scoring_cfg)
        if score is None:
            continue
        if score < scoring_cfg.get("min_score_threshold", 7):
            continue

        # Compose article record
        article = {
            "id": make_article_id(item["url"]),
            "title": item["title"],
            "url": item["url"],
            "source": source_name,
            "source_language": language,
            "country": country,
            "tier_weight": tier_weight,
            "summary_raw": item.get("summary_raw", ""),
            "published": item.get("published", ""),
            "score": score,
        }
        results.append(article)
        qualified += 1

    print(f"  qualified: {qualified} (threshold={scoring_cfg.get('min_score_threshold')})")
    stats["items_qualified"] += qualified


# -----------------------------------------------------------------
# Google News broad search (Tier 4)
# -----------------------------------------------------------------
# 쿼리 키 → (언어, 국가) 매핑
# Google News RSS는 hl(언어)·gl(국가)·ceid(국가:언어) 파라미터로 지역화함
GOOGLE_NEWS_LOCALES = {
    "tanzania_english_queries": ("en", "TZ", "TZ:en"),
    "tanzania_swahili_queries": ("sw", "TZ", "TZ:sw"),
    "indonesia_english_queries": ("en", "ID", "ID:en"),
    "indonesia_local_queries":   ("id", "ID", "ID:id"),
    "vietnam_english_queries":   ("en", "VN", "VN:en"),
    "vietnam_local_queries":     ("vi", "VN", "VN:vi"),
    "mongolia_english_queries":  ("en", "MN", "MN:en"),
    "mongolia_local_queries":    ("mn", "MN", "MN:mn"),
    "kazakhstan_english_queries": ("en", "KZ", "KZ:en"),
    "kazakhstan_russian_queries": ("ru", "KZ", "KZ:ru"),
    "uzbekistan_english_queries": ("en", "UZ", "UZ:en"),
    "uzbekistan_russian_queries": ("ru", "UZ", "UZ:ru"),
    "laos_english_queries":      ("en", "LA", "LA:en"),
    "korea_cross_queries":       ("ko", "KR", "KR:ko"),
}


def fetch_google_news_feed(query, locale_tuple):
    """Google News RSS를 한 쿼리에 대해 호출. feedparser로 결과 파싱.

    feedparser에 명시적 User-Agent 전달하여 차단 회피.
    """
    from urllib.parse import quote_plus
    hl, gl, ceid = locale_tuple
    url = (
        f"https://news.google.com/rss/search?"
        f"q={quote_plus(query)}&hl={hl}&gl={gl}&ceid={ceid}"
    )
    try:
        # feedparser는 agent 인자 지원
        feed = feedparser.parse(url, agent=USER_AGENT)
        # bozo는 파싱 오류 플래그. 0이면 정상
        if feed.bozo and not feed.entries:
            # 파싱 오류 + 빈 결과면 진짜 실패
            return []
        return feed.entries
    except Exception as e:
        print(f"    [WARN] Google News fetch failed for '{query}': {e}")
        return []


def resolve_google_news_url(google_url, session=None):
    """Google News RSS URL을 진짜 매체 URL로 변환.

    Google News의 /rss/articles/CBMi... 형식 URL은 클릭 가능하지 않으므로
    HEAD 요청을 보내 redirect Location 헤더에서 실제 매체 URL을 추출함.

    실패 시 원래 URL 반환 (안전한 fallback).
    성능 최적화: 짧은 타임아웃 (5초), HEAD만 시도 (GET retry 없음).
    """
    if "news.google.com" not in google_url:
        return google_url  # 이미 매체 직접 URL

    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": USER_AGENT})

    try:
        # HEAD 요청만, 짧은 타임아웃 5초
        r = session.head(google_url, allow_redirects=False, timeout=5)

        # Google News는 302 또는 301로 redirect함
        if r.status_code in (301, 302, 303, 307, 308):
            real_url = r.headers.get("Location", "")
            if real_url and "google.com" not in real_url:
                return real_url
    except Exception:
        pass  # 어떤 오류든 원래 URL fallback

    return google_url


def collect_from_google_news(tier4_cfg, scoring_cfg, results, stats):
    """tier_4_broad_search 섹션의 모든 쿼리를 Google News RSS로 실행."""
    min_score = scoring_cfg.get("min_score_threshold", 7)

    # URL 변환용 세션 (재사용으로 성능 향상)
    url_session = requests.Session()
    url_session.headers.update({"User-Agent": USER_AGENT})

    # 모든 쿼리 키를 탐색
    for query_key, locale in GOOGLE_NEWS_LOCALES.items():
        queries = tier4_cfg.get(query_key, [])
        if not queries:
            continue

        print(f"\n  [{query_key}] {len(queries)} query(ies), locale={locale[2]}")

        for query in queries:
            stats["google_news_queries"] += 1
            entries = fetch_google_news_feed(query, locale)
            stats["google_news_items"] += len(entries)
            print(f"    '{query}' → {len(entries)} entries")

            qualified = 0
            for entry in entries:
                # Google News 항목을 article 구조로 변환
                title = entry.get("title", "")
                google_link = entry.get("link", "")
                summary = entry.get("summary", "")
                pub_str = entry.get("published", "") or entry.get("updated", "")

                # 발행일 파싱
                pub_dt = None
                try:
                    if pub_str:
                        from email.utils import parsedate_to_datetime
                        pub_dt = parsedate_to_datetime(pub_str)
                        if pub_dt.tzinfo is None:
                            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

                # 가상 source_meta 생성 (Tier 4 - weight 1)
                source_meta = {
                    "name": f"Google News ({query_key})",
                    "tier_weight": tier4_cfg.get("weight", 1),
                    "priority_boost": 0,
                    "language": locale[0],
                }

                # article 후보 빌드 - 일단 Google News URL로 점수화
                # URL 변환은 점수 통과 후에만 수행 (성능 최적화)
                article = {
                    "id": hashlib.md5(google_link.encode("utf-8")).hexdigest()[:12],
                    "title": title,
                    "url": google_link,  # 임시 - 점수 통과 후 매체 URL로 변환
                    "source": f"Google News ({locale[2]})",
                    "source_language": locale[0],
                    "summary_raw": summary[:1500] if summary else "",
                    "published_dt": pub_dt,
                    "published": pub_dt.strftime("%Y-%m-%d") if pub_dt else "",
                    "tier_weight": tier4_cfg.get("weight", 1),
                    "priority_boost": 0,
                    "source_type": "google_news",
                    "search_query": query,
                }

                # 점수화 (Country detection 포함, freshness 30일 필터 자동)
                score, country = score_article(article, source_meta, scoring_cfg)
                if score is None or score < min_score:
                    continue

                # 점수 통과 → 이제 URL 변환 (HEAD 요청 비용 발생)
                # 변환 실패 시 google_link fallback
                real_link = resolve_google_news_url(google_link, url_session)
                article["url"] = real_link
                # id도 진짜 URL 기반으로 재생성 (전체 dedup 정확도)
                article["id"] = hashlib.md5(real_link.encode("utf-8")).hexdigest()[:12]

                article["score"] = score
                article["country"] = country
                # published_dt는 직렬화 안 되므로 제거
                article.pop("published_dt", None)
                results.append(article)
                qualified += 1

            if qualified > 0:
                stats["items_qualified"] += qualified
                print(f"      qualified: {qualified}")

            # Rate limiting: Google News에 부담 주지 않기 위한 지연
            time.sleep(0.5)


def main():
    cfg = load_sources()
    scoring = cfg.get("scoring", {})

    results = []
    stats = {"sources_tried": 0, "items_fetched": 0, "items_qualified": 0,
             "google_news_queries": 0, "google_news_items": 0}

    # Iterate all tier sections - each tier has { weight, sources[] }
    tier_keys = [k for k in cfg.keys() if k.startswith("tier_")]
    for tier_key in tier_keys:
        tier_block = cfg[tier_key]
        if not isinstance(tier_block, dict):
            continue
        tier_weight = tier_block.get("weight", 1)
        sources_list = tier_block.get("sources", [])

        print(f"\n{'#'*60}")
        print(f"# {tier_key} (weight={tier_weight}, sources={len(sources_list)})")
        print(f"{'#'*60}")

        for source in sources_list:
            collect_from_source(source, tier_weight, scoring, results, stats)

    # ----------------------------------------------------
    # Phase B: Tier 4 Google News broad search
    # ----------------------------------------------------
    tier4 = cfg.get("tier_4_broad_search", {})
    if tier4:
        print(f"\n{'#'*60}")
        print(f"# Tier 4: Google News (broad search across 4 countries)")
        print(f"{'#'*60}")
        collect_from_google_news(tier4, scoring, results, stats)

    # Deduplicate by URL (same article might appear in multiple queries)
    seen_urls = set()
    deduped = []
    for art in results:
        url = art.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(art)
    print(f"\nDeduplication: {len(results)} → {len(deduped)} articles")
    results = deduped

    # Sort by score desc
    results.sort(key=lambda r: r["score"], reverse=True)

    # Save
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_file = OUTPUT_DIR / f"raw_{today}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "stats": stats,
            "total": len(results),
            "articles": results,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"Sources tried:        {stats['sources_tried']}")
    print(f"Items fetched (tier1-3): {stats['items_fetched']}")
    print(f"Google News queries:  {stats['google_news_queries']}")
    print(f"Google News items:    {stats['google_news_items']}")
    print(f"Items qualified:      {stats['items_qualified']}")
    print(f"After dedup:          {len(results)}")
    print(f"Output:               {output_file}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
