# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

KCMO Weekly (Korea Critical Minerals ODA Weekly) — automated weekly digest of critical-mineral policy, exploration, supply-chain, and research news from Korea's 7 ODA partner countries.

- **운영자**: 조성준 박사 (KIGAM 책임연구원, 한국자원공학회 회장)
- **협력국 7개**: 탄자니아 · 인도네시아 · 베트남 · 몽골 · 카자흐스탄 · 우즈베키스탄 · 라오스
- **독자**: KIGAM, 한국자원공학회, MOFA, MOTIE, KIAT 정책 결정자
- **발송**: GitHub Actions, 매주 토요일 23:00 UTC = 일요일 08:00 KST, Mailchimp 서버 `us13`
- **사이트**: https://dolmudaddy.github.io/korea-oda-minerals/
- **자매 프로젝트**: `dolmudaddy/critical-minerals` (CMW) — 전 세계 핵심광물, 일요일 23:00 UTC 발송. **옵시디언 통합 작업의 참조 구현**.

### Domain facts that MUST be reflected accurately

These are baked into `summarize.py`'s system prompt and any user-facing copy must match:

- **KIAT(한국산업기술진흥원)**이 핵심광물 ODA의 **실무 주관기관**이다. KOICA가 아니다. KOICA는 일반 무상원조 총괄이며 핵심광물은 담당하지 않는다. `oda_relevance` 작성 시 이 사실을 정확히 반영하지 않으면 박사님 회의 인용 가치가 떨어진다.
- **라오스 광물 주관 부처는 MOIC** (Ministry of Industry and Commerce). 2025-06-16 정부 조직개편으로 옛 MEM(Ministry of Energy and Mines)이 MOIC에 통합됨. 기사에 'MEM' 표기가 남아 있어도 요약·시사점에는 반드시 현재 부처인 MOIC로 표기.

## Pipeline (run in this order)

```
collect.py → madini_html_collector.py → summarize.py → build_index.py → generate_obsidian.py → send_email.py
```

Each stage reads the previous stage's output from `data/`. All filenames are date-suffixed (`raw_YYYY-MM-DD.json`, `cards_YYYY-MM-DD.json`) so the pipeline is idempotent for a given UTC date — re-running overwrites that day's files.

- **collect.py** — reads `sources.yaml`, fetches Tier 1–3 RSS/HTML sources plus Tier 4 Google News broad search across all 7 countries, runs the 4-stage critical-mineral filter (see below), and writes `data/raw_YYYY-MM-DD.json`. Google News links are resolved to real publisher URLs via HEAD redirect *only after* the article passes scoring (cost optimization).
- **madini_html_collector.py** — separately scrapes Tanzania ministry (madini.go.tz) page bodies. Failures are non-fatal (`continue-on-error: true` in workflow). Replaces the older `pdf_collector.py`, which is kept in the tree but no longer wired into the workflow.
- **summarize.py** — calls Claude (`claude-haiku-4-5-20251001`) per article, expecting a strict JSON response with `korean_summary` (3 lines, 발표체), `oda_relevance`, `category`, `tags`, `key_phrases`. The system prompt encodes Korea ODA governance facts (KIAT is the critical-mineral ODA 실무 주관기관, not KOICA) and partner-country ministry mappings (notably: Laos MEM was merged into MOIC on 2025-06-16). Writes `data/cards_YYYY-MM-DD.json`.
- **build_index.py** — renders `index.html` from `template.html` using a hybrid approach: cards are pre-rendered as `<article>` blocks (SEO/no-JS) AND embedded as JSON for client-side filtering. Computes the next dispatch date from `week_of`.
- **generate_obsidian.py** — reads the latest `cards_*.json` and writes one markdown note per card plus a weekly index into the target Obsidian vault (`KCMO/articles/{YYYY}/`, `KCMO/weekly/{YYYY}/`). Wikilink vocabulary lives in `obsidian_vocab.yaml`. See "Obsidian 통합" below. Non-fatal in workflow (vault failure must not block email send).
- **send_email.py** — creates a Mailchimp campaign and sends. Set `KCMO_DRY_RUN=1` to skip the actual send and write `email_preview.html` only.

## Critical-mineral filter (the load-bearing piece)

`scoring.critical_mineral_keywords` in `sources.yaml` drives what gets through. Articles must (a) match a target country, (b) survive the 4-stage filter in `collect.py:has_critical_mineral`, and (c) score above `min_score_threshold` (currently 8).

Filter order — **first match wins**:
1. `exclusion_terms` (substring) → discard. Blocks "gold reserves", "HPV", "film", "railway tariff" type false positives.
2. `exclusion_wordbound` (word boundary regex) → discard. For short ambiguous abbreviations.
3. `core_minerals` (substring) → pass. Direct mineral mention or known mining company/site name.
4. `core_minerals_wordbound` (word boundary) → pass. For short abbrevs like REE, PGM (avoids matching "agREE", "Erdogan").
5. `domain_terms` (substring) → pass. KCMO domain vocab: 자원외교, 산업기술협력, critical mineral, supply chain.
6. No match → discard with reason logged.

When tuning, **add to `sources.yaml`, not `collect.py`**. The filter logic itself should not need changes; the v6 redesign was specifically to push tuning into the keyword dictionaries. After every change, scan the GitHub Actions log for `[PURGED-...]` lines to confirm intended behavior.

`scoring.government_citation_bonus` adds a separate +bonus (capped per-card) for articles citing Korean or partner-country government bodies. Short uppercase abbreviations (≤5 chars, e.g. `DOM`, `MOIT`) are matched with word boundaries automatically — do not add `\b` manually in YAML.

## Obsidian 통합

매주 생성된 카드를 박사님 옵시디언 vault에 마크다운 노트로 동기화한다. 카드 한 건당 노트 한 개(`KCMO/articles/{YYYY}/{date}-{country}-{slug}.md`) + 주간 인덱스(`KCMO/weekly/{YYYY}/KCMO Weekly {YYYY-Wnn}.md`).

**튜닝 원칙**: wikilink 어휘는 **`obsidian_vocab.yaml`에서만 수정**한다. `generate_obsidian.py` linkify 로직은 손대지 않는다 — `collect.py` 필터 로직을 손대지 않고 `sources.yaml`로만 튜닝하는 것과 동일한 분리 원칙이다.

`obsidian_vocab.yaml` 구조:
- 5개 카테고리(`countries` / `minerals` / `korea_institutions` / `partner_institutions` / `policy_terms`) 각각 `node` + `patterns` 목록. `node`가 wikilink 타깃(`[[node]]`), `patterns`가 본문에서 찾을 후보 표기. 같은 노드의 긴 패턴을 짧은 패턴보다 우선 매칭하기 위해 **길이 내림차순으로 자동 정렬**된다. 다중 노드가 겹칠 때는 전체에서 가장 긴 매칭이 이긴다.
- `cooperation_nodes` — `{country} {mineral}` 형태의 자동 노드(예: `[[베트남 희토류]]`). `whitelist`가 비어 있으면 `sources.yaml`의 각국 `primary_minerals`와 카드 본문/태그를 교차해 자동 생성. whitelist를 명시하면 그 목록만 사용.

**linkify 알고리즘 주의점**:
- Python `\b`가 Unicode-aware라 "KIAT의"의 T-의 경계를 word boundary로 인식 못함. 따라서 ASCII-only lookaround `(?<![A-Za-z0-9_])PATTERN(?![A-Za-z0-9_])`를 사용한다 — 한글이 뒤따라도 정상 매칭됨.
- 이미 만든 `[[wikilink]]`는 placeholder로 치환해 보호한 뒤 본문 스캔을 돌리고 마지막에 복원한다. 이중 링크 방지.
- 긴 패턴 우선이라 "광물 ODA"(6자)가 "핵심광물"(4자)보다 먼저 매칭되는 문제는 `광물 ODA` 노드의 patterns에 `핵심광물 ODA`를 추가해 더 긴 표기로 흡수했다. 동일 유형 단편화가 또 생기면 같은 방식으로 패턴 추가.

**워크플로우 연동**: 매주 GitHub Actions에서 KCMO repo가 옵시디언 vault repo를 별도로 checkout → `generate_obsidian.py --vault ./vault-checkout` 실행 → vault repo에 commit/push. 모든 단계 `continue-on-error: true`로 vault 실패가 메일 발송을 막지 않게 한다. Vault repo URL과 `OBSIDIAN_VAULT_PAT` secret은 박사님이 KCMO repo Settings → Secrets에 등록. (워크플로우 미연동 상태 — 박사님 vault 준비 후 적용 예정.)

로컬 테스트:
```powershell
python scripts/generate_obsidian.py --vault C:/path/to/vault --cards data/cards_YYYY-MM-DD.json
# --dry-run 으로 파일 출력 없이 카운트만 확인 가능
```

## Common commands

Local end-to-end run (Bash example from README; on Windows PowerShell use `$env:NAME = "..."`):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export MAILCHIMP_API_KEY=...
export MAILCHIMP_SERVER=us13
export MAILCHIMP_AUDIENCE_ID=...
export MAILCHIMP_REPLY_TO=mac@kigam.re.kr
export KCMO_DRY_RUN=1   # skip actual send

pip install feedparser requests pyyaml anthropic beautifulsoup4 lxml
python scripts/collect.py
python scripts/summarize.py
python scripts/build_index.py
python scripts/send_email.py     # dry-run writes email_preview.html
```

Run a single stage against an existing date: each script picks the *latest* matching file in `data/` automatically (`raw_*.json` for summarize, `cards_*.json` for build/send). To re-run only summarize+build for an old date, delete newer dated files or temporarily rename them.

Manual GitHub Actions trigger: Repo → Actions → "KCMO Weekly Digest" → Run workflow → set `dry_run: true` to skip Mailchimp send.

There are no tests, linters, or build steps beyond the pipeline scripts themselves.

## Editing notes

- `collect.py` purposely runs the country filter *first* and the critical-mineral filter *second* — both are mandatory drops. Don't reorder without understanding the cost (mineral check is more expensive than country check).
- The Google News path uses one HEAD request per qualified article to resolve real URLs. Workflow timeout is 15 min; if you add sources, check that summarize.py (which is the slowest stage, one Claude call per card) still fits.
- `summarize.py` retries JSON parse failures up to `API_RETRY=3`. The system prompt requires raw JSON with no code fences — the parser strips fences defensively but don't rely on that.
- `build_index.py` substitutes `{{PLACEHOLDERS}}` in `template.html` via plain string replace — no templating engine. `{{CARDS_DATA}}` injects the full cards JSON for client-side filtering.
- `data/processed_pages.json` and `data/processed_pdfs.json` are dedup registries written by the Tanzania collectors; do not delete unless intentionally re-processing.
- All dates in code/logs are UTC; KST is only used for display in `build_index.py` and `send_email.py`.

## Current status (2026-05-15)

- **점수 시스템 v6.2**: 키워드 사전 확장 적용 완료 (`sources.yaml` 및 `collect.py` 반영). 추가 튜닝은 `sources.yaml`의 키워드 사전에서 진행하고 `collect.py` 필터 로직은 손대지 않는다.
- **옵시디언 통합 (스크립트 단계 완료, 워크플로우 연동 대기)**: `generate_obsidian.py` + `obsidian_vocab.yaml` 로컬 검증 완료(21 카드 → 21 노트 + 주간 인덱스 정상). 다음은 `.github/workflows/weekly.yml`에 vault checkout → generate → commit/push 3단계 추가. 박사님이 vault repo URL과 `OBSIDIAN_VAULT_PAT` secret을 등록한 후 적용 예정.
