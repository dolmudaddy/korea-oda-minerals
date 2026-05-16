"""
KCMO Weekly - generate_obsidian.py
Korea Critical Minerals ODA Weekly

Reads the latest cards_YYYY-MM-DD.json and writes per-card markdown notes
plus a weekly index note into a separate Obsidian vault repo.

Pipeline position: after summarize.py, before send_email.py.
The vault repo is checked out to a separate path by the workflow; this
script accepts --vault <path> pointing at that checkout.

Outputs (under {vault}/KCMO/):
  README.md                                   (seeded once)
  articles/{YYYY}/{date}-{country}-{slug}.md  (one per card)
  weekly/{YYYY}/KCMO Weekly {YYYY-Wnn}.md    (one per week)

Wikilink generation rules live in obsidian_vocab.yaml; the cooperation
node whitelist (country × mineral) defaults to sources.yaml's
target_countries[*].primary_minerals when use_sources_yaml is true.

Usage:
  python scripts/generate_obsidian.py --vault ./vault-checkout
  python scripts/generate_obsidian.py --vault /tmp/test --dry-run
  python scripts/generate_obsidian.py --vault /tmp/test --cards data/cards_2026-05-15.json
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR
DATA_DIR = ROOT_DIR / "data"
VOCAB_FILE = ROOT_DIR / "obsidian_vocab.yaml"
SOURCES_FILE = ROOT_DIR / "sources.yaml"

KCMO_ROOT = "KCMO"   # subfolder inside vault to keep KCMO content isolated

# Mineral key (sources.yaml primary_minerals) → Korean node name.
# Used to translate sources.yaml's English mineral keys when building the
# auto cooperation_nodes set. Anything missing here falls back to the key
# itself (which would not match a Korean mineral node — silently skipped).
SOURCES_MINERAL_KO = {
    "graphite": "흑연",
    "lithium": "리튬",
    "cobalt": "코발트",
    "nickel": "니켈",
    "copper": "구리",
    "rare_earth": "희토류",
    "uranium": "우라늄",
    "tungsten": "텅스텐",
    "bauxite": "보크사이트",
    "tin": "주석",
    "fluorspar": "형석",
    "helium": "헬륨",
    "potash": "칼륨염",
    "chromium": "크롬",
    "titanium": "티타늄",
    "manganese": "망간",
    "gold": "금",
}

CATEGORY_KO = {
    "oda_cooperation": "ODA 협력",
    "policy_regulation": "정책·법규",
    "exploration_development": "탐사·개발",
    "supply_chain_trade": "공급망·교역",
    "research_academic": "연구·학술",
}

LANG_LABEL = {
    "sw": "스와힐리어", "ko": "한국어", "en": "영어",
    "id": "인도네시아어", "vi": "베트남어", "mn": "몽골어",
    "ru": "러시아어", "kk": "카자흐어", "uz": "우즈베크어", "lo": "라오어",
}

PLACEHOLDER_PREFIX = "\x00WL"
PLACEHOLDER_SUFFIX = "\x00"


# ---------------------------------------------------------------------
# Vocab loading and pattern compilation
# ---------------------------------------------------------------------
def load_vocab():
    with open(VOCAB_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources():
    with open(SOURCES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def is_ascii_word(s):
    """True if string is pure ASCII letters/digits/spaces (eligible for \\b)."""
    return s.isascii()


def compile_patterns(vocab):
    """Return list of (compiled_regex, target_node) sorted by pattern length desc.

    English/ASCII patterns get word-boundary regex (case-insensitive).
    Korean/mixed patterns get literal substring match (case-sensitive).
    Longest patterns first so 'rare earth elements' beats 'rare earth'.
    """
    entries = []
    for category in ("countries", "minerals", "korea_institutions",
                     "partner_institutions", "policy_terms"):
        for item in vocab.get(category, []) or []:
            node = item["node"]
            for pat in item.get("patterns", []):
                if not pat:
                    continue
                if is_ascii_word(pat):
                    # Use ASCII-only lookarounds so 'KIAT' matches inside
                    # 'KIAT의' (Korean particle attached). Python's \b is
                    # Unicode-aware and would treat T-의 as no-boundary.
                    rx = re.compile(
                        r"(?<![A-Za-z0-9_])" + re.escape(pat)
                        + r"(?![A-Za-z0-9_])",
                        re.IGNORECASE,
                    )
                else:
                    rx = re.compile(re.escape(pat))
                entries.append((len(pat), rx, node, pat))

    entries.sort(key=lambda x: x[0], reverse=True)
    return [(rx, node, pat) for _, rx, node, pat in entries]


def build_country_lookup(vocab):
    """en (e.g., 'Tanzania') → ko ('탄자니아') mapping for cooperation nodes."""
    out = {}
    for item in vocab.get("countries", []) or []:
        en = item.get("en")
        if en:
            out[en] = item["node"]
    return out


def build_cooperation_node_set(vocab, sources, country_lookup):
    """Set of valid '국가 광종' cooperation nodes.

    If vocab.cooperation_nodes.whitelist is non-empty, use it verbatim.
    Else if use_sources_yaml is true, build from sources.yaml's
    target_countries[*].primary_minerals.
    Else return empty set (no cooperation nodes generated).
    """
    cfg = vocab.get("cooperation_nodes", {}) or {}
    whitelist = cfg.get("whitelist") or []
    if whitelist:
        return set(whitelist)

    if not cfg.get("use_sources_yaml", True):
        return set()

    out = set()
    for c in sources.get("target_countries", []) or []:
        country_en = c.get("name")
        country_ko = country_lookup.get(country_en) or c.get("name_ko")
        if not country_ko:
            continue
        for m_key in c.get("primary_minerals", []) or []:
            mineral_ko = SOURCES_MINERAL_KO.get(m_key)
            if mineral_ko:
                out.add(f"{country_ko} {mineral_ko}")
    return out


# ---------------------------------------------------------------------
# Linkify with placeholder protection
# ---------------------------------------------------------------------
def _protect_existing_wikilinks(text):
    """Replace existing [[...]] with placeholders; return (text, restorations)."""
    placeholders = []
    def _sub(m):
        placeholders.append(m.group(0))
        return f"{PLACEHOLDER_PREFIX}{len(placeholders) - 1}{PLACEHOLDER_SUFFIX}"
    new_text = re.sub(r"\[\[[^\[\]]+\]\]", _sub, text)
    return new_text, placeholders


def _restore_placeholders(text, placeholders):
    for i, original in enumerate(placeholders):
        text = text.replace(
            f"{PLACEHOLDER_PREFIX}{i}{PLACEHOLDER_SUFFIX}", original
        )
    return text


def linkify(text, compiled_patterns):
    """Insert [[node]] wikilinks into text. Returns (new_text, matched_nodes_set).

    Algorithm:
    1. Protect existing [[...]] with placeholders.
    2. Walk patterns in length-desc order; collect non-overlapping match spans.
    3. Apply replacements from end to start so earlier indices stay valid.
    4. Restore placeholders.
    """
    if not text:
        return text, set()

    text, placeholders = _protect_existing_wikilinks(text)
    matched_nodes = set()
    occupied = []   # list of (start, end) covering already-claimed spans
    edits = []      # list of (start, end, replacement)

    def _overlaps(s, e):
        for os_, oe in occupied:
            if not (e <= os_ or s >= oe):
                return True
        return False

    for rx, node, _pat in compiled_patterns:
        for m in rx.finditer(text):
            s, e = m.start(), m.end()
            if _overlaps(s, e):
                continue
            # Skip if the match is inside a placeholder span
            slice_str = text[s:e]
            if PLACEHOLDER_PREFIX in slice_str:
                continue
            matched_nodes.add(node)
            edits.append((s, e, f"[[{node}]]"))
            occupied.append((s, e))

    edits.sort(key=lambda x: x[0], reverse=True)
    for s, e, repl in edits:
        text = text[:s] + repl + text[e:]

    text = _restore_placeholders(text, placeholders)
    return text, matched_nodes


# ---------------------------------------------------------------------
# Card → related nodes (for frontmatter and "관련 개념" section)
# ---------------------------------------------------------------------
def split_compound_tag(tag):
    """Split tags like '희토류·리튬' into ['희토류', '리튬']."""
    parts = re.split(r"[·,/，、]", tag)
    return [p.strip() for p in parts if p.strip()]


def collect_related_nodes(card, vocab, compiled_patterns,
                          country_lookup, coop_set):
    """Compute the full set of [[nodes]] for a card.

    Sources:
    - linkify hits in title + korean_summary + oda_relevance + key_phrases
    - tag-derived nodes (each tag as literal candidate, also split compound)
    - country node (always)
    - cooperation node ([[국가 광종]]) if country + matched mineral pair
      is in coop_set
    """
    found_nodes = set()

    # Linkify scan over all narrative text
    text_blob = " ".join([
        card.get("title", ""),
        " ".join(card.get("korean_summary", [])),
        card.get("oda_relevance", ""),
        " ".join(p.get("phrase", "") + " " + p.get("meaning", "")
                 for p in card.get("key_phrases", []) or []),
    ])
    _, hits = linkify(text_blob, compiled_patterns)
    found_nodes.update(hits)

    # Country always present
    country_ko = country_lookup.get(card.get("country"), card.get("country"))
    if country_ko:
        found_nodes.add(country_ko)

    # Tag-as-node: each tag (and split parts) is checked against vocab.
    # If the tag string equals or contains a vocab pattern's literal form
    # (Korean only), treat it as a hit.
    for tag in card.get("tags", []) or []:
        for part in split_compound_tag(tag):
            # exact-match check by linkifying the tag itself
            _, tag_hits = linkify(part, compiled_patterns)
            found_nodes.update(tag_hits)

    # Cooperation nodes: for each mineral node found and known country,
    # check whether '국가 광종' is in coop_set.
    if country_ko:
        mineral_nodes = {n for n in found_nodes if _is_mineral_node(n, vocab)}
        for m in mineral_nodes:
            candidate = f"{country_ko} {m}"
            if candidate in coop_set:
                found_nodes.add(candidate)

    return sorted(found_nodes)


def _is_mineral_node(node, vocab):
    return node in {item["node"] for item in vocab.get("minerals", []) or []}


def categorize_nodes(nodes, vocab, country_lookup):
    """Group sorted node list by category for the '관련 개념' section."""
    by_cat = {
        "국가": [], "광종": [], "한국 기관": [],
        "협력국 기관": [], "정책": [], "협력 노드": [],
    }
    country_set = {item["node"] for item in vocab.get("countries", []) or []}
    mineral_set = {item["node"] for item in vocab.get("minerals", []) or []}
    korea_set = {item["node"]
                 for item in vocab.get("korea_institutions", []) or []}
    partner_set = {item["node"]
                   for item in vocab.get("partner_institutions", []) or []}
    policy_set = {item["node"]
                  for item in vocab.get("policy_terms", []) or []}

    for n in nodes:
        if n in country_set:
            by_cat["국가"].append(n)
        elif n in mineral_set:
            by_cat["광종"].append(n)
        elif n in korea_set:
            by_cat["한국 기관"].append(n)
        elif n in partner_set:
            by_cat["협력국 기관"].append(n)
        elif n in policy_set:
            by_cat["정책"].append(n)
        elif " " in n and any(n.startswith(c + " ") for c in country_set):
            by_cat["협력 노드"].append(n)
        else:
            by_cat["정책"].append(n)   # fallback bucket
    return by_cat


# ---------------------------------------------------------------------
# Filename + ISO week helpers
# ---------------------------------------------------------------------
_FILENAME_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def slugify(s, max_len=40):
    s = _FILENAME_BAD_CHARS.sub("", s or "")
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace(" ", "-")
    if len(s) > max_len:
        s = s[:max_len].rstrip("-")
    return s


def normalize_date(raw, fallback_iso):
    """Normalize a published-date string to 'YYYY-MM-DD'.

    Inputs vary by source:
    - ISO 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS+00:00' → first 10 chars
    - RFC 2822 'Wed, 13 May 2026 12:50:22 +0000' → email.utils parser
    - Empty/None/garbage → fallback_iso (typically week_of)
    """
    if raw:
        s = str(raw).strip()
        if len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-":
            return s[:10]
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(s)
            if dt:
                return dt.strftime("%Y-%m-%d")
        except Exception:
            pass
    return (fallback_iso or "")[:10] or \
        datetime.now(timezone.utc).strftime("%Y-%m-%d")


def card_filename(card, country_ko, fallback_iso):
    """{date}-{country_ko}-{tag1}-{tag2}-{id_short}.md"""
    date = normalize_date(card.get("published"), fallback_iso)
    tags = card.get("tags", []) or []
    tags = [t for t in tags if t and t != country_ko][:2]
    parts = [date, country_ko] + [slugify(t) for t in tags]
    parts.append((card.get("id") or "")[-4:] or "0000")
    name = "-".join(p for p in parts if p)
    return name + ".md"


def iso_week_str(date_str):
    """'2026-05-15' → ('2026-W20', '2026') where folder year is iso year."""
    try:
        dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
    except Exception:
        dt = datetime.now(timezone.utc)
    iso_y, iso_w, _ = dt.isocalendar()
    return f"{iso_y}-W{iso_w:02d}", str(iso_y)


def card_year(card, fallback_iso):
    """Calendar year of the card's published date (for articles/{YYYY}/)."""
    d = normalize_date(card.get("published"), fallback_iso)
    return d.split("-")[0]


# ---------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------
def render_yaml_value(v):
    """Quote a YAML scalar that contains special chars."""
    s = str(v)
    if any(ch in s for ch in ':#{}[]&*!|>\'"%@`,') or s.startswith(("- ", "? ")):
        escaped = s.replace('"', '\\"')
        return f'"{escaped}"'
    return s


def render_card_md(card, vocab, compiled_patterns, country_lookup, coop_set,
                   week_str, week_of):
    country_ko = country_lookup.get(card.get("country"), card.get("country"))
    category = card.get("category", "")
    category_ko = card.get("category_ko") or CATEGORY_KO.get(category, "")
    src_lang = card.get("source_language", "en")
    tier = card.get("tier_weight", 1)
    score = card.get("score", 0)
    pub_date = normalize_date(card.get("published"), week_of)

    related = collect_related_nodes(card, vocab, compiled_patterns,
                                    country_lookup, coop_set)
    grouped = categorize_nodes(related, vocab, country_lookup)

    summary_lines = card.get("korean_summary", []) or []
    title_ko = summary_lines[0] if summary_lines else card.get("title", "")

    # Frontmatter
    fm_lines = ["---"]
    fm_lines.append(f"id: {render_yaml_value(card.get('id', ''))}")
    fm_lines.append(f"title: {render_yaml_value(card.get('title', ''))}")
    fm_lines.append(f"title_ko: {render_yaml_value(title_ko)}")
    fm_lines.append(f"date: {pub_date}")
    fm_lines.append(f"week: {week_str}")
    fm_lines.append(f"country: {country_ko}")
    fm_lines.append(f"country_en: {card.get('country', '')}")
    fm_lines.append(f"category: {category}")
    fm_lines.append(f"category_ko: {render_yaml_value(category_ko)}")
    fm_lines.append(f"source: {render_yaml_value(card.get('source', ''))}")
    fm_lines.append(f"source_url: {card.get('url', '')}")
    fm_lines.append(f"source_language: {src_lang}")
    fm_lines.append(f"tier: {tier}")
    fm_lines.append(f"score: {score}")
    tags = card.get("tags", []) or []
    if tags:
        fm_lines.append("tags:")
        for t in tags:
            fm_lines.append(f"  - {render_yaml_value(t)}")
    if related:
        fm_lines.append("related:")
        for n in related:
            fm_lines.append(f'  - "[[{n}]]"')
    fm_lines.append("---")

    # Linkified narrative
    summary_linkified = [linkify(line, compiled_patterns)[0]
                         for line in summary_lines]
    relevance_linkified = linkify(card.get("oda_relevance", ""),
                                  compiled_patterns)[0]

    # Body
    body = []
    body.append("")
    body.append(f"# {country_ko} — {card.get('title', '')}")
    body.append("")
    src = card.get("source", "")
    url = card.get("url", "#")
    body.append(f"> **출처**: [{src}]({url}) · `{src_lang}` "
                f"({LANG_LABEL.get(src_lang, '원문')})")
    body.append(f"> **발표일**: {pub_date} · "
                f"**점수**: {score} · **카테고리**: [[{category_ko}]]")
    body.append("")
    body.append("## 한국어 요약")
    body.append("")
    for line in summary_linkified:
        body.append(f"- {line}")
    body.append("")
    if relevance_linkified:
        body.append("## 한국 ODA 시사점")
        body.append("")
        body.append(f"> {relevance_linkified}")
        body.append("")

    phrases = card.get("key_phrases", []) or []
    if phrases:
        body.append(f"## 원문 핵심 표현 ({src_lang})")
        body.append("")
        body.append("| 원문 | 한국어 |")
        body.append("|---|---|")
        for p in phrases:
            ph = (p.get("phrase", "") or "").replace("|", "\\|")
            mn = (p.get("meaning", "") or "").replace("|", "\\|")
            body.append(f"| {ph} | {mn} |")
        body.append("")

    if related:
        body.append("## 관련 개념")
        body.append("")
        for label, nodes in grouped.items():
            if nodes:
                joined = " · ".join(f"[[{n}]]" for n in nodes)
                body.append(f"- **{label}**: {joined}")
        body.append("")

    body.append("---")
    body.append("")
    body.append(f"**원문 보기**: <{url}>")
    body.append("")
    body.append(f"*KCMO Weekly 자동 생성, {week_str} "
                f"(id: `{card.get('id', '')}`)*")

    return "\n".join(fm_lines) + "\n" + "\n".join(body) + "\n"


def render_weekly_index(cards, week_str, week_of, country_lookup, vocab):
    total = len(cards)

    # Bucket counts
    by_country = {}
    by_category = {}
    coop_counter = {}
    korea_counter = {}
    partner_counter = {}
    mineral_counter = {}

    country_set = {item["node"] for item in vocab.get("countries", []) or []}
    mineral_set = {item["node"] for item in vocab.get("minerals", []) or []}
    korea_set = {item["node"]
                 for item in vocab.get("korea_institutions", []) or []}
    partner_set = {item["node"]
                   for item in vocab.get("partner_institutions", []) or []}

    cards_by_country = {}
    for c in cards:
        country_ko = country_lookup.get(c.get("country"), c.get("country"))
        by_country[country_ko] = by_country.get(country_ko, 0) + 1
        cards_by_country.setdefault(country_ko, []).append(c)

        cat = c.get("category_ko") or CATEGORY_KO.get(c.get("category", ""), "")
        by_category[cat] = by_category.get(cat, 0) + 1

        # Use precomputed _related cached on the card (set by main)
        for n in c.get("_related", []):
            if n in mineral_set:
                mineral_counter[n] = mineral_counter.get(n, 0) + 1
            elif n in korea_set:
                korea_counter[n] = korea_counter.get(n, 0) + 1
            elif n in partner_set:
                partner_counter[n] = partner_counter.get(n, 0) + 1
            elif " " in n and any(n.startswith(cc + " ") for cc in country_set):
                coop_counter[n] = coop_counter.get(n, 0) + 1

    out = []
    out.append("---")
    out.append("type: weekly-index")
    out.append(f"week: {week_str}")
    out.append(f"week_of: {week_of}")
    out.append(f"total_cards: {total}")
    out.append(f"generated_at: {datetime.now(timezone.utc).isoformat()}")
    out.append("---")
    out.append("")
    out.append(f"# KCMO Weekly {week_str}")
    out.append("")
    out.append(f"> 발송일 {week_of} · 총 {total}건")
    out.append("")

    if by_category:
        out.append("## 카테고리")
        out.append("")
        for cat, cnt in sorted(by_category.items(), key=lambda x: -x[1]):
            out.append(f"- **{cat}** ({cnt}건)")
        out.append("")

    if cards_by_country:
        out.append("## 국가별 카드")
        out.append("")
        country_order = sorted(cards_by_country.keys(),
                               key=lambda k: -by_country[k])
        for country in country_order:
            out.append(f"### {country} ({by_country[country]}건)")
            out.append("")
            cs = sorted(cards_by_country[country],
                        key=lambda c: -c.get("score", 0))
            for c in cs:
                stem = Path(c["_filename"]).stem
                cat_ko = c.get("category_ko") or \
                    CATEGORY_KO.get(c.get("category", ""), "")
                out.append(f"- [[{stem}]] — 점수 {c.get('score', 0)} · {cat_ko}")
            out.append("")

    def _render_counter(label, counter):
        if not counter:
            return
        out.append(f"## 이번 주 등장 {label}")
        out.append("")
        chunks = [f"[[{n}]] ({cnt})"
                  for n, cnt in sorted(counter.items(), key=lambda x: -x[1])]
        out.append(" · ".join(chunks))
        out.append("")

    _render_counter("협력 노드", coop_counter)
    _render_counter("한국 기관", korea_counter)
    _render_counter("협력국 기관", partner_counter)
    _render_counter("광종", mineral_counter)

    out.append("---")
    out.append("")
    out.append(f"*KCMO Weekly 자동 생성, "
               f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*")
    out.append("")

    return "\n".join(out)


README_SEED = """# KCMO Vault

KCMO Weekly (Korea Critical Minerals ODA Weekly)가 매주 일요일 08:00 KST에
자동 생성하는 노트 모음입니다.

## 폴더 구조

- `articles/{연도}/` — 카드 1건당 마크다운 노트 1개
- `weekly/{연도}/KCMO Weekly {YYYY-Www}.md` — 주간 인덱스

## 옵시디언 활용

### Graph View
좌측 Graph 아이콘 → 카드와 협력 노드(국가·광종·기관) 사이 연결망 시각화.
1년 누적 시 핵심광물 ODA 도메인 지형도가 만들어집니다.

### Wikilink로 협력 관점 탐색
- `[[탄자니아]]` — 탄자니아 관련 모든 카드
- `[[KIAT]]` — KIAT가 등장한 모든 카드
- `[[탄자니아 흑연]]` — 탄자니아 × 흑연 협력 노드 (자동 생성)
- 좌측 Backlinks 패널에 해당 노드를 인용한 모든 카드가 표시됨

### Dataview 쿼리 예시
```dataview
TABLE date, source, score
FROM "KCMO/articles"
WHERE contains(tags, "흑연") AND country = "탄자니아"
SORT date DESC
LIMIT 20
```

## 자동 생성 정책

- **카드 노트는 기계 출력 영역**입니다. 같은 id로 매주 덮어쓰기됨.
- 박사님 수기 메모는 카드가 아니라 **협력 노드 페이지**에 작성하세요.
  예: `[[탄자니아]]`, `[[KIAT]]`, `[[탄자니아 흑연]]`
- 노드 페이지는 옵시디언이 빈 wikilink 클릭 시 자동 생성합니다.

## 출처

- **운영자**: 조성준 박사 (KIGAM 책임연구원)
- **소스 저장소**: https://github.com/dolmudaddy/korea-oda-minerals
- **사이트**: https://dolmudaddy.github.io/korea-oda-minerals/
"""


# ---------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------
def find_latest_cards():
    files = sorted(DATA_DIR.glob("cards_*.json"))
    if not files:
        print(f"ERROR: no cards_*.json in {DATA_DIR}", file=sys.stderr)
        sys.exit(1)
    return files[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", required=True,
                    help="Path to Obsidian vault checkout root")
    ap.add_argument("--cards", default=None,
                    help="Path to cards_YYYY-MM-DD.json (default: latest)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print summary only, do not write files")
    args = ap.parse_args()

    vault_root = Path(args.vault).resolve()
    cards_path = Path(args.cards) if args.cards else find_latest_cards()

    print(f"Vault root:   {vault_root}")
    print(f"Cards file:   {cards_path}")
    print(f"Dry run:      {args.dry_run}")

    vocab = load_vocab()
    sources = load_sources()
    compiled = compile_patterns(vocab)
    country_lookup = build_country_lookup(vocab)
    coop_set = build_cooperation_node_set(vocab, sources, country_lookup)
    print(f"Vocab patterns: {len(compiled)} | cooperation nodes: {len(coop_set)}")

    with open(cards_path, encoding="utf-8") as f:
        data = json.load(f)
    cards = data.get("articles", [])
    week_of = data.get("week_of", cards_path.stem.replace("cards_", ""))
    week_str, _ = iso_week_str(week_of)
    print(f"Week:         {week_str} (week_of={week_of}) | cards: {len(cards)}")

    kcmo_root = vault_root / KCMO_ROOT
    articles_root = kcmo_root / "articles"
    weekly_root = kcmo_root / "weekly"
    readme_path = kcmo_root / "README.md"

    written_count = 0
    skipped_count = 0
    errors = []

    for card in cards:
        country_ko = country_lookup.get(card.get("country"),
                                        card.get("country"))
        try:
            md = render_card_md(card, vocab, compiled, country_lookup,
                                coop_set, week_str, week_of)
        except Exception as e:
            errors.append(f"render failed for {card.get('id')}: {e}")
            continue

        # Cache related nodes for the weekly index
        related = collect_related_nodes(card, vocab, compiled,
                                        country_lookup, coop_set)
        card["_related"] = related

        fname = card_filename(card, country_ko or "", week_of)
        card["_filename"] = fname
        out_dir = articles_root / card_year(card, week_of)
        out_path = out_dir / fname

        if args.dry_run:
            written_count += 1
            print(f"  [DRY] {out_path.relative_to(vault_root)}")
            continue

        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        written_count += 1

    # Weekly index note
    weekly_year = week_str.split("-W")[0]
    weekly_path = weekly_root / weekly_year / f"KCMO Weekly {week_str}.md"
    weekly_md = render_weekly_index(cards, week_str, week_of,
                                    country_lookup, vocab)
    if args.dry_run:
        print(f"  [DRY] {weekly_path.relative_to(vault_root)}")
    else:
        weekly_path.parent.mkdir(parents=True, exist_ok=True)
        weekly_path.write_text(weekly_md, encoding="utf-8")

    # Seed README once
    if not args.dry_run:
        if not readme_path.exists():
            kcmo_root.mkdir(parents=True, exist_ok=True)
            readme_path.write_text(README_SEED, encoding="utf-8")
            print(f"  Seeded {readme_path.relative_to(vault_root)}")

    print(f"\n{'='*60}")
    print(f"Cards written: {written_count}")
    print(f"Skipped:       {skipped_count}")
    print(f"Weekly index:  {weekly_path.relative_to(vault_root)}")
    if errors:
        print(f"Errors ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
