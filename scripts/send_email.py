"""
KCMO Weekly - send_email.py
Korea Critical Minerals ODA Weekly

Reads cards_YYYY-MM-DD.json and sends a campaign via Mailchimp.
Pattern: create campaign → set HTML content → send immediately.

Environment variables required:
  MAILCHIMP_API_KEY     - Marketing API key
  MAILCHIMP_SERVER      - Server prefix (e.g. 'us13')
  MAILCHIMP_AUDIENCE_ID - Target Audience (List) ID for KCMO
  MAILCHIMP_FROM_NAME   - Display name (default: "KCMO Weekly")
  MAILCHIMP_REPLY_TO    - Reply-to email (default: mac@kigam.re.kr)

Optional:
  KCMO_SITE_URL         - Web link in footer (default: GitHub Pages URL)
  KCMO_DRY_RUN          - If "1", build HTML but skip send/Mailchimp calls
"""
import os
import sys
import json
import html
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

# -----------------------------------------------------------------
# Config
# -----------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
ROOT_DIR = SCRIPT_DIR.parent if SCRIPT_DIR.name == "scripts" else SCRIPT_DIR
DATA_DIR = ROOT_DIR / "data"
PREVIEW_FILE = ROOT_DIR / "email_preview.html"

KST = ZoneInfo("Asia/Seoul")
SITE_URL_DEFAULT = "https://dolmudaddy.github.io/korea-oda-minerals/"

COUNTRY_KO = {
    "Tanzania": "탄자니아", "Indonesia": "인도네시아", "Vietnam": "베트남",
    "Mongolia": "몽골", "Kazakhstan": "카자흐스탄",
    "Uzbekistan": "우즈베키스탄", "Laos": "라오스",
}

CATEGORY_KO = {
    "oda_cooperation": "ODA 협력",
    "policy_regulation": "정책·법규",
    "exploration_development": "탐사·개발",
    "supply_chain_trade": "공급망·교역",
    "research_academic": "연구·학술",
}

LANGUAGE_KO = {
    "sw": "sw 원문", "ko": "ko 원문", "en": "en 원문",
    "id": "id 원문", "vi": "vi 원문", "mn": "mn 원문",
}


# -----------------------------------------------------------------
# HTML rendering (email-safe inline styles)
# -----------------------------------------------------------------
def esc(s):
    return html.escape(str(s)) if s is not None else ""


def render_card_email(card):
    country_ko = COUNTRY_KO.get(card["country"], card["country"])
    category_ko = card.get("category_ko") or CATEGORY_KO.get(card.get("category"), "")
    lang_badge = LANGUAGE_KO.get(card.get("source_language", "en"), "원문")
    tags = card.get("tags", [])
    prominent_tags = tags[:2]

    # Tag chips
    tag_chips = "".join(
        f'<span style="background: #f5f5f0; color: #666; font-size: 10px; '
        f'padding: 2px 8px; border-radius: 5px;">{esc(t)}</span>'
        for t in prominent_tags
    )

    # Summary
    summary_html = "".join(
        f'<p style="margin: 0 0 3px 0; font-size: 12px; line-height: 1.55;">{esc(line)}</p>'
        for line in card.get("korean_summary", [])
    )

    # ODA relevance
    relevance_html = ""
    if card.get("oda_relevance"):
        relevance_html = f'''
<table cellpadding="0" cellspacing="0" border="0" width="100%" style="margin: 0 0 10px 0;">
  <tr><td style="background: #fafaf7; border-radius: 6px; padding: 7px 11px;">
    <div style="font-size: 9px; color: #666; letter-spacing: 0.3px; margin-bottom: 2px;">한국 ODA 시사점</div>
    <p style="margin: 0; font-size: 11.5px; line-height: 1.5;">{esc(card["oda_relevance"])}</p>
  </td></tr>
</table>'''

    # Key phrases - EXPANDED by default in email
    phrases_html = ""
    key_phrases = card.get("key_phrases", [])
    if key_phrases:
        rows = "".join(
            f'<tr><td style="padding: 3px 0; border-bottom: 1px solid #eee; font-family: Georgia, serif;">{esc(p.get("phrase", ""))}</td>'
            f'<td style="padding: 3px 0; border-bottom: 1px solid #eee; text-align: right; color: #666;">{esc(p.get("meaning", ""))}</td></tr>'
            for p in key_phrases
        )
        # remove bottom border from last row
        rows_clean = rows.replace('border-bottom: 1px solid #eee;', '', rows.count('border-bottom: 1px solid #eee;') - 2)
        phrases_html = f'''
<div style="margin-top: 8px;">
  <div style="font-size: 10px; color: #666; margin-bottom: 4px;">원문 핵심 표현</div>
  <table cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse: collapse; font-size: 11px;">
    {rows}
  </table>
</div>'''

    return f'''
<article style="border-top: 1px solid #eee; padding-top: 14px; padding-bottom: 14px;">
  <div style="margin-bottom: 8px; line-height: 1.8;">
    <span style="background: #EAF3DE; color: #173404; font-size: 10px; padding: 2px 8px; border-radius: 5px; font-weight: 500;">{esc(country_ko)}</span>
    <span style="background: #E1F5EE; color: #04342C; font-size: 10px; padding: 2px 8px; border-radius: 5px; font-weight: 500;">{esc(category_ko)}</span>
    {tag_chips}
    <span style="background: #FAEEDA; color: #412402; font-size: 9px; padding: 2px 7px; border-radius: 5px; font-weight: 500; float: right;">{esc(lang_badge)}</span>
  </div>
  <h3 style="font-size: 14px; font-weight: 500; margin: 0 0 6px 0; line-height: 1.4;">
    <a href="{esc(card.get("url", "#"))}" style="color: #222; text-decoration: none;">{esc(card.get("title", ""))}</a>
  </h3>
  <div style="font-size: 10px; color: #666; margin-bottom: 10px;">{esc(card.get("source", ""))} · {esc(card.get("published", ""))}</div>
  <div style="border-left: 2px solid #2d5016; padding: 2px 0 2px 10px; margin: 0 0 10px 0;">
    {summary_html}
  </div>
  {relevance_html}
  {phrases_html}
</article>'''


def build_email_html(data, site_url):
    cards = data.get("articles", [])
    week_of = data.get("week_of", "")
    total = len(cards)

    # Category breakdown for header
    cat_counts = {}
    for c in cards:
        cn = c.get("category_ko") or CATEGORY_KO.get(c.get("category"), "기타")
        cat_counts[cn] = cat_counts.get(cn, 0) + 1
    cat_summary = " · ".join(f"{n} {cnt}건" for n, cnt in cat_counts.items())

    cards_html = "".join(render_card_email(c) for c in cards)

    return f'''<!doctype html>
<html><head><meta charset="utf-8">
<title>KCMO Weekly {esc(week_of)}</title>
</head>
<body style="margin: 0; padding: 0; background: #efeeea; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;">

<table cellpadding="0" cellspacing="0" border="0" width="100%" style="background: #efeeea; padding: 20px 0;">
  <tr><td align="center">

    <table cellpadding="0" cellspacing="0" border="0" width="600" style="max-width: 600px; background: #fff; border: 1px solid #ddd;">

      <tr><td style="background: #2d5016; color: #EAF3DE; padding: 1.5rem 1.5rem 1.3rem;">
        <div style="font-size: 10px; letter-spacing: 1.5px; opacity: 0.75; margin-bottom: 5px;">KCMO WEEKLY</div>
        <h1 style="font-size: 19px; font-weight: 500; margin: 0; color: #EAF3DE; line-height: 1.3;">한국 핵심광물 ODA 협력국 주간 동향</h1>
        <div style="font-size: 11px; opacity: 0.85; margin-top: 7px;">{esc(week_of)} 발행 · {total}건의 동향</div>
      </td></tr>

      <tr><td style="padding: 14px 1.5rem 0; font-size: 11px; color: #666;">
        이번 주 카테고리: {esc(cat_summary)}
      </td></tr>

      <tr><td style="padding: 12px 1.5rem 1rem;">
        {cards_html}
      </td></tr>

      <tr><td style="background: #fafaf7; border-top: 1px solid #ddd; padding: 14px 1.5rem; text-align: center; font-size: 10px; color: #666;">
        <a href="{esc(site_url)}" style="color: #2d5016; text-decoration: none; font-weight: 500;">웹사이트에서 전체 동향 보기 →</a>
        <div style="margin-top: 8px; color: #999;">한국지질자원연구원(KIGAM) · 한국자원공학회 · 자동 큐레이션 by Claude AI (Anthropic)</div>
        <div style="margin-top: 6px; color: #999; font-size: 9px;">구독 해지: *|UNSUB|*</div>
      </td></tr>

    </table>

  </td></tr>
</table>

</body></html>'''


def build_plain_text(data):
    """Plain-text fallback for clients that block HTML."""
    cards = data.get("articles", [])
    week_of = data.get("week_of", "")
    lines = [
        "한국 핵심광물 ODA 협력국 주간 동향",
        f"{week_of} 발행 · {len(cards)}건",
        "=" * 50,
        "",
    ]
    for i, c in enumerate(cards, 1):
        country = COUNTRY_KO.get(c["country"], c["country"])
        category = c.get("category_ko") or CATEGORY_KO.get(c.get("category"), "")
        lines.append(f"[{i}] [{country} · {category}] {c.get('title', '')}")
        lines.append(f"    출처: {c.get('source', '')} ({c.get('published', '')})")
        for sum_line in c.get("korean_summary", []):
            lines.append(f"    • {sum_line}")
        if c.get("oda_relevance"):
            lines.append(f"    [ODA 시사점] {c['oda_relevance']}")
        lines.append(f"    원문: {c.get('url', '')}")
        lines.append("")
    lines.append("=" * 50)
    lines.append("웹사이트: https://dolmudaddy.github.io/korea-oda-minerals/")
    lines.append("자동 큐레이션 by Claude AI (Anthropic)")
    return "\n".join(lines)


# -----------------------------------------------------------------
# Mailchimp API
# -----------------------------------------------------------------
class MailchimpClient:
    def __init__(self, api_key, server):
        self.api_key = api_key
        self.base = f"https://{server}.api.mailchimp.com/3.0"
        self.auth = ("anystring", api_key)

    def create_campaign(self, audience_id, subject, from_name, reply_to):
        url = f"{self.base}/campaigns"
        payload = {
            "type": "regular",
            "recipients": {"list_id": audience_id},
            "settings": {
                "subject_line": subject,
                "title": subject,
                "from_name": from_name,
                "reply_to": reply_to,
                "auto_footer": False,
                "inline_css": True,
            },
        }
        r = requests.post(url, json=payload, auth=self.auth, timeout=30)
        r.raise_for_status()
        return r.json()["id"]

    def set_content(self, campaign_id, html_body, plain_text):
        url = f"{self.base}/campaigns/{campaign_id}/content"
        payload = {"html": html_body, "plain_text": plain_text}
        r = requests.put(url, json=payload, auth=self.auth, timeout=60)
        r.raise_for_status()
        return r.json()

    def send_campaign(self, campaign_id):
        url = f"{self.base}/campaigns/{campaign_id}/actions/send"
        r = requests.post(url, auth=self.auth, timeout=30)
        r.raise_for_status()
        return True


# -----------------------------------------------------------------
# Subject line builder
# -----------------------------------------------------------------
def build_subject(data):
    cards = data.get("articles", [])
    week_of = data.get("week_of", "")
    total = len(cards)

    if total == 0:
        return f"한국 핵심광물 ODA 주간 | {week_of} (이번 주 동향 없음)"

    # Top 2 countries by card count
    cnt = {}
    for c in cards:
        cn = COUNTRY_KO.get(c.get("country"), c.get("country", ""))
        cnt[cn] = cnt.get(cn, 0) + 1
    top = sorted(cnt.items(), key=lambda x: -x[1])

    if len(top) == 1:
        country_phrase = top[0][0]
    elif len(top) == 2:
        country_phrase = f"{top[0][0]}·{top[1][0]}"
    else:
        country_phrase = f"{top[0][0]}·{top[1][0]} 외"

    remaining = total - (top[0][1] + (top[1][1] if len(top) > 1 else 0))
    if len(top) > 2 and remaining > 0:
        return f"한국 핵심광물 ODA 주간 | {week_of} ({country_phrase} {remaining}건)"
    return f"한국 핵심광물 ODA 주간 | {week_of} ({country_phrase} {total}건)"


# -----------------------------------------------------------------
# Main
# -----------------------------------------------------------------
def main():
    # Find latest cards file
    cards_files = sorted(DATA_DIR.glob("cards_*.json"))
    if not cards_files:
        print(f"ERROR: no cards_*.json in {DATA_DIR}")
        sys.exit(1)
    cards_file = cards_files[-1]

    with open(cards_file, encoding="utf-8") as f:
        data = json.load(f)

    cards = data.get("articles", [])
    if not cards:
        print("No cards to send. Skipping email.")
        return

    site_url = os.environ.get("KCMO_SITE_URL", SITE_URL_DEFAULT)
    html_body = build_email_html(data, site_url)
    plain = build_plain_text(data)
    subject = build_subject(data)

    # Always save preview file (useful for debugging)
    PREVIEW_FILE.write_text(html_body, encoding="utf-8")
    print(f"Email preview saved: {PREVIEW_FILE}")
    print(f"Subject: {subject}")
    print(f"Cards: {len(cards)}")

    # Dry run mode
    if os.environ.get("KCMO_DRY_RUN") == "1":
        print("\n[DRY RUN] Skipping Mailchimp API calls.")
        return

    # Validate env
    api_key = os.environ.get("MAILCHIMP_API_KEY")
    server = os.environ.get("MAILCHIMP_SERVER", "us13")
    audience_id = os.environ.get("MAILCHIMP_AUDIENCE_ID")
    from_name = os.environ.get("MAILCHIMP_FROM_NAME", "KCMO Weekly")
    reply_to = os.environ.get("MAILCHIMP_REPLY_TO", "mac@kigam.re.kr")

    missing = [n for n, v in [("MAILCHIMP_API_KEY", api_key),
                              ("MAILCHIMP_AUDIENCE_ID", audience_id)] if not v]
    if missing:
        print(f"ERROR: missing env vars: {', '.join(missing)}")
        sys.exit(1)

    client = MailchimpClient(api_key, server)

    print(f"\nCreating campaign on {server}.api.mailchimp.com...")
    campaign_id = client.create_campaign(audience_id, subject, from_name, reply_to)
    print(f"Campaign created: {campaign_id}")

    print("Uploading HTML content...")
    client.set_content(campaign_id, html_body, plain)
    print("Content uploaded.")

    print("Sending campaign...")
    client.send_campaign(campaign_id)
    print("Campaign sent successfully.")


if __name__ == "__main__":
    main()
