"""
리뉴얼 1단계 — Google News 본문 추출 실측 (probe 전용, 운영 파이프라인과 무관)

카드 JSON(KCMO cards_*.json / CMW week-*.json)을 읽어
  1) Google News 중계 주소 → 원매체 주소 (googlenewsdecoder 배치, 실패 시 리다이렉트 추적)
  2) 원매체 주소 → 본문 (trafilatura, favor_precision)
  3) body_status / block_type / 발행일 추출·일치 여부
를 기록한다. 공개 저장소이므로 본문 전문은 저장하지 않는다 (길이·sha256·앞 200자만).

사용:
  py scripts/probe/body_probe.py --format kcmo [--limit 5]
  py scripts/probe/body_probe.py --format cmw  [--limit 5]
  py scripts/probe/body_probe.py --report
의존성: trafilatura, googlenewsdecoder (selectolax<1.0 필요)
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
import trafilatura
from googlenewsdecoder import gnewsdecoder

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

DELAY = 0.5
TIMEOUT = 15
FULL_MIN, PARTIAL_MIN = 800, 300
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,ko;q=0.8"}

BOT_STATUS = {401, 403, 429, 503}
BOT_SIGNS = ("just a moment", "cf-browser-verification", "cf-challenge", "captcha",
             "are you a robot", "access denied", "perimeterx", "datadome",
             "enable javascript and cookies", "request unsuccessful")
PAYWALL_SIGNS = ("paywall", "subscribe to continue", "subscribers only",
                 "subscriber-only", "premium content", "to continue reading",
                 '"isaccessibleforfree":false', '"isaccessibleforfree": false',
                 '"isaccessibleforfree":"false"', '"isaccessibleforfree": "false"')


def is_gnews(url):
    return "news.google.com" in (urlparse(url).netloc or "")


def domain_of(url):
    host = (urlparse(url).netloc or "").lower()
    return host[4:] if host.startswith("www.") else host


# ── 입력 어댑터 ───────────────────────────────────────────────
def norm_date(s):
    """ISO('2026-09-15', '2026-10-11T05:10:25+00:00') 또는 RFC822('Tue, 15 Sep 2026 ...') → YYYY-MM-DD"""
    if not s:
        return None
    if re.match(r"\d{4}-\d{2}-\d{2}", s):
        return s[:10]
    try:
        return parsedate_to_datetime(s).date().isoformat()
    except (TypeError, ValueError):
        return None


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
                "card_published": norm_date(a.get("published")),
            })
    return cards


# ── 1) URL 해석 ───────────────────────────────────────────────
def resolve_all(cards):
    gn = [c for c in cards if is_gnews(c["orig_url"])]
    for c in cards:
        if not is_gnews(c["orig_url"]):
            c.update(resolve_method="direct", resolved_url=c["orig_url"])
    if not gn:
        return
    print(f"[resolve] googlenewsdecoder 배치 {len(gn)}건 (interval={DELAY}s)")
    try:
        results = gnewsdecoder([c["orig_url"] for c in gn], interval=DELAY, timeout=TIMEOUT)
    except Exception as e:  # 배치 전체 실패 → 전부 2차로
        print(f"[resolve] 배치 실패: {e}")
        results = [{"success": False, "message": str(e)}] * len(gn)
    if isinstance(results, dict):
        results = [results]
    retry = [i for i, r in enumerate(results) if not r.get("success")]
    if retry:  # SSL/타임아웃 등 일시 오류 대비 1회 재시도
        print(f"[resolve] 실패 {len(retry)}건 10초 후 재시도")
        time.sleep(10)
        for i in retry:
            try:
                results[i] = gnewsdecoder(gn[i]["orig_url"], interval=DELAY, timeout=TIMEOUT)
            except Exception as e:
                results[i] = {"success": False, "message": str(e)}
    for c, r in zip(gn, results):
        if r.get("success") and r.get("decoded_url") and not is_gnews(r["decoded_url"]):
            c.update(resolve_method="decoder", resolved_url=r["decoded_url"])
            continue
        c["resolve_error"] = r.get("message")
        url = redirect_follow(c["orig_url"])
        if url:
            c.update(resolve_method="redirect", resolved_url=url)
        else:
            c.update(resolve_method="failed", resolved_url=None)


def redirect_follow(url):
    time.sleep(DELAY)
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.url and not re.search(r"(^|\.)google\.[a-z.]+$", urlparse(r.url).netloc):
            return r.url
    except requests.RequestException:
        pass
    return None


# ── 2) 본문 fetch + 추출 ───────────────────────────────────────
def classify_block(status, html_lower, body_len, err):
    if err == "timeout":
        return "timeout"
    if err:
        return "http_error"
    if status in BOT_STATUS or (body_len < PARTIAL_MIN and any(s in html_lower[:20000] for s in BOT_SIGNS)):
        return "bot_block"
    if any(s in html_lower for s in PAYWALL_SIGNS):
        return "paywall"
    if status and status >= 400:
        return "http_error"
    return "parse_fail"


def extract(c):
    rec = dict(c)
    rec.update(resolved_domain=domain_of(c["resolved_url"]) if c.get("resolved_url") else None,
               http_status=None, body_len=0, body_sha256=None, body_head200=None,
               meta_date=None, error=None)
    if not c.get("resolved_url"):
        rec.update(body_status="title_only", block_type="resolve_fail")
        return rec

    t0 = time.time()
    html, err = "", None
    try:
        r = requests.get(c["resolved_url"], headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        rec["http_status"] = r.status_code
        html = r.text or ""
        if domain_of(r.url) != rec["resolved_domain"]:
            rec["final_url"] = r.url
    except requests.Timeout:
        err = "timeout"
    except requests.RequestException as e:
        err = type(e).__name__
        rec["error"] = str(e)[:200]

    text = ""
    if html:
        try:
            doc = trafilatura.bare_extraction(html, url=c["resolved_url"], favor_precision=True,
                                              with_metadata=True)
            if doc is not None:
                d = doc if isinstance(doc, dict) else doc.as_dict()
                text = (d.get("text") or "").strip()
                rec["meta_date"] = (d.get("date") or None)
        except Exception as e:
            rec["error"] = f"extract: {e}"[:200]
    rec["elapsed_s"] = round(time.time() - t0, 2)

    n = len(text)
    rec["body_len"] = n
    if n:
        rec["body_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        rec["body_head200"] = text[:200]
    rec["body_status"] = ("full" if n >= FULL_MIN else "partial" if n >= PARTIAL_MIN
                          else "lead_only" if n > 0 else "title_only")
    rec["block_type"] = (None if n >= PARTIAL_MIN
                         else classify_block(rec["http_status"], html.lower(), n, err))
    if err == "timeout":
        rec["error"] = "timeout"
    return rec


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
    print(f"[{fmt}] 카드 {len(cards)}건, GN {sum(is_gnews(c['orig_url']) for c in cards)}건")
    resolve_all(cards)

    records = []
    last_hit = 0.0  # 전체 순차 실행 → 도메인당 동시 1건 자동 보장
    for i, c in enumerate(cards, 1):
        if c.get("resolved_url"):
            time.sleep(max(0.0, DELAY - (time.time() - last_hit)))
        rec = extract(c)
        last_hit = time.time()
        rec["date_match"] = date_match(rec["card_published"], rec["meta_date"])
        records.append(rec)
        print(f"  [{i}/{len(cards)}] {rec['body_status']:<10} {rec['block_type'] or '':<12} "
              f"{rec['resolved_domain'] or '-'}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = out_json_path()
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"services": {}}
    data["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
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
         f"/ lead_only 1~{PARTIAL_MIN - 1}자 / title_only 0자 · 추출: trafilatura favor_precision", ""]

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


# ── 두 실행 비교 (로컬 vs Actions) ─────────────────────────────
def got(r):
    return r["body_status"] in ("full", "partial")


def compare(path_a, path_b, label_a="로컬", label_b="Actions"):
    def load(p):
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        return [r for blk in d["services"].values() for r in blk["records"]]

    def rate(rs):
        return sum(map(got, rs)) / len(rs) * 100 if rs else 0.0

    A, B = load(path_a), load(path_b)
    L = [f"# Body probe 비교: {label_a} vs {label_b}", "",
         f"- {label_a}: `{Path(path_a).name}`", f"- {label_b}: `{Path(path_b).name}`", "",
         "## 서비스별 확보율(full+partial)", "",
         f"| 서비스 | 건수 | {label_a} | {label_b} | 차이(%p) |", "|---|---:|---:|---:|---:|"]
    for svc in sorted({r["service"] for r in A + B}):
        a = [r for r in A if r["service"] == svc]
        b = [r for r in B if r["service"] == svc]
        L.append(f"| {svc.upper()} | {len(a)}/{len(b)} | {rate(a):.1f}% | {rate(b):.1f}% | {rate(b) - rate(a):+.1f} |")
    L += [f"| 전체 | {len(A)}/{len(B)} | {rate(A):.1f}% | {rate(B):.1f}% | **{rate(B) - rate(A):+.1f}** |", ""]

    def by_dom(recs):
        g = defaultdict(list)
        for r in recs:
            g[r["resolved_domain"] or "(주소 해석 실패)"].append(r)
        return g

    def blocks(rs):
        return ",".join(sorted({r["block_type"] for r in rs if r["block_type"]})) or "-"

    da, db = by_dom(A), by_dom(B)
    rows = []
    for dom in set(da) | set(db):
        a, b = da.get(dom, []), db.get(dom, [])
        ga, gb = sum(map(got, a)), sum(map(got, b))
        changed = (ga / len(a) if a else None) != (gb / len(b) if b else None)
        rows.append((not changed, -max(len(a), len(b)), dom,
                     f"| {dom} | {ga}/{len(a)} | {gb}/{len(b)} | {blocks(a)} | {blocks(b)} | "
                     f"{'**변화**' if changed else ''} |"))
    L += ["## 도메인별 (변화 있는 도메인 먼저)", "",
          f"| 도메인 | {label_a} 확보/건수 | {label_b} 확보/건수 | {label_a} 차단 | {label_b} 차단 | |",
          "|---|---:|---:|---|---|---|"]
    L += [r[3] for r in sorted(rows)]
    out = Path(path_b).with_name(Path(path_b).stem + "_compare.md")
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"비교: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--format", choices=("kcmo", "cmw"))
    ap.add_argument("--inputs", nargs="*")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--compare", nargs=2, metavar=("LOCAL_JSON", "ACTIONS_JSON"))
    a = ap.parse_args()
    if a.compare:
        compare(*a.compare)
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
