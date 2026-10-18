"""
KCMO collect — 공통 코어(mincore) 그림자 단계 (리뉴얼 3b)

collect.py가 legacy raw를 저장하기 직전에 호출된다. 하는 일:
  1) Google News 주소 → 원매체 주소 (mincore.resolve)
  2) 본문 추출 (mincore.extract) — 전문은 data/_cache/bodies/ 에만(gitignore)
  3) 통일 카드(card.v1) → data/collected_YYYY-MM-DD.json
  4) 실행 보고 → data/reports/run_YYYY-MM-DD.{json,md}
  5) legacy raw 기사에 '키 추가만' (url·id·summary_raw 등 기존 키는 그대로)
  6) 발행 원장(data/published_ledger.json) 대조 — 이미 발행한 기사는
     [LEDGER-url]/[LEDGER-title] 로그 + ledger_hit 키로 표시만 (리뉴얼 3d).
     실제 제외는 collect.py에서 KCMO_LEDGER_ENFORCE=1일 때만.

그림자 원칙: 기존 산출물(raw의 기존 키, 기사 수·순서)은 바꾸지 않는다.
회차 내 중복(원매체 주소 기준)도 제거하지 않고 dup_of 키로 표시만 한다.

활성 조건: 환경변수 KCMO_CORE_SHADOW=1 이고 mincore가 설치돼 있을 때만.
2026-10-25 회차부터 운영 weekly.yml도 KCMO_CORE_SHADOW=1 + KCMO_LEDGER_ENFORCE=1로 실행한다
(원장 제외 목록은 data/reports/run_*.md에 기록).
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

SERVICE = "kcmo"


def enabled():
    if os.environ.get("KCMO_CORE_SHADOW") != "1":
        return False
    try:
        import mincore  # noqa: F401
    except ImportError:
        print("[core-shadow] KCMO_CORE_SHADOW=1 이지만 mincore 미설치 → 건너뜀")
        return False
    return True


def _source_fields(art):
    """legacy 기사 → card.v1 source/ext 필드."""
    is_gn = art.get("source_type") == "google_news"
    ext = {
        "country": art.get("country"),
        "source_type": art.get("source_type") or "tier_source",
        "search_query": art.get("search_query"),
        "priority_boost": art.get("priority_boost", 0),
        "legacy_id": art.get("id"),
    }
    return is_gn, ext


def run(results, stats, today, data_dir):
    """results(legacy 기사 목록)에 키를 추가하고 collected/report 파일을 쓴다."""
    from mincore import __version__ as mincore_version
    from mincore.card import build_card, legacy_extra, validate
    from mincore.domain_rules import load_rules
    from mincore.extract import extract_body
    from mincore.fetch import Fetcher
    from mincore.ledger import Ledger
    from mincore.normalize import canonical_url, domain_of, norm_date
    from mincore.report import RunReport
    from mincore.resolve import resolve_many

    data_dir = Path(data_dir)
    rep = RunReport(SERVICE, run_date=today)
    rep.count("fetched", stats.get("items_fetched", 0) + stats.get("google_news_items", 0))
    rep.count("qualified", stats.get("items_qualified", 0))
    for name, s in (stats.get("per_source") or {}).items():
        rep.source(name, fetched=s.get("fetched", 0), qualified=s.get("qualified", 0))
    rep.source("Google News", fetched=stats.get("google_news_items", 0),
               qualified=sum(1 for a in results if a.get("source_type") == "google_news"))

    print(f"\n[core-shadow] mincore {mincore_version} — 기사 {len(results)}건 주소 해석")
    resolutions = resolve_many([a.get("url", "") for a in results])

    ledger_path = data_dir / "published_ledger.json"
    ledger = Ledger.load(ledger_path) if ledger_path.exists() else None
    if ledger is None:
        print("[core-shadow] 발행 원장 없음 → 원장 대조 건너뜀")
    else:
        print(f"[core-shadow] 발행 원장 {len(ledger.entries)}건 ({', '.join(ledger.weeks()[:1] + ledger.weeks()[-1:])})")
    ledger_hits = 0

    rules, fetcher, ctx = load_rules(), Fetcher(), {}
    cache_dir = data_dir / "_cache" / "bodies"
    cards, seen, errors = [], {}, 0
    for i, (art, r) in enumerate(zip(results, resolutions), 1):
        rep.resolved(r.method)
        is_gn, ext = _source_fields(art)
        url = r.url or art.get("url", "")
        canon = canonical_url(url) if r.url else None

        if ledger is not None:                         # 이전 회차 발행분: 표시만
            reason = ledger.check(r.url, art.get("title"))
            if reason:
                art["ledger_hit"] = reason
                rep.excluded(reason, title=art.get("title"), url=r.url)
                ledger_hits += 1
                tag = "url" if reason == "url" else "title"
                print(f"  [LEDGER-{tag}] ({reason}) {art.get('title', '')[:60]}")
        if canon and canon in seen:                    # 회차 내 중복: 표시만
            art["dup_of"] = seen[canon]
            rep.count("dedup_dropped")
        if r.url:
            body = extract_body(r.url, fetcher, rules, title=art.get("title"),
                                rss_summary=art.get("summary_raw"), cache_dir=cache_dir, ctx=ctx)
        else:
            from mincore.extract import BodyResult
            body = BodyResult(block_type="resolve_fail", error=r.error)
        card = build_card(
            SERVICE, title=art.get("title", ""), url=url,
            gnews_url=art.get("url") if is_gn else None,
            source_name=art.get("source", ""), tier_weight=art.get("tier_weight"),
            language=art.get("source_language"),
            published=norm_date(art.get("published")) or body.extracted_date,
            published_from=("gnews" if is_gn else "rss") if art.get("published") else
                           ("meta" if body.extracted_date else None),
            score=art.get("score"), body=body, ext=ext)
        if not r.url:
            card["url"] = None                         # 해석 실패: 원매체 주소 없음
        errs = validate(card) if r.url else []
        if errs:
            errors += 1
            print(f"  [core-shadow][INVALID] {art.get('id')}: {errs}")
        if canon and canon not in seen:
            seen[canon] = card["card_id"]
        cards.append(card)
        rep.body(domain_of(url) if r.url else "(주소 해석 실패)", body.to_record())
        art.update(legacy_extra(card))                 # 키 추가만
        art["resolve_method"] = r.method
        print(f"  [{i}/{len(results)}] {body.status:<10} {body.source:<15} "
              f"{body.block_type or '':<12} {domain_of(url) if r.url else '-'}")

    rep.count("validation_errors", errors)
    if ledger is not None:
        print(f"[core-shadow] 원장 대조: 이번 회차 {len(results)}건 중 원장 제외 대상 {ledger_hits}건")
    out = data_dir / f"collected_{today}.json"
    out.write_text(json.dumps({
        "schema_version": "card.v1",
        "service": SERVICE,
        "run_date": today,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mincore_version": mincore_version,
        "total": len(cards),
        "cards": cards,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    rp = rep.write(data_dir / "reports")
    print(f"[core-shadow] 저장: {out.name}, {rp.name} (검증 오류 {errors})")
    return cards
