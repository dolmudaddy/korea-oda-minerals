"""
리뉴얼 ⑤ 인도네시아 차단 대책 실측 (probe 전용, 운영 파이프라인과 무관)

A) RSS 후보: 피드별 항목 수·최신 발행일, KCMO 필터(국가+핵심광물) 통과 수,
   최근 항목의 본문 확보율(mincore.extract — 운영 코어와 같은 코드).
B) Jina Reader: 3a·3b에서 본문 확보 실패한 인도네시아 기사(indonesia_blocked.json)를
   https://r.jina.ai/<url> 로 받아 확보율 측정. 요청 간격 2초.

공개 저장소이므로 본문 전문은 저장하지 않는다 (길이·앞 120자만).

사용:
  py scripts/probe/indonesia_probe.py [--part A|B|AB] [--per-feed 8]
결과: data/probe/indonesia_probe_<날짜><_TAG>.{json,md}
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
import yaml

from mincore.domain_rules import load_rules
from mincore.extract import FULL_MIN, PARTIAL_MIN, extract_body
from mincore.fetch import Fetcher
from mincore.normalize import domain_of

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402  국가 판별·핵심광물 필터를 운영 코드 그대로 사용

OUT_DIR = ROOT / "data" / "probe"
TAG = os.environ.get("PROBE_TAG", "")
UA = "Mozilla/5.0 (compatible; KCMO-Weekly/1.0; +https://dolmudaddy.github.io/korea-oda-minerals/)"

# 10/18 로컬 확인(HTTP 200 + 항목 있음) 후보. sources.yaml에 없는 것만.
FEEDS = [
    ("Antara English - News", "https://en.antaranews.com/rss/news.xml", "en"),
    ("Antara - Ekonomi", "https://www.antaranews.com/rss/ekonomi.xml", "id"),
    ("Antara - Ekonomi Bisnis", "https://www.antaranews.com/rss/ekonomi-bisnis.xml", "id"),
    ("Antara - Ekonomi Finansial", "https://www.antaranews.com/rss/ekonomi-finansial.xml", "id"),
    ("Tambang.co.id", "https://www.tambang.co.id/feed/", "id"),
    ("Dunia Energi", "https://www.dunia-energi.com/feed/", "id"),
    ("Ruang Energi", "https://www.ruangenergi.com/feed/", "id"),
    ("Nikel.co.id", "https://www.nikel.co.id/feed/", "id"),
    ("Kontan Industri", "https://industri.kontan.co.id/rss", "id"),
    ("Katadata", "https://www.katadata.co.id/rss", "id"),
    ("CNBC Indonesia - News", "https://www.cnbcindonesia.com/news/rss", "id"),
]

BLOCK_MARKERS = ("just a moment", "attention required", "access denied", "verify you are human",
                 "captcha", "403 forbidden", "cf-chl", "enable javascript")


def status_of(chars):
    return "full" if chars >= FULL_MIN else "partial" if chars >= PARTIAL_MIN else "short"


def part_a(per_feed, scoring):
    rules, fetcher, ctx = load_rules(), Fetcher(), {}
    rows = []
    for name, url, lang in FEEDS:
        print(f"\n[A] {name} {url}")
        row = {"name": name, "url": url, "language": lang}
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
            row["http_status"] = r.status_code
            feed = feedparser.parse(r.content)
        except Exception as e:
            row.update(http_status=None, error=repr(e)[:200], entries=0)
            rows.append(row)
            continue
        ents = feed.entries
        row["entries"] = len(ents)
        row["newest"] = (ents[0].get("published") or ents[0].get("updated") or "")[:25] if ents else ""
        # KCMO 필터 (국가 + 핵심광물). 점수 기준은 소스 tier에 따라 달라지므로 여기선 제외.
        rel = []
        for e in ents:
            text = f"{e.get('title', '')} {e.get('summary', '')[:1000]}"
            if collect.detect_country(text) == "Indonesia" or lang == "id":
                dec, why = collect.has_critical_mineral(text, scoring)
                if dec == "PASS":
                    rel.append((e, why))
        row["mineral_pass"] = len(rel)
        row["mineral_pass_titles"] = [e.get("title", "")[:90] for e, _ in rel[:5]]
        # 본문: 광물 통과 항목 우선, 부족하면 최신 항목으로 채움
        sample = [e for e, _ in rel][:per_feed]
        for e in ents:
            if len(sample) >= per_feed:
                break
            if e not in sample:
                sample.append(e)
        bodies = []
        for e in sample:
            link = e.get("link", "")
            b = extract_body(link, fetcher, rules, title=e.get("title"),
                             rss_summary=e.get("summary"), ctx=ctx)
            bodies.append({"url": link, "status": b.status, "chars": b.chars, "source": b.source,
                           "block_type": b.block_type, "http_status": b.http_status})
            print(f"   {b.status:<10} {b.chars:>6} {b.source:<15} {b.block_type or '':<10} {link[:80]}")
        got = sum(1 for b in bodies if b["status"] in ("full", "partial"))
        row.update(sampled=len(bodies), body_got=got, bodies=bodies,
                   rss_content_chars=max((len((e.get("content") or [{}])[0].get("value", ""))
                                          for e in ents[:5]), default=0))
        rows.append(row)
    return rows


def part_b(interval=2.0):
    items = json.loads((ROOT / "scripts/probe/indonesia_blocked.json").read_text(encoding="utf-8"))["items"]
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    rows = []
    for i, it in enumerate(items, 1):
        if i > 1:
            time.sleep(interval)
        u = it["url"]
        rec = {"url": u, "domain": domain_of(u), "orig_block": it.get("block_type")}
        try:
            r = s.get("https://r.jina.ai/" + u, timeout=45)
            text = r.text or ""
            low = text[:3000].lower()
            # Jina 응답 머리말(Title:/URL Source:/Markdown Content:) 제외한 본문 길이
            body = text.split("Markdown Content:", 1)[-1].strip() if "Markdown Content:" in text else text.strip()
            blocked = any(m in low for m in BLOCK_MARKERS)
            rec.update(http_status=r.status_code, chars=len(body), blocked_marker=blocked,
                       status=("blocked" if blocked or r.status_code != 200 else status_of(len(body))),
                       head120=body[:120].replace("\n", " "))
        except Exception as e:
            rec.update(http_status=None, chars=0, status="error", error=repr(e)[:200])
        print(f"[B] {i:>2}/{len(items)} {rec['status']:<8} {rec.get('http_status')} {rec['chars']:>6} {u[:80]}")
        rows.append(rec)
    return rows


def render_md(res):
    L = [f"# 인도네시아 차단 대책 실측 — {res['generated_at'][:10]} {TAG}", ""]
    if res.get("A") is not None:
        L += ["## A. RSS 후보 (Actions IP)", "",
              "| 피드 | HTTP | 항목 | 최신 | 광물필터 통과 | 본문 확보 (표본) |", "|---|---:|---:|---|---:|---:|"]
        for r in res["A"]:
            L.append(f"| {r['name']} | {r.get('http_status')} | {r.get('entries', 0)} | {r.get('newest', '')[:16]} | "
                     f"{r.get('mineral_pass', '-')} | {r.get('body_got', 0)}/{r.get('sampled', 0)} |")
        L.append("")
    if res.get("B") is not None:
        B = res["B"]
        from collections import Counter
        c = Counter(r["status"] for r in B)
        got = c["full"] + c["partial"]
        L += ["## B. Jina Reader (r.jina.ai, 2초 간격)", "",
              f"- 대상 {len(B)}건 → **확보 {got}/{len(B)}** (full {c['full']}, partial {c['partial']}, "
              f"short {c['short']}, blocked {c['blocked']}, error {c['error']})", "",
              "| 도메인 | 시도 | 확보 |", "|---|---:|---:|"]
        by = {}
        for r in B:
            d = by.setdefault(r["domain"], [0, 0])
            d[0] += 1
            d[1] += r["status"] in ("full", "partial")
        L += [f"| {k} | {v[0]} | {v[1]} |" for k, v in sorted(by.items(), key=lambda x: -x[1][0])]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="AB")
    ap.add_argument("--per-feed", type=int, default=8)
    a = ap.parse_args()
    scoring = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["scoring"]
    res = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "tag": TAG}
    res["A"] = part_a(a.per_feed, scoring) if "A" in a.part else None
    res["B"] = part_b() if "B" in a.part else None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"indonesia_probe_{res['generated_at'][:10]}{'_' + TAG if TAG else ''}"
    (OUT_DIR / f"{stem}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    md = render_md(res)
    (OUT_DIR / f"{stem}.md").write_text(md, encoding="utf-8")
    print("\n" + md)


if __name__ == "__main__":
    main()
