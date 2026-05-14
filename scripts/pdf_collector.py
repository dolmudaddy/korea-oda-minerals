"""
KCMO Weekly - pdf_collector.py
Korea Critical Minerals ODA Weekly

탄자니아 광물부(madini.go.tz)의 3개 보도자료 메뉴에서 최근 30일 이내
게시된 PDF 파일을 자동으로 수집·다운로드·텍스트 추출하여, 기존
raw_*.json 파이프라인에 합류시킵니다.

수집 대상:
  - /otherpage/?p=press-release  (공식 보도자료)
  - /listspeech/                  (장관 연설)
  - /otherpage/?p=public-notes    (공지사항)

신선도: 최근 30일 이내 게시된 PDF만 처리
중복 방지: data/processed_pdfs.json에 기록된 파일은 건너뜀

출력:
  data/pdf_articles_YYYY-MM-DD.json - 기존 raw_*.json과 동일 구조로
                                       summarize.py가 그대로 처리 가능
"""
import os
import sys
import json
import re
import hashlib
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
except ImportError:
    print("ERROR: install pdfplumber: pip install pdfplumber")
    sys.exit(1)


# -----------------------------------------------------------------
# Config
# -----------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR
DATA_DIR = ROOT_DIR / "data"
PDF_CACHE_DIR = DATA_DIR / "pdf_cache"
PROCESSED_REGISTRY = DATA_DIR / "processed_pdfs.json"
DATA_DIR.mkdir(exist_ok=True)
PDF_CACHE_DIR.mkdir(exist_ok=True)

USER_AGENT = (
    "Mozilla/5.0 (compatible; KCMO-Weekly/1.0; "
    "+https://dolmudaddy.github.io/korea-oda-minerals/)"
)
REQUEST_TIMEOUT = 30
FRESHNESS_DAYS = 30

# Tiered size-based processing
# - Small (<5MB): 보도자료, 짧은 공지 → 전체 처리
# - Medium (5-50MB): 분기 보고서, Local Content 가이드 → 처음 10페이지
# - Large (50-100MB): 연간 보고서, 지질도·시추 데이터 → 처음 15페이지 + 목차
# - Oversized (>100MB): 거부 (디스크·메모리 보호)
PDF_SIZE_SMALL_MB = 5
PDF_SIZE_MEDIUM_MB = 50
PDF_SIZE_LARGE_MB = 100  # 절대 한도

PAGES_FOR_SMALL = 5    # 작은 보도자료는 보통 1-3페이지라 5페이지면 충분
PAGES_FOR_MEDIUM = 10  # 중간 보고서는 처음 10페이지에 핵심 요약
PAGES_FOR_LARGE = 15   # 큰 보고서는 처음 15페이지 (Executive Summary + 목차 + 핵심 결론)

# 수집 대상 페이지
TARGET_PAGES = [
    {
        "name": "Wizara ya Madini - Press Release",
        "name_en": "Ministry of Minerals - Press Release",
        "url": "https://www.madini.go.tz/otherpage/?p=press-release",
        "menu_type": "press_release",
        "priority_boost": 3,
    },
    {
        "name": "Wizara ya Madini - Speeches",
        "name_en": "Ministry of Minerals - Speeches",
        "url": "https://www.madini.go.tz/listspeech/",
        "menu_type": "speeches",
        "priority_boost": 2,
    },
    {
        "name": "Wizara ya Madini - Public Notes",
        "name_en": "Ministry of Minerals - Public Notes",
        "url": "https://www.madini.go.tz/otherpage/?p=public-notes",
        "menu_type": "public_notes",
        "priority_boost": 1,
    },
]


# -----------------------------------------------------------------
# Registry management (avoid re-processing)
# -----------------------------------------------------------------
def load_registry():
    """이미 처리한 PDF 목록 로드."""
    if not PROCESSED_REGISTRY.exists():
        return {}
    try:
        with open(PROCESSED_REGISTRY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_registry(registry):
    """처리 기록 저장."""
    with open(PROCESSED_REGISTRY, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


# -----------------------------------------------------------------
# PDF date extraction (from filename or HTTP headers)
# -----------------------------------------------------------------
DATE_PATTERNS = [
    # _DDMMYYYY  (e.g., _04012026)
    (re.compile(r"_(\d{2})(\d{2})(\d{4})(?:\.pdf|_)"), "ddmmyyyy"),
    # _YYYYMMDD  (e.g., _20260104)
    (re.compile(r"_(\d{4})(\d{2})(\d{2})(?:\.pdf|_)"), "yyyymmdd"),
    # _DD-MM-YYYY or _DD_MM_YYYY
    (re.compile(r"_(\d{2})[-_](\d{2})[-_](\d{4})(?:\.pdf|_)"), "ddmmyyyy"),
    # YYYY-MM-DD anywhere
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "yyyymmdd"),
]


def parse_date_from_filename(filename):
    """파일명에서 날짜 추출. 실패 시 None 반환."""
    for pattern, order in DATE_PATTERNS:
        m = pattern.search(filename)
        if not m:
            continue
        try:
            if order == "ddmmyyyy":
                day, month, year = m.group(1), m.group(2), m.group(3)
            else:  # yyyymmdd
                year, month, day = m.group(1), m.group(2), m.group(3)
            return datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
        except (ValueError, IndexError):
            continue
    return None


def get_pdf_date(url, session, head_only=True):
    """PDF의 게시 날짜 추출. 우선순위: 파일명 → Last-Modified 헤더."""
    filename = unquote(urlparse(url).path.split("/")[-1])
    dt = parse_date_from_filename(filename)
    if dt:
        return dt, "filename"

    # Fallback: HEAD 요청으로 Last-Modified 헤더 확인
    if head_only:
        try:
            r = session.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            last_mod = r.headers.get("Last-Modified")
            if last_mod:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(last_mod), "http_header"
        except Exception:
            pass
    return None, None


# -----------------------------------------------------------------
# PDF link discovery
# -----------------------------------------------------------------
def find_pdf_links(page_url, session):
    """HTML 페이지에서 PDF 링크들을 추출."""
    try:
        r = session.get(page_url, timeout=REQUEST_TIMEOUT,
                        headers={"User-Agent": USER_AGENT})
        r.raise_for_status()
    except Exception as e:
        print(f"  [WARN] fetch failed: {page_url} ({e})")
        return []

    soup = BeautifulSoup(r.content, "lxml")
    pdf_links = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        full_url = urljoin(page_url, href)

        # PDF 확장자 또는 PDF 다운로드 패턴 매칭
        if not (full_url.lower().endswith(".pdf") or
                "/listdoc/" in full_url and "doc=" in full_url):
            continue

        if full_url in seen:
            continue
        seen.add(full_url)

        # 링크 텍스트(또는 부모 텍스트)를 제목으로
        link_text = a.get_text(strip=True)
        if not link_text or len(link_text) < 3:
            # 부모 노드에서 제목 찾기
            parent = a.parent
            if parent:
                link_text = parent.get_text(strip=True)[:200]

        pdf_links.append({
            "url": full_url,
            "title": link_text,
            "filename": unquote(urlparse(full_url).path.split("/")[-1]),
        })

    return pdf_links


# -----------------------------------------------------------------
# PDF download and text extraction
# -----------------------------------------------------------------
def make_pdf_id(url):
    """URL 기반 고유 ID 생성."""
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]


def get_size_tier(size_bytes):
    """파일 크기에 따른 처리 등급 결정.

    Returns:
        (tier_name, max_pages, label_suffix)
        - tier_name: 'small' | 'medium' | 'large' | 'oversized'
        - max_pages: 추출할 최대 페이지 수
        - label_suffix: 카드에 표시할 설명 (큰 PDF만)
    """
    size_mb = size_bytes / 1024 / 1024
    if size_mb < PDF_SIZE_SMALL_MB:
        return "small", PAGES_FOR_SMALL, ""
    elif size_mb < PDF_SIZE_MEDIUM_MB:
        return "medium", PAGES_FOR_MEDIUM, f" (중간 보고서, {PAGES_FOR_MEDIUM}페이지 분석)"
    elif size_mb < PDF_SIZE_LARGE_MB:
        return "large", PAGES_FOR_LARGE, f" (대형 보고서, {PAGES_FOR_LARGE}페이지 분석)"
    else:
        return "oversized", 0, ""


def download_pdf(url, session, dest_path):
    """PDF를 디스크에 저장. 성공 시 (True, size_bytes) 튜플 반환, 실패 시 (False, 0).

    크기 등급:
      - small (<5MB): 정상 처리
      - medium (5-50MB): 정상 처리, 텍스트 추출 시 페이지 제한
      - large (50-100MB): 정상 처리, 텍스트 추출 시 더 강한 페이지 제한
      - oversized (>100MB): 거부
    """
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT, stream=True,
                        headers={"User-Agent": USER_AGENT})
        r.raise_for_status()

        # Content-Length 헤더로 사전 크기 검사
        content_length = r.headers.get("Content-Length")
        if content_length:
            size_bytes = int(content_length)
            tier, _, _ = get_size_tier(size_bytes)
            if tier == "oversized":
                size_mb = size_bytes / 1024 / 1024
                print(f"    [SKIP] file too large: {size_mb:.1f}MB > {PDF_SIZE_LARGE_MB}MB limit")
                return False, 0

        # 다운로드 진행
        with open(dest_path, "wb") as f:
            written = 0
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    written += len(chunk)
                    # 다운로드 중 크기 초과 시 abort (Content-Length가 없는 경우)
                    if written > PDF_SIZE_LARGE_MB * 1024 * 1024:
                        print(f"    [ABORT] exceeded {PDF_SIZE_LARGE_MB}MB during download")
                        f.close()
                        dest_path.unlink(missing_ok=True)
                        return False, 0

        actual_size = dest_path.stat().st_size
        return True, actual_size
    except Exception as e:
        print(f"    [WARN] download failed: {e}")
        if dest_path.exists():
            dest_path.unlink(missing_ok=True)
        return False, 0


def extract_pdf_text(pdf_path, max_pages):
    """pdfplumber로 PDF 본문 추출.

    Args:
        pdf_path: PDF 파일 경로
        max_pages: 추출할 최대 페이지 수 (크기 등급에 따라 결정)

    Returns:
        (text, total_pages) 튜플
        - text: 추출된 본문 텍스트
        - total_pages: PDF의 전체 페이지 수 (카드에 "X페이지 중 Y페이지 분석" 표시용)
    """
    try:
        text_parts = []
        total_pages = 0
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            num_to_extract = min(total_pages, max_pages)
            for page in pdf.pages[:num_to_extract]:
                text = page.extract_text() or ""
                text_parts.append(text)
        full_text = "\n\n".join(text_parts).strip()
        # 공백 정규화
        full_text = re.sub(r"\n{3,}", "\n\n", full_text)
        full_text = re.sub(r" {2,}", " ", full_text)
        return full_text, total_pages
    except Exception as e:
        print(f"    [WARN] PDF parse failed: {e}")
        return "", 0


# -----------------------------------------------------------------
# Process one PDF: download → extract → build article record
# -----------------------------------------------------------------
def process_pdf(pdf_info, source_meta, session, registry, cutoff_date):
    """PDF 한 건을 처리. 새로 처리된 article dict 또는 None 반환."""
    url = pdf_info["url"]
    pdf_id = make_pdf_id(url)

    # 1. 이미 처리한 PDF인지 확인
    if pdf_id in registry:
        return None  # silently skip

    # 2. PDF 날짜 추출 및 신선도 검사
    pdf_date, date_source = get_pdf_date(url, session)
    if pdf_date is None:
        print(f"    [SKIP] no date found: {pdf_info['filename']}")
        return None

    if pdf_date < cutoff_date:
        # 너무 오래된 PDF — 레지스트리에는 기록해서 다음 실행 때 또 확인하지 않게 함
        registry[pdf_id] = {
            "url": url,
            "filename": pdf_info["filename"],
            "skipped_reason": "stale",
            "pdf_date": pdf_date.isoformat(),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        return None

    print(f"  [NEW] {pdf_info['filename']}")
    print(f"        date: {pdf_date.strftime('%Y-%m-%d')} (from {date_source})")

    # 3. 다운로드
    dest_path = PDF_CACHE_DIR / f"{pdf_id}.pdf"
    download_ok, size_bytes = download_pdf(url, session, dest_path)
    if not download_ok:
        return None

    # 4. 크기 등급 결정 → 처리 페이지 수 결정
    size_mb = size_bytes / 1024 / 1024
    tier, max_pages, tier_label = get_size_tier(size_bytes)
    print(f"        size: {size_mb:.2f}MB (tier: {tier}, will extract {max_pages} pages)")

    # 5. 텍스트 추출
    text, total_pages = extract_pdf_text(dest_path, max_pages)
    if not text or len(text) < 50:
        print(f"    [SKIP] empty or too short text ({len(text)} chars)")
        # 레지스트리에 기록해서 다음에 안 시도하게 함
        registry[pdf_id] = {
            "url": url,
            "filename": pdf_info["filename"],
            "skipped_reason": "empty_text",
            "size_mb": round(size_mb, 2),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        return None

    print(f"        extracted {len(text)} chars from {min(total_pages, max_pages)}/{total_pages} pages")

    # 6. 큰 PDF의 경우 카드 제목에 분석 범위 표시
    title_raw = pdf_info.get("title", "") or pdf_info["filename"].replace(".pdf", "").replace("_", " ")
    title = title_raw[:300]
    if tier in ("medium", "large") and total_pages > max_pages:
        title = f"{title} [{total_pages}p 중 {max_pages}p 분석]"

    # 7. raw_*.json과 동일한 article 구조로 빌드
    article = {
        "id": pdf_id,
        "title": title,
        "url": url,
        "source": source_meta["name"],
        "source_language": "sw",  # 광물부 PDF는 스와힐리어
        "country": "Tanzania",
        "tier_weight": 5,  # Tier 1
        "summary_raw": text[:3000],  # 토큰 절약을 위해 처음 3000자
        "published": pdf_date.strftime("%Y-%m-%d"),
        "score": None,  # 아래에서 점수화
        "source_type": "pdf",
        "priority_boost": source_meta.get("priority_boost", 0),
        # PDF 메타데이터 (카드 표시용)
        "pdf_metadata": {
            "size_mb": round(size_mb, 2),
            "size_tier": tier,
            "total_pages": total_pages,
            "extracted_pages": min(total_pages, max_pages),
            "is_partial": total_pages > max_pages,
        },
    }

    # 8. 레지스트리에 처리 완료 기록
    registry[pdf_id] = {
        "url": url,
        "filename": pdf_info["filename"],
        "skipped_reason": None,
        "pdf_date": pdf_date.isoformat(),
        "size_mb": round(size_mb, 2),
        "size_tier": tier,
        "total_pages": total_pages,
        "extracted_pages": min(total_pages, max_pages),
        "text_length": len(text),
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    # 9. 캐시 파일은 디스크 절약을 위해 삭제 (텍스트는 이미 추출됨)
    dest_path.unlink(missing_ok=True)

    return article


# -----------------------------------------------------------------
# Score PDF article (Korea / ODA keyword check)
# -----------------------------------------------------------------
KOREA_KEYWORDS_SW = ["Korea", "Kikorea", "Jamhuri ya Korea", "KIGAM", "KOICA", "EDCF"]
ODA_KEYWORDS_SW = [
    "ushirikiano wa maendeleo", "makubaliano", "mkataba",
    "ubia", "msaada wa kiufundi", "ODA", "MoU"
]


def score_pdf_article(article):
    """PDF에 점수 부여 (collect.py와 동일한 로직 단순화 버전).

    Tier 1(5점) + priority_boost + Korea/ODA 키워드 가산.
    """
    text = f"{article['title']} {article.get('summary_raw', '')}"

    score = article.get("tier_weight", 5)  # 5
    score += article.get("priority_boost", 0)
    score += 3  # local_language_bonus (스와힐리어)

    # 한국 키워드
    for kw in KOREA_KEYWORDS_SW:
        if kw.lower() in text.lower():
            score += 5
            break

    # ODA 키워드 (가중치 부여)
    oda_weights = {"ushirikiano wa maendeleo": 4, "makubaliano": 3,
                   "mkataba": 3, "ubia": 3, "msaada wa kiufundi": 4,
                   "ODA": 5, "MoU": 3}
    for kw, w in oda_weights.items():
        if kw.lower() in text.lower():
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
# Main
# -----------------------------------------------------------------
def main():
    print("=" * 60)
    print("KCMO Weekly - PDF Collector")
    print("Target: madini.go.tz (3 menus, last 30 days)")
    print("=" * 60)

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=FRESHNESS_DAYS)
    print(f"Cutoff date: {cutoff_date.strftime('%Y-%m-%d')} (≥ this is fresh)")

    registry = load_registry()
    print(f"Registry: {len(registry)} previously processed PDFs")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    new_articles = []
    stats = {"pages_scanned": 0, "pdfs_found": 0, "pdfs_processed": 0,
             "pdfs_skipped_stale": 0, "pdfs_skipped_known": 0,
             "size_tiers": {"small": 0, "medium": 0, "large": 0}}

    for source_meta in TARGET_PAGES:
        print(f"\n[{source_meta['name']}]")
        print(f"  URL: {source_meta['url']}")
        stats["pages_scanned"] += 1

        pdf_links = find_pdf_links(source_meta["url"], session)
        print(f"  Found {len(pdf_links)} PDF link(s)")
        stats["pdfs_found"] += len(pdf_links)

        for pdf_info in pdf_links:
            pdf_id = make_pdf_id(pdf_info["url"])
            if pdf_id in registry:
                stats["pdfs_skipped_known"] += 1
                continue

            article = process_pdf(pdf_info, source_meta, session, registry, cutoff_date)
            if article is None:
                # check if it was marked stale
                if registry.get(pdf_id, {}).get("skipped_reason") == "stale":
                    stats["pdfs_skipped_stale"] += 1
                continue

            # 점수 부여
            article["score"] = score_pdf_article(article)
            new_articles.append(article)
            stats["pdfs_processed"] += 1

            # 크기 등급 카운트
            tier = article.get("pdf_metadata", {}).get("size_tier", "small")
            if tier in stats["size_tiers"]:
                stats["size_tiers"][tier] += 1

            # API rate limit 방지: PDF 사이 짧은 지연
            time.sleep(0.5)

        # 레지스트리는 페이지 한 번 끝날 때마다 저장 (중간 실패 대비)
        save_registry(registry)

    # 최종 결과 저장
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    output_file = DATA_DIR / f"pdf_articles_{today}.json"

    output_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "madini.go.tz (pdf_collector)",
        "stats": stats,
        "total": len(new_articles),
        "articles": new_articles,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # 추가: 기존 raw_*.json에 PDF article들을 병합
    # summarize.py가 raw 파일을 그대로 읽으므로 별도 수정 없이 PDF 콘텐츠가 합류됨
    if new_articles:
        raw_file = DATA_DIR / f"raw_{today}.json"
        if raw_file.exists():
            try:
                with open(raw_file, encoding="utf-8") as f:
                    raw_data = json.load(f)

                # 중복 방지: 이미 있는 article id는 건너뜀
                existing_ids = {a.get("id") for a in raw_data.get("articles", [])}
                merged_count = 0
                for art in new_articles:
                    if art["id"] not in existing_ids:
                        raw_data["articles"].append(art)
                        merged_count += 1

                # 점수순 정렬
                raw_data["articles"].sort(key=lambda a: a.get("score", 0), reverse=True)
                raw_data["total"] = len(raw_data["articles"])

                # 메타데이터에 PDF 수집 사실 기록
                raw_data.setdefault("stats", {})
                raw_data["stats"]["pdf_articles_merged"] = merged_count
                raw_data["pdf_collection_at"] = datetime.now(timezone.utc).isoformat()

                with open(raw_file, "w", encoding="utf-8") as f:
                    json.dump(raw_data, f, ensure_ascii=False, indent=2)

                print(f"\nMerged {merged_count} PDF article(s) into {raw_file.name}")
            except Exception as e:
                print(f"\n[WARN] failed to merge into raw file: {e}")
                print(f"PDF articles preserved separately in {output_file.name}")
        else:
            print(f"\n[INFO] raw_{today}.json not found yet.")
            print(f"PDF articles saved separately in {output_file.name}")
            print(f"Run collect.py first, or summarize.py will read both files.")

    print(f"\n{'='*60}")
    print(f"Pages scanned:         {stats['pages_scanned']}")
    print(f"PDFs found total:      {stats['pdfs_found']}")
    print(f"  - already processed: {stats['pdfs_skipped_known']}")
    print(f"  - too old (stale):   {stats['pdfs_skipped_stale']}")
    print(f"  - newly processed:   {stats['pdfs_processed']}")
    if stats["pdfs_processed"] > 0:
        tiers = stats["size_tiers"]
        print(f"    · small (<{PDF_SIZE_SMALL_MB}MB):     {tiers['small']}")
        print(f"    · medium ({PDF_SIZE_SMALL_MB}-{PDF_SIZE_MEDIUM_MB}MB):   {tiers['medium']}")
        print(f"    · large ({PDF_SIZE_MEDIUM_MB}-{PDF_SIZE_LARGE_MB}MB):  {tiers['large']}")
    print(f"Output:                {output_file}")
    print(f"Registry size:         {len(registry)} PDFs tracked")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
