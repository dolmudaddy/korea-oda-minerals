"""
KCMO Weekly - collect.py
Korea Critical Minerals ODA Weekly

Collects articles from 7 target ODA countries with Korea-cooperation focus.
Supports both RSS feeds and HTML listing pages (multi-language).

Phase A: Tanzania only - establishes the pattern.
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


def main():
    cfg = load_sources()
    scoring = cfg.get("scoring", {})

    results = []
    stats = {"sources_tried": 0, "items_fetched": 0, "items_qualified": 0}

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
    print(f"Sources tried:    {stats['sources_tried']}")
    print(f"Items fetched:    {stats['items_fetched']}")
    print(f"Items qualified:  {stats['items_qualified']}")
    print(f"Output:           {output_file}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
