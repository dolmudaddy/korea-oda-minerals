"""
리뉴얼 본문 추출 실측 (probe 전용, 운영 파이프라인과 무관)

카드 JSON(KCMO cards_*.json / CMW week-*.json)을 읽어 공통 코어(mincore)로
  1) Google News 중계 주소 → 원매체 주소 (mincore.resolve: 배치 + 3회 지수 재시도 + 리다이렉트)
  2) 원매체 주소 → 본문 (mincore.extract: trafilatura → 도메인 대체표 → og:description → RSS 설명)
  3) body_status / block_type / body_source / 발행일 추출·일치 여부
를 기록한다. 운영 collect와 같은 코드를 쓰므로 측정값이 곧 운영 기대값이다.
공개 저장소이므로 본문 전문은 저장하지 않는다 (길이·sha256·앞 200자·인용 구절만).

사용:
  py scripts/probe/body_probe.py --format kcmo [--limit 5]
  py scripts/probe/body_probe.py --format cmw  [--limit 5]
  py scripts/probe/body_probe.py --report
  py scripts/probe/body_probe.py --compare A.json B.json [C.json ...] --labels 1단계 2단계 3a
의존성: scripts/probe/requirements.txt (mincore)
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from mincore import __version__ as MINCORE_VERSION
from mincore.domain_rules import load_rules
from mincore.extract import FULL_MIN, PARTIAL_MIN, extract_body
from mincore.fetch import Fetcher
from mincore.normalize import domain_of, is_gnews, norm_date
from mincore.resolve import resolve_many

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "probe"
# Actions에서는 CMW repo checkout 경로를 CMW_DATA_DIR로 지정
CMW_DATA = Path(os.environ.get("CMW_DATA_DIR",
                               r"C:\Users\Seong-Jun Cho\Documents\GitHub\critical-minerals\data"))
# 결과 파일명 접미사 (예: PROBE_TAG=actions → body_probe_<날짜>_actions.json)
PROBE_TAG = os.environ.get("PROBE_TAG", "")

DEFAULT_INPUTS = {
    "kcmo": [ROOT / "data" / f"cards_{d}.json" for d in
             ("2026-09-20", "2026-09-27", "2026-10-04", "2026-10-11")],
    "cmw": [CMW_DATA / f"week-{d}.json" for d in
            ("2026-09-21", "2026-09-28", "2026-10-05", "2026-10-12")],
}


# ── 입력 어댑터 ───────────────────────────────────────────────
def load_cards(fmt, paths):
    cards = []
    for p in paths:
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        week = d.get("week_of") or re.search(r"\d{4}-\d{2}-\d{2}", Path(p).name).group(0)
        for a in d.get("articles", []):
            cards.append({
                "service": fmt,
                "week": week,
                "card_id": a.get("id"),
                "title": a.get("title", ""),
                "source": a.get("source", ""),
                "orig_url": a.get("url") or a.get("link", ""),
                "rss_summary": a.get("summary_raw"),
                "card_published": norm_date(a.get("published")),
            })
    return cards


def date_match(card_pub, meta):
    if not card_pub or not meta:
        return "n/a"
    try:
        a, b = date.fromisoformat(card_pub[:10]), date.fromisoformat(meta[:10])
    except ValueError:
        return "n/a"
    diff = abs((a - b).days)
    return "exact" if diff == 0 else "±1d" if diff == 1 else "mismatch"


# ── 실행 ──────────────────────────────────────────────────────
def out_json_path():
    suffix = f"_{PROBE_TAG}" if PROBE_TAG else ""
    return OUT_DIR / f"body_probe_{datetime.now(timezone.utc).date()}{suffix}.json"


def run(fmt, inputs, limit):
    cards = load_cards(fmt, inputs)
    if limit:
        cards = cards[:limit]
    print(f"[{fmt}] 카드 {len(cards)}건, GN {sum(is_gnews(c['orig_url']) for c in cards)}건 (mincore {MINCORE_VERSION})")

    resolutions = resolve_many([c["orig_url"] for c in cards])
    rules, fetcher, ctx = load_rules(), Fetcher(), {}

    records = []
    for i, (c, r) in enumerate(zip(cards, resolutions), 1):
        rec = {k: v for k, v in c.items() if k != "rss_summary"}
        rec.update(resolve_method=r.method, resolved_url=r.url, resolve_attempts=r.attempts,
                   resolve_error=r.error if r.method == "failed" else None,
                   resolved_domain=domain_of(r.url) if r.url else None)
        if not r.url:
            rec.update(body_status="title_only", block_type="resolve_fail", primary_block="resolve_fail",
                       body_source="none", body_len=0, body_sha256=None, body_head200=None, quotes=[],
                       strategies_tried=[], http_status=None, meta_date=None, error=r.error)
        else:
            b = extract_body(r.url, fetcher, rules, title=c["title"], rss_summary=c["rss_summary"], ctx=ctx)
            rec.update(body_status=b.status, body_source=b.source, body_len=b.chars, body_sha256=b.sha256,
                       body_head200=b.text[:200] or None, quotes=b.quotes, strategies_tried=b.strategies_tried,
                       http_status=b.http_status, meta_date=b.extracted_date, error=b.error,
                       primary_block=b.block_type,
                       # 1·2단계와 비교 가능하도록: 최종 실패(300자 미만)일 때만 block_type을 남긴다
                       block_type=b.block_type if b.chars < PARTIAL_MIN else None)
        rec["date_match"] = date_match(rec["card_published"], rec["meta_date"])
        records.append(rec)
        print(f"  [{i}/{len(cards)}] {rec['body_status']:<10} {rec['body_source']:<15} "
              f"{rec['primary_block'] or '':<12} {rec['resolved_domain'] or '-'}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = out_json_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"services": {}}
    data["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    data["mincore_version"] = MINCORE_VERSION
    data["services"][fmt] = {
        "inputs": [str(p) for p in inputs],
        "limit": limit,
        "records": records,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{fmt}] 저장: {path}")



# ── 보고서 ────────────────────────────────────────────────────
STATUSES = ("full", "partial", "lead_only", "title_only")


def pct(n, d):
    return f"{n / d * 100:.1f}%" if d else "-"


def report():
    path = out_json_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    L = [f"# Body probe 보고서 ({path.stem.removeprefix('body_probe_')})", "",
         f"생성: {data['generated_at']} · 기준: full ≥{FULL_MIN}자 / partial {PARTIAL_MIN}~{FULL_MIN - 1}자 "
         f"/ lead_only 1~{PARTIAL_MIN - 1}자 / title_only 0자 · 추출: mincore {data.get('mincore_version', '-')} "
         f"(trafilatura → 도메인 대체표 → og:description → RSS 설명)", ""]

    # 1. 서비스별 요약
    L += ["## 1. 서비스별 요약", "",
          "| 서비스 | 구분 | 건수 | 주소해석 성공 | full | partial | lead_only | title_only | 확보율(full+partial) | 날짜 추출 | 날짜 일치(exact/±1d) |",
          "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    all_recs = []
    for svc, block in data["services"].items():
        recs = block["records"]
        all_recs += recs
        groups = [("전체", recs),
                  ("Google News", [r for r in recs if r["resolve_method"] != "direct"]),
                  ("직접 RSS/HTML", [r for r in recs if r["resolve_method"] == "direct"])]
        for label, g in groups:
            n = len(g)
            if not n:
                continue
            st = Counter(r["body_status"] for r in g)
            resolved = sum(r["resolve_method"] != "failed" for r in g)
            dated = [r for r in g if r["meta_date"]]
            dm = Counter(r["date_match"] for r in dated)
            L.append(f"| {svc.upper()} | {label} | {n} | {pct(resolved, n)} | "
                     + " | ".join(f"{st[s]} ({pct(st[s], n)})" for s in STATUSES)
                     + f" | **{pct(st['full'] + st['partial'], n)}** | {pct(len(dated), n)} | "
                       f"{dm['exact']}/{dm['±1d']} of {len(dated)} ({pct(dm['exact'] + dm['±1d'], len(dated))}) |")
    L.append("")
    rm = Counter((r["service"], r["resolve_method"]) for r in all_recs)
    L.append("주소 해석 방법: " + ", ".join(f"{s.upper()} {m}={n}" for (s, m), n in sorted(rm.items())))
    src = Counter((r["service"], r.get("body_source", "trafilatura")) for r in all_recs if r["body_len"])
    L.append("본문 출처: " + ", ".join(f"{s.upper()} {m}={n}" for (s, m), n in sorted(src.items())))
    rec_ = [r for r in all_recs if r.get("primary_block") and r["body_status"] in ("full", "partial")]
    L.append(f"1차 차단 후 대체 전략으로 회복: {len(rec_)}건 "
             + str(dict(Counter(r["resolved_domain"] for r in rec_))))
    L.append("")

    # 2. 차단 유형
    L += ["## 2. 실패(lead_only·title_only) 차단 유형", "",
          "| 서비스 | " + " | ".join(("resolve_fail", "timeout", "bot_block", "paywall", "http_error", "parse_fail")) + " |",
          "|---|" + "---:|" * 6]
    for svc in data["services"]:
        bt = Counter(r["block_type"] for r in all_recs if r["service"] == svc and r["block_type"])
        L.append(f"| {svc.upper()} | " + " | ".join(str(bt[k]) for k in
                 ("resolve_fail", "timeout", "bot_block", "paywall", "http_error", "parse_fail")) + " |")
    L.append("")

    # 3. 도메인별 표
    by_dom = defaultdict(list)
    for r in all_recs:
        by_dom[r["resolved_domain"] or "(주소 해석 실패)"].append(r)
    L += ["## 3. 도메인별 확보율 (건수순)", "",
          "| 도메인 | 서비스 | 건수 | full | partial | lead | title | 확보율 | 주요 차단유형 | 날짜추출 |",
          "|---|---|---:|---:|---:|---:|---:|---:|---|---:|"]
    for dom, g in sorted(by_dom.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        st = Counter(r["body_status"] for r in g)
        bt = Counter(r["block_type"] for r in g if r["block_type"]).most_common(1)
        svcs = "+".join(sorted({r["service"].upper() for r in g}))
        L.append(f"| {dom} | {svcs} | {len(g)} | {st['full']} | {st['partial']} | {st['lead_only']} | "
                 f"{st['title_only']} | {pct(st['full'] + st['partial'], len(g))} | "
                 f"{f'{bt[0][0]} ({bt[0][1]})' if bt else '-'} | {pct(sum(bool(r['meta_date']) for r in g), len(g))} |")
    L.append("")

    # 4. 실패 사례 20건 (도메인 다양성 우선)
    fails = [r for r in all_recs if r["body_status"] in ("lead_only", "title_only")]
    seen, picked = set(), []
    for r in fails:
        key = r["resolved_domain"] or r["source"]
        if key not in seen:
            seen.add(key)
            picked.append(r)
    picked += [r for r in fails if r not in picked]
    L += ["## 4. 실패 사례 20건", "",
          "| # | 서비스 | 제목 | 도메인 | HTTP | 상태 | 차단유형 | 비고 |",
          "|---:|---|---|---|---:|---|---|---|"]
    for i, r in enumerate(picked[:20], 1):
        title = r["title"].replace("|", "/")[:70]
        note = (r.get("error") or r.get("resolve_error") or "").replace("|", "/")[:60]
        L.append(f"| {i} | {r['service'].upper()} | {title} | {r['resolved_domain'] or '-'} | "
                 f"{r['http_status'] or '-'} | {r['body_status']} | {r['block_type']} | {note} |")
    L.append("")

    md = path.with_suffix(".md")
    md.write_text("\n".join(L), encoding="utf-8")
    print(f"보고서: {md}")


# ── 여러 실행 비교 (예: 1단계 로컬 / 2단계 Actions / 3a 코어 Actions) ──────
def got(r):
    return r["body_status"] in ("full", "partial")


def compare(paths, labels=None):
    labels = labels or [Path(p).stem.removeprefix("body_probe_") for p in paths]

    def load(p):
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        return [r for blk in d["services"].values() for r in blk["records"]]

    def rate(rs):
        return sum(map(got, rs)) / len(rs) * 100 if rs else 0.0

    runs = [load(p) for p in paths]
    hdr = " | ".join(labels)
    L = [f"# Body probe 비교: {' vs '.join(labels)}", ""]
    L += [f"- {lab}: `{Path(p).name}`" for lab, p in zip(labels, paths)]
    L += ["", "## 서비스별 확보율(full+partial)", "",
          f"| 서비스 | 건수 | {hdr} | 차이(마지막−첫째, %p) |", "|---|---:|" + "---:|" * (len(runs) + 1)]
    for svc in sorted({r["service"] for run in runs for r in run}) + ["전체"]:
        sub = [[r for r in run if svc == "전체" or r["service"] == svc] for run in runs]
        L.append(f"| {svc.upper() if svc != '전체' else svc} | {len(sub[0])} | "
                 + " | ".join(f"{rate(x):.1f}%" for x in sub) + f" | **{rate(sub[-1]) - rate(sub[0]):+.1f}** |")
    L.append("")

    def by_dom(recs):
        g = defaultdict(list)
        for r in recs:
            g[r["resolved_domain"] or "(주소 해석 실패)"].append(r)
        return g

    def cell(rs):
        if not rs:
            return "-"
        srcs = sorted({r.get("body_source") for r in rs if got(r) and r.get("body_source") not in (None, "trafilatura")})
        blk = sorted({r["block_type"] for r in rs if r["block_type"]})
        note = (" " + "/".join(srcs)) if srcs else ""
        note += (" ✗" + ",".join(blk)) if blk else ""
        return f"{sum(map(got, rs))}/{len(rs)}{note}"

    doms = [by_dom(run) for run in runs]
    rows = []
    for dom in set().union(*doms):
        rates = [(sum(map(got, d[dom])) / len(d[dom])) if d.get(dom) else None for d in doms]
        changed = len({x for x in rates if x is not None}) > 1
        n = max(len(d.get(dom, [])) for d in doms)
        rows.append((not changed, -n, dom, f"| {dom} | " + " | ".join(cell(d.get(dom, [])) for d in doms)
                     + f" | {'**변화**' if changed else ''} |"))
    L += ["## 도메인별 확보/건수 (변화 있는 도메인 먼저)", "",
          "셀 표기: 확보/건수, 대체 출처(amp·feed·og 등), ✗최종 차단유형", "",
          f"| 도메인 | {hdr} | |", "|---|" + "---|" * (len(runs) + 1)]
    L += [r[3] for r in sorted(rows)]
    out = Path(paths[-1]).with_name(Path(paths[-1]).stem + "_compare.md")
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"비교: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=("kcmo", "cmw"))
    ap.add_argument("--inputs", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--compare", nargs="+", metavar="PROBE_JSON", help="비교할 결과 JSON 2개 이상 (첫째가 기준)")
    ap.add_argument("--labels", nargs="+")
    a = ap.parse_args()
    if a.compare:
        if len(a.compare) < 2:
            ap.error("--compare에는 JSON이 2개 이상 필요")
        compare(a.compare, a.labels)
        return
    if a.report:
        report()
        return
    if not a.format:
        ap.error("--format 또는 --report 필요")
    inputs = [Path(p) for p in a.inputs] if a.inputs else DEFAULT_INPUTS[a.format]
    run(a.format, inputs, a.limit)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
