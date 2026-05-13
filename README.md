# korea-oda-minerals (KCMO Weekly)

한국 핵심광물 ODA 협력국 주간 동향 자동 큐레이션 시스템

## 개요

한국이 핵심광물 ODA 협력을 진행 중인 7개국(탄자니아·인도네시아·베트남·몽골·카자흐스탄·우즈베키스탄·라오스)의 정책·탐사·개발·공급망·연구 동향을 매주 자동 수집·요약·발송합니다.

- **사이트**: https://dolmudaddy.github.io/korea-oda-minerals/
- **발송 시각**: 매주 일요일 08:00 KST
- **발신**: mac@kigam.re.kr (KCMO Weekly)
- **운영자**: 조성준 박사 (KIGAM 책임연구원, 한국자원공학회 회장)

## 시스템 흐름

```
1. collect.py        → 7개국 다국어 소스 수집 (영어·스와힐리어·한국어 등)
2. summarize.py      → Claude API로 ODA 관점 한국어 요약
3. build_index.py    → 사이트 빌드 (index.html)
4. send_email.py     → Mailchimp 메일 발송
```

매주 GitHub Actions가 위 4단계를 자동 실행합니다.

## 저장소 구조

```
korea-oda-minerals/
├── .github/workflows/
│   └── weekly.yml              # GitHub Actions 자동화 워크플로우
├── scripts/
│   ├── collect.py              # 수집
│   ├── summarize.py            # Claude API 요약
│   ├── build_index.py          # 사이트 빌드
│   └── send_email.py           # Mailchimp 발송
├── data/                       # 주간 결과물 (자동 생성)
│   ├── raw_YYYY-MM-DD.json
│   └── cards_YYYY-MM-DD.json
├── sources.yaml                # 4계층 소스 정의
├── template.html               # 사이트 HTML 템플릿
├── index.html                  # 빌드 결과 (GitHub Pages가 호스팅)
└── README.md                   # 이 파일
```

## 환경 설정 (최초 1회)

### 1. GitHub Secrets 등록

저장소 Settings → Secrets and variables → Actions에 다음 5개 secret 등록:

| Name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Anthropic Console에서 발급 |
| `MAILCHIMP_API_KEY` | Mailchimp Profile → API keys |
| `MAILCHIMP_SERVER` | `us13` |
| `MAILCHIMP_AUDIENCE_ID` | KCMO Audience의 10자리 ID |
| `MAILCHIMP_REPLY_TO` | `mac@kigam.re.kr` |

### 2. GitHub Pages 활성화

저장소 Settings → Pages에서 Source를 `Deploy from a branch`로, Branch를 `main / (root)`로 설정.

### 3. Mailchimp Audience 생성

Mailchimp에서 별도 Audience "KCMO Weekly" 생성 후 박사님 본인 이메일을 구독자로 추가.

## 수동 실행 (테스트)

GitHub 저장소 페이지 → Actions 탭 → "KCMO Weekly Digest" → "Run workflow" 버튼.

`dry_run` 옵션을 `true`로 두면 메일은 보내지 않고 미리보기만 생성됩니다.

## 로컬 테스트

```bash
# 환경 변수 설정
export ANTHROPIC_API_KEY=sk-ant-api03-...
export MAILCHIMP_API_KEY=...-us13
export MAILCHIMP_SERVER=us13
export MAILCHIMP_AUDIENCE_ID=...
export MAILCHIMP_REPLY_TO=mac@kigam.re.kr
export KCMO_DRY_RUN=1  # 실제 발송 안 함

# 의존성 설치
pip install feedparser requests pyyaml anthropic beautifulsoup4 lxml

# 파이프라인 실행
python scripts/collect.py
python scripts/summarize.py
python scripts/build_index.py
python scripts/send_email.py
```

## 운영 비용 (연간 예상)

- GitHub Pages·Actions: 무료
- Anthropic API (Haiku 4.5): 약 USD 2~3/년
- Mailchimp Free Plan: 무료 (500명까지)

**합계: 약 USD 3/년**

## 자매 프로젝트

- **CMW (Critical Minerals Weekly)**: 전 세계 핵심광물 동향 (월요일 08:00 KST 발송)
  - 저장소: `dolmudaddy/critical-minerals`
  - 사이트: https://dolmudaddy.github.io/critical-minerals/

## 라이선스

저작권 © 2026 조성준 (KIGAM). 자동 큐레이션 by Claude AI (Anthropic).
