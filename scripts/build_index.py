"""
KCMO Weekly - build_index.py
Korea Critical Minerals ODA Weekly

Reads the latest cards_YYYY-MM-DD.json and renders index.html
by injecting card HTML and embedding cards data for client-side filtering.

Hybrid approach:
- Server-side: cards pre-rendered as <article> blocks (SEO, no-JS fallback)
- Client-side: cards data embedded as JSON for interactive filtering
"""
import os
import json
import html
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR
DATA_DIR = ROOT_DIR / "data"
TEMPLATE_FILE = ROOT_DIR / "template.html"
OUTPUT_FILE = ROOT_DIR / "index.html"

KST = ZoneInfo("Asia/Seoul")

CATEGORY_KO = {
    "oda_cooperation": "ODA 협력",
    "policy_regulation": "정책·법규",
    "exploration_development": "탐사·개발",
    "supply_chain_trade": "공급망·교역",
    "research_academic": "연구·학술",
}

COUNTRY_KO = {
    "Tanzania": "탄자니아",
    "Indonesia": "인도네시아",
    "Vietnam": "베트남",
    "Mongolia": "몽골",
    "Kazakhstan": "카자흐스탄",
    "Uzbekistan": "우즈베키스탄",
    "Laos": "라오스",
}

LANGUAGE_KO = {
    "sw": "sw 원문",
    "ko": "ko 원문",
    "en": "en 원문",
    "id": "id 원문",
    "vi": "vi 원문",
    "mn": "mn 원문",
}


def esc(s):
    """HTML escape, handle None."""
    if s is None:
        return ""
    return html.escape(str(s))


def render_card(card):
    """Render a single card to HTML string."""
    country_ko = COUNTRY_KO.get(card["country"], card["country"])
    category_ko = card.get("category_ko") or CATEGORY_KO.get(card.get("category"), "")
    lang_badge = LANGUAGE_KO.get(card.get("source_language", "en"), "원문")

    # Extract first 2 tags for prominent display, rest go to data attr only
    tags = card.get("tags", [])
    prominent_tags = tags[:2]

    # Build summary lines (3 lines from korean_summary)
    summary_lines = card.get("korean_summary", [])
    summary_html = "\n".join(
        f'      <p>{esc(line)}</p>' for line in summary_lines
    )

    # Key phrases (Swahili etc.)
    key_phrases = card.get("key_phrases", [])
    phrases_html = ""
    if key_phrases:
        rows = "\n".join(
            f'        <tr><td class="phrase">{esc(p.get("phrase", ""))}</td>'
            f'<td class="meaning">{esc(p.get("meaning", ""))}</td></tr>'
            for p in key_phrases
        )
        phrases_html = f'''
    <details class="phrases">
      <summary>원문 핵심 표현 {len(key_phrases)}개 보기</summary>
      <table>
{rows}
      </table>
    </details>'''

    # ODA relevance (KCMO-specific)
    relevance = card.get("oda_relevance", "")
    relevance_html = ""
    if relevance:
        relevance_html = f'''
    <div class="relevance">
      <div class="relevance-label">한국 ODA 시사점</div>
      <p>{esc(relevance)}</p>
    </div>'''

    # Tag chips (after country/category)
    tag_chips = "\n".join(
        f'      <span class="chip chip-tag">{esc(t)}</span>'
        for t in prominent_tags
    )

    return f'''<article class="card"
    data-id="{esc(card.get("id", ""))}"
    data-country="{esc(card["country"])}"
    data-category="{esc(card.get("category", ""))}"
    data-language="{esc(card.get("source_language", "en"))}"
    data-tags="{esc(",".join(tags))}"
    data-score="{esc(card.get("score", 0))}"
    data-published="{esc(card.get("published", ""))}">
    <div class="card-meta">
      <span class="chip chip-country">{esc(country_ko)}</span>
      <span class="chip chip-category">{esc(category_ko)}</span>
{tag_chips}
      <span class="card-score">{esc(card.get("score", 0))}</span>
    </div>
    <h3><a href="{esc(card.get("url", "#"))}" target="_blank" rel="noopener">{esc(card.get("title", ""))}</a></h3>
    <div class="card-source">
      <span>{esc(card.get("source", ""))} · {esc(card.get("published", ""))}</span>
      <a class="chip chip-lang chip-lang-link" href="{esc(card.get("url", "#"))}" target="_blank" rel="noopener" title="원문 보기">{esc(lang_badge)} ↗</a>
    </div>
    <div class="summary">
{summary_html}
    </div>{relevance_html}{phrases_html}
  </article>'''


def count_by(cards, key, ko_map=None):
    """Count cards grouped by a key, returning sorted list of (label, count)."""
    counts = {}
    for c in cards:
        val = c.get(key)
        if val:
            counts[val] = counts.get(val, 0) + 1
    out = []
    for val, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        label = ko_map.get(val, val) if ko_map else val
        out.append((val, label, cnt))
    return out


def build_filter_options(label, items, all_count):
    """Build <option> list with counts."""
    opts = [f'<option value="">전체 ({all_count})</option>']
    for val, lbl, cnt in items:
        opts.append(f'<option value="{esc(val)}">{esc(lbl)} ({cnt})</option>')
    return "\n          ".join(opts)


def collect_tags(cards):
    """Aggregate all unique tags across cards."""
    counter = {}
    for c in cards:
        for t in c.get("tags", []):
            counter[t] = counter.get(t, 0) + 1
    return sorted(counter.items(), key=lambda x: -x[1])


def main():
    # Find latest cards file
    cards_files = sorted(DATA_DIR.glob("cards_*.json"))
    if not cards_files:
        print(f"ERROR: no cards_*.json found in {DATA_DIR}")
        return
    cards_file = cards_files[-1]
    print(f"Reading: {cards_file}")

    with open(cards_file, encoding="utf-8") as f:
        data = json.load(f)

    cards = data.get("articles", [])
    week_of = data.get("week_of", "")
    total = len(cards)

    # Sort by score desc for default display
    cards.sort(key=lambda c: c.get("score", 0), reverse=True)

    # Render cards
    cards_html = "\n\n  ".join(render_card(c) for c in cards) if cards else \
        '<p class="empty">이번 주는 임계값 이상의 ODA 동향이 없습니다.</p>'

    # Build filter dropdowns
    country_items = count_by(cards, "country", COUNTRY_KO)
    category_items = count_by(cards, "category", CATEGORY_KO)
    tag_items = collect_tags(cards)

    country_opts = build_filter_options("국가", country_items, total)
    category_opts = build_filter_options("카테고리", category_items, total)

    # Tag dropdown (top 10 tags only to keep UI clean)
    top_tags = tag_items[:10]
    tag_opts_list = [f'<option value="">전체 ({total})</option>']
    for tag, cnt in top_tags:
        tag_opts_list.append(f'<option value="{esc(tag)}">{esc(tag)} ({cnt})</option>')
    tag_opts = "\n          ".join(tag_opts_list)

    # Compute next dispatch date (next Sunday 08:00 KST from week_of)
    try:
        wd = datetime.strptime(week_of, "%Y-%m-%d").replace(tzinfo=KST)
        days_to_sun = (6 - wd.weekday()) % 7
        if days_to_sun == 0:
            days_to_sun = 7
        # 다음 일요일 = 발행일 + days_to_sun
        next_sun = wd + timedelta(days=days_to_sun)
        next_dispatch = next_sun.strftime("%Y-%m-%d") + " 08:00"
    except Exception:
        next_dispatch = "일요일 08:00 KST"

    # Embedded JSON for client-side filtering
    cards_data_json = json.dumps(cards, ensure_ascii=False)

    # Mailchimp 구독 폼 URL - 환경변수 또는 기본값
    # 박사님이 Mailchimp 대시보드 → Audience → Signup forms → Embedded forms에서
    # 가져올 수 있음. CMW의 us13 서버 사용 (박사님 메모리에 기록됨).
    mailchimp_form_url = os.environ.get(
        "MAILCHIMP_FORM_URL",
        # KCMO 기본값 - 박사님이 Mailchimp 구독 폼 URL을 얻으시면
        # GitHub Secrets에 MAILCHIMP_FORM_URL로 등록하시면 됨
        "#mailchimp-not-configured"
    )

    # Load template, substitute placeholders
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    output = (template
              .replace("{{WEEK_OF}}", esc(week_of))
              .replace("{{TOTAL}}", str(total))
              .replace("{{NEXT_DISPATCH}}", esc(next_dispatch))
              .replace("{{MAILCHIMP_FORM_URL}}", esc(mailchimp_form_url))
              .replace("{{COUNTRY_OPTIONS}}", country_opts)
              .replace("{{CATEGORY_OPTIONS}}", category_opts)
              .replace("{{TAG_OPTIONS}}", tag_opts)
              .replace("{{CARDS_HTML}}", cards_html)
              .replace("{{CARDS_DATA}}", cards_data_json))

    OUTPUT_FILE.write_text(output, encoding="utf-8")
    print(f"Wrote: {OUTPUT_FILE}")
    print(f"Cards rendered: {total}")

    # 아카이브 인덱스 갱신 (풀다운 메뉴용)
    build_archive_index()


def build_archive_index():
    """data/cards_*.json 을 스캔해 data/archive-index.json 작성.

    같은 week_of 가 여러 파일에 있으면 generated_at 가장 최신 한 개만 선택
    (수동 dispatch + cron 지연 발화로 같은 회차가 중복 발생한 사례 정리).
    total_cards == 0 인 파일은 제외.
    """
    weeks_by_date = {}

    for cf in sorted(DATA_DIR.glob("cards_*.json")):
        try:
            with open(cf, encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            print(f"  [archive] skip {cf.name}: {e}")
            continue

        week_of = d.get("week_of") or ""
        if not week_of:
            continue
        articles = d.get("articles", []) or []
        total = d.get("total_cards") if d.get("total_cards") is not None else len(articles)
        if not total:
            continue

        generated_at = d.get("generated_at") or ""

        # category counts + top tags
        cat_counts = {}
        tag_counter = {}
        for a in articles:
            cat = a.get("category")
            if cat:
                cat_counts[cat] = cat_counts.get(cat, 0) + 1
            for t in a.get("tags", []) or []:
                tag_counter[t] = tag_counter.get(t, 0) + 1
        top_tags = [t for t, _ in sorted(tag_counter.items(), key=lambda x: -x[1])[:5]]

        entry = {
            "week_of": week_of,
            "filename": cf.name,
            "total_cards": total,
            "category_counts": cat_counts,
            "top_tags": top_tags,
            "generated_at": generated_at,
        }

        existing = weeks_by_date.get(week_of)
        if existing is None or generated_at > existing.get("generated_at", ""):
            weeks_by_date[week_of] = entry

    weeks_sorted = sorted(
        weeks_by_date.values(),
        key=lambda w: w["week_of"],
        reverse=True,
    )
    index = {
        "total_weeks": len(weeks_sorted),
        "latest_week": weeks_sorted[0]["week_of"] if weeks_sorted else "",
        "weeks": weeks_sorted,
    }

    out_path = DATA_DIR / "archive-index.json"
    out_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote: {out_path} ({len(weeks_sorted)} weeks)")


if __name__ == "__main__":
    main()
