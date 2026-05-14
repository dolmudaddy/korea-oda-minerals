"""
KCMO Weekly - summarize.py
Korea Critical Minerals ODA Weekly

Reads raw_YYYY-MM-DD.json (output of collect.py), calls Claude API
to generate Korean ODA-perspective summaries, then writes cards.json.

Each card includes:
  - korean_summary: 3-line ODA-perspective Korean summary (statement style)
  - oda_relevance: 1-line Korea ODA implication (KCMO-specific field)
  - swahili_terms: list of {term, meaning} for Swahili sources
  - category: one of 5 ODA categories
  - tags: country, mineral, institution tags
"""
import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone

try:
    import anthropic
except ImportError:
    print("ERROR: install anthropic SDK: pip install anthropic")
    sys.exit(1)

# -----------------------------------------------------------------
# Config
# -----------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR
DATA_DIR = ROOT_DIR / "data"

MODEL = "claude-haiku-4-5-20251001"  # 비용 효율 우선
MAX_TOKENS = 1500
API_RETRY = 3
API_RETRY_BACKOFF = 5  # seconds

CATEGORIES = [
    "oda_cooperation",        # ODA 협력
    "policy_regulation",      # 정책·법규
    "exploration_development", # 탐사·개발
    "supply_chain_trade",     # 공급망·교역
    "research_academic",      # 연구·학술
]

CATEGORY_KO = {
    "oda_cooperation": "ODA 협력",
    "policy_regulation": "정책·법규",
    "exploration_development": "탐사·개발",
    "supply_chain_trade": "공급망·교역",
    "research_academic": "연구·학술",
}


# -----------------------------------------------------------------
# Prompt builder
# -----------------------------------------------------------------
SYSTEM_PROMPT = """당신은 한국 핵심광물 ODA 협력국 7개국(탄자니아·인도네시아·베트남·몽골·카자흐스탄·우즈베키스탄·라오스) 동향을 큐레이션하는 전문 분석가입니다.

독자는 한국지질자원연구원(KIGAM), 한국자원공학회, 외교부, 산업통상자원부(MOTIE), KIAT(한국산업기술진흥원)의 정책 결정자입니다.

## 한국 ODA 거버넌스 사실 (반드시 정확히 반영)

핵심광물 ODA의 한국측 실무 주관기관 분담은 다음과 같습니다:
- **KIAT(한국산업기술진흥원, MOTIE 산하)**: **핵심광물 ODA 실무 주관기관**. 자원개발·산업기술 협력 ODA 사업 집행
- **KIGAM(한국지질자원연구원)**: 지질·자원 기술협력 파트너. 탐사·평가·기술이전 담당
- **KOICA(한국국제협력단)**: 일반 무상원조 총괄 (※ 핵심광물 ODA의 실무 주관은 아님)
- **EDCF(대외경제협력기금, 수출입은행)**: 유상원조 자금 운영
- **MOTIE(산업통상자원부)**: 핵심광물 정책 주관 부처
- **MOFA(외교부)**: 자원외교 총괄

이전에는 KOICA가 ODA를 총괄한다는 인식이 흔했으나, 핵심광물 분야는 KIAT가 실무를 주관합니다. oda_relevance 작성 시 이 사실을 정확히 반영하세요.

## 협력국 정부 거버넌스 사실 (반드시 정확히 반영)

각 협력국의 광물 행정 주관 부처는 다음과 같습니다:
- **탄자니아**: Wizara ya Madini (광물부)
- **인도네시아**: Kementerian ESDM (에너지광물자원부)
- **베트남**: Bộ Công Thương (MOIT, 산업통상부)
- **몽골**: MRPAM (광물석유청) 및 Ministry of Mining and Heavy Industry
- **카자흐스탄**: Ministry of Industry and Construction
- **우즈베키스탄**: 광물지질부 및 Almalyk MMC, Navoi MMC 등 국영 광업기업
- **라오스**: **Ministry of Industry and Commerce (MOIC, 산업통상부)**
  - ※ 2025년 6월 16일 정부 조직개편으로 Ministry of Energy and Mines (MEM, 에너지광산부)가 MOIC에 통합됨
  - ※ Department of Geology and Minerals (DGM, 지질광업국)과 Department of Mines (DOM, 광산부)도 MOIC 산하로 이관됨
  - ※ 옛 'Ministry of Energy and Mines' 또는 'MEM'이 기사에 언급되더라도 oda_relevance에서는 현재 주관 부처인 MOIC를 정확히 명시할 것

## 응답 형식

기사 원문(영어/스와힐리어/한국어/기타 현지어)을 받아서 다음 형식의 JSON으로 응답하세요. 다른 텍스트는 포함하지 마세요.

{
  "korean_summary": [
    "첫째 줄: 무슨 일이 일어났는지 (사실 중심, 발표체 평서문, 30-50자)",
    "둘째 줄: 핵심 인물·기관·금액·일정 등 구체적 세부사항 (발표체, 30-50자)",
    "셋째 줄: 한국과의 관련성 또는 향후 전망 (발표체, 30-50자)"
  ],
  "oda_relevance": "한국 ODA 관점 시사점 한 줄 (50-100자). 핵심광물 이슈인 경우 KIAT 역할도 자연스럽게 언급",
  "category": "oda_cooperation | policy_regulation | exploration_development | supply_chain_trade | research_academic 중 하나",
  "tags": ["관련 광종·기관·지역 태그 3-5개"],
  "key_phrases": [
    {"phrase": "원문 핵심 표현 (원문 언어 그대로)", "meaning": "한국어 의미"}
  ]
}

## 작성 규칙

- korean_summary는 반드시 평서문 발표체("...임", "...했음", "...예정임")로 작성하세요. "...했다", "...했습니다" 같은 일반 종결형은 쓰지 마세요.
- oda_relevance는 박사님이 KOICA·외교부·MOTIE·KIAT 회의에서 즉시 인용할 수 있는 정책적 시사점이어야 합니다.
- oda_relevance에서 핵심광물 이슈인 경우 KIAT의 실무 주관 역할을 자연스럽게 반영하세요. 예: "KIAT의 핵심광물 ODA 사업 후보로 검토 가치 있음", "KIAT 자원개발협력 사업과 연계 가능", "KIAT-KIGAM 합동 기술협력 트랙 적합" 등.
- 단, 핵심광물과 무관한 일반 자원·정책 카드라면 KIAT를 억지로 끼워넣지 마세요. KIAT 언급이 자연스럽지 않을 때는 KIGAM·MOTIE·외교부 등 적합한 기관을 언급하세요.
- key_phrases는 원문이 스와힐리어인 경우 스와힐리어로, 영어면 영어, 한국어면 그대로. 3-5개.
- category는 5개 중 가장 적합한 하나만.
- tags는 한국어로 작성. 광종(예: 흑연·희토류), 기관(예: KIGAM·KIAT·STAMICO·ESDM·MOIT·MRPAM), 지역(예: Lindi·Sulawesi·Núi Pháo·Oyu Tolgoi)을 적절히 혼합.
- 답변은 반드시 유효한 JSON만 출력. 코드 펜스(```) 사용 금지."""


def build_user_message(article):
    """Construct the user prompt for one article."""
    parts = [
        f"## 기사 메타데이터",
        f"- 출처: {article.get('source', 'unknown')}",
        f"- 국가: {article.get('country', 'unknown')}",
        f"- 원문 언어: {article.get('source_language', 'en')}",
        f"- 발행일: {article.get('published', 'unknown')}",
        f"- URL: {article.get('url', '')}",
        "",
        f"## 기사 제목",
        article.get("title", ""),
        "",
        f"## 기사 본문/요약",
        article.get("summary_raw", "")[:2000],  # 토큰 절약
    ]
    return "\n".join(parts)


# -----------------------------------------------------------------
# API call with retry
# -----------------------------------------------------------------
def call_claude(client, article):
    """Returns parsed dict or None on failure."""
    user_msg = build_user_message(article)

    for attempt in range(API_RETRY):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_msg}],
            )
            text = response.content[0].text.strip()

            # Strip code fences just in case
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

            parsed = json.loads(text)
            return parsed
        except json.JSONDecodeError as e:
            print(f"    [WARN] JSON parse failed (attempt {attempt+1}/{API_RETRY}): {e}")
            if attempt == API_RETRY - 1:
                print(f"    [DEBUG] Raw response: {text[:500]}")
                return None
        except Exception as e:
            print(f"    [WARN] API call failed (attempt {attempt+1}/{API_RETRY}): {e}")
            if attempt < API_RETRY - 1:
                time.sleep(API_RETRY_BACKOFF * (attempt + 1))
            else:
                return None
    return None


# -----------------------------------------------------------------
# Validate AI response
# -----------------------------------------------------------------
def validate_summary(summary):
    """Basic sanity checks on AI output."""
    required = ["korean_summary", "oda_relevance", "category", "tags", "key_phrases"]
    for key in required:
        if key not in summary:
            return False, f"missing key: {key}"

    if not isinstance(summary["korean_summary"], list):
        return False, "korean_summary must be list"
    if len(summary["korean_summary"]) != 3:
        return False, f"korean_summary must have 3 lines (got {len(summary['korean_summary'])})"

    if summary["category"] not in CATEGORIES:
        return False, f"invalid category: {summary['category']}"

    if not isinstance(summary["tags"], list) or len(summary["tags"]) == 0:
        return False, "tags must be non-empty list"

    return True, "ok"


# -----------------------------------------------------------------
# Main pipeline
# -----------------------------------------------------------------
def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY environment variable not set")
        sys.exit(1)

    # Find latest raw file
    raw_files = sorted(DATA_DIR.glob("raw_*.json"))
    if not raw_files:
        print(f"ERROR: no raw_*.json found in {DATA_DIR}")
        sys.exit(1)
    raw_file = raw_files[-1]
    print(f"Reading: {raw_file}")

    with open(raw_file, encoding="utf-8") as f:
        raw_data = json.load(f)

    articles = raw_data.get("articles", [])
    if not articles:
        print("No articles to summarize.")
        # Still write an empty cards file
        write_cards(raw_file, [])
        return

    print(f"Articles to process: {len(articles)}")
    client = anthropic.Anthropic(api_key=api_key)

    cards = []
    failed = 0

    for i, article in enumerate(articles, 1):
        print(f"\n[{i}/{len(articles)}] {article.get('country')} | "
              f"score={article.get('score')} | {article.get('title', '')[:60]}")

        summary = call_claude(client, article)
        if summary is None:
            failed += 1
            continue

        ok, msg = validate_summary(summary)
        if not ok:
            print(f"    [WARN] validation failed: {msg}")
            failed += 1
            continue

        # Merge raw article fields with AI-generated fields into card
        card = {
            # From collect.py
            "id": article["id"],
            "title": article["title"],
            "url": article["url"],
            "source": article["source"],
            "source_language": article.get("source_language", "en"),
            "country": article["country"],
            "tier_weight": article.get("tier_weight", 1),
            "score": article["score"],
            "published": article.get("published", ""),

            # From Claude
            "korean_summary": summary["korean_summary"],
            "oda_relevance": summary["oda_relevance"],
            "category": summary["category"],
            "category_ko": CATEGORY_KO[summary["category"]],
            "tags": summary["tags"],
            "key_phrases": summary["key_phrases"],

            "ai_processed": True,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }
        cards.append(card)
        print(f"    [OK] category={summary['category']}, "
              f"phrases={len(summary['key_phrases'])}, tags={len(summary['tags'])}")

    write_cards(raw_file, cards, raw_data)
    print(f"\n{'='*60}")
    print(f"Total: {len(articles)}, success: {len(cards)}, failed: {failed}")
    print(f"{'='*60}")


def write_cards(raw_file, cards, raw_data=None):
    """Write cards JSON with same date suffix as raw file."""
    date_str = raw_file.stem.replace("raw_", "")
    output_file = DATA_DIR / f"cards_{date_str}.json"

    output = {
        "week_of": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_cards": len(cards),
        "articles": cards,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nWrote: {output_file}")


if __name__ == "__main__":
    main()
