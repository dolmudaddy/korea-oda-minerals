"""
debug_madini.py - 진단용 일회성 스크립트

목적: madini.go.tz가 GitHub Actions IP에서 요청 시 어떤 응답을 주는지
       직접 확인. /page/{uuid}/ URL이 응답 HTML에 있는지 검증.

실행 후 GitHub Actions 로그를 박사님이 캡처해서 분석에 활용.
"""
import re
import sys
import requests


URLS_TO_TEST = [
    "https://www.madini.go.tz/",
    "https://www.madini.go.tz/otherpage/?p=press-release",
    "https://www.madini.go.tz/otherpage/?p=latest-news",
]

# 일반 브라우저처럼 보이는 헤더
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

PAGE_URL_PATTERN = re.compile(
    r"/page/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/?",
    re.IGNORECASE,
)

PAGE_HREF_PATTERN = re.compile(
    r'href=["\']([^"\']*page/[0-9a-f-]{36}[^"\']*)["\']',
    re.IGNORECASE,
)


def diagnose_url(url):
    print(f"\n{'=' * 70}")
    print(f"URL: {url}")
    print(f"{'=' * 70}")

    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=60)
        print(f"Status: {r.status_code}")
        print(f"Content-Type: {r.headers.get('Content-Type', 'N/A')}")
        print(f"Server: {r.headers.get('Server', 'N/A')}")
        print(f"Body size: {len(r.content):,} bytes")
        print(f"Body length (text): {len(r.text):,} chars")

        # 응답 HTML 일부 출력
        text = r.text
        print(f"\n--- First 500 chars of response ---")
        print(text[:500])
        print(f"--- (truncated) ---\n")

        # /page/{uuid}/ 패턴 매칭
        all_matches = PAGE_URL_PATTERN.findall(text)
        href_matches = PAGE_HREF_PATTERN.findall(text)
        unique_paths = set(all_matches)

        print(f"\n[Pattern matching results]")
        print(f"  Bare /page/.../ pattern: {len(all_matches)} matches")
        print(f"  Unique paths: {len(unique_paths)}")
        print(f"  href='...page/...' pattern: {len(href_matches)} matches")

        if unique_paths:
            print(f"\n[Found page URLs (first 5)]")
            for p in sorted(unique_paths)[:5]:
                print(f"  {p}")

        # 본문 페이지 URL 후보가 있는지 빠른 검색
        keywords = ["Latest News", "Press Release", "Taarifa", "page/"]
        print(f"\n[Keyword presence check]")
        for kw in keywords:
            count = text.count(kw)
            print(f"  '{kw}': {count} occurrences")

        # JavaScript 렌더링 의심 신호
        js_indicators = ["<script", "vue", "react", "angular", "data-react", "data-vue",
                         "__NUXT__", "__INITIAL_STATE__"]
        print(f"\n[JS rendering signals]")
        for sig in js_indicators:
            if sig.lower() in text.lower():
                print(f"  FOUND: {sig}")

    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")


def main():
    print("=" * 70)
    print("madini.go.tz Diagnostic Probe")
    print("Purpose: figure out why GitHub Actions sees no /page/{uuid}/ URLs")
    print("=" * 70)

    for url in URLS_TO_TEST:
        diagnose_url(url)

    print(f"\n{'=' * 70}")
    print("Diagnostic complete. Share this log to determine next step.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
