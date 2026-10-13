# Body probe 보고서 (2026-10-13)

생성: 2026-10-13T10:08:38+00:00 · 기준: full ≥800자 / partial 300~799자 / lead_only 1~299자 / title_only 0자 · 추출: trafilatura favor_precision

## 1. 서비스별 요약

| 서비스 | 구분 | 건수 | 주소해석 성공 | full | partial | lead_only | title_only | 확보율(full+partial) | 날짜 추출 | 날짜 일치(exact/±1d) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| KCMO | 전체 | 215 | 100.0% | 192 (89.3%) | 4 (1.9%) | 5 (2.3%) | 14 (6.5%) | **91.2%** | 93.5% | 166/12 of 201 (88.6%) |
| KCMO | Google News | 182 | 100.0% | 159 (87.4%) | 4 (2.2%) | 5 (2.7%) | 14 (7.7%) | **89.6%** | 92.3% | 145/11 of 168 (92.9%) |
| KCMO | 직접 RSS/HTML | 33 | 100.0% | 33 (100.0%) | 0 (0.0%) | 0 (0.0%) | 0 (0.0%) | **100.0%** | 100.0% | 21/1 of 33 (66.7%) |
| CMW | 전체 | 48 | 100.0% | 19 (39.6%) | 4 (8.3%) | 11 (22.9%) | 14 (29.2%) | **47.9%** | 64.6% | 17/2 of 31 (61.3%) |
| CMW | Google News | 31 | 100.0% | 6 (19.4%) | 4 (12.9%) | 11 (35.5%) | 10 (32.3%) | **32.3%** | 58.1% | 6/2 of 18 (44.4%) |
| CMW | 직접 RSS/HTML | 17 | 100.0% | 13 (76.5%) | 0 (0.0%) | 0 (0.0%) | 4 (23.5%) | **76.5%** | 76.5% | 11/0 of 13 (84.6%) |

주소 해석 방법: CMW decoder=31, CMW direct=17, KCMO decoder=182, KCMO direct=33

## 2. 실패(lead_only·title_only) 차단 유형

| 서비스 | resolve_fail | timeout | bot_block | paywall | http_error | parse_fail |
|---|---:|---:|---:|---:|---:|---:|
| KCMO | 0 | 1 | 9 | 0 | 6 | 3 |
| CMW | 0 | 1 | 3 | 0 | 2 | 19 |

## 3. 도메인별 확보율 (건수순)

| 도메인 | 서비스 | 건수 | full | partial | lead | title | 확보율 | 주요 차단유형 | 날짜추출 |
|---|---|---:|---:|---:|---:|---:|---:|---|---:|
| mining.com | CMW+KCMO | 18 | 18 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| qazinform.com | KCMO | 12 | 12 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| mongolianminingjournal.com | KCMO | 11 | 11 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| nikel.co.id | KCMO | 11 | 11 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| cnbcindonesia.com | KCMO | 8 | 5 | 3 | 0 | 0 | 100.0% | - | 100.0% |
| fastmarkets.com | CMW | 8 | 0 | 0 | 0 | 8 | 0.0% | parse_fail (7) | 0.0% |
| finance.biggo.com | KCMO | 8 | 8 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| projectblue.com | CMW | 8 | 0 | 0 | 7 | 1 | 0.0% | parse_fail (7) | 87.5% |
| gazeta.uz | KCMO | 6 | 6 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| vietnam.vn | KCMO | 5 | 5 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| vietnamnet.vn | KCMO | 5 | 5 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| aa.com.tr | KCMO | 4 | 4 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| asiae.co.kr | KCMO | 4 | 4 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| dailynews.co.tz | KCMO | 4 | 3 | 0 | 0 | 1 | 75.0% | http_error (1) | 75.0% |
| ec.europa.eu | CMW | 4 | 0 | 0 | 0 | 4 | 0.0% | parse_fail (4) | 0.0% |
| en.sedaily.com | KCMO | 4 | 4 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| koreajoongangdaily.com | KCMO | 4 | 4 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| koreatimes.co.kr | KCMO | 4 | 1 | 0 | 0 | 3 | 25.0% | http_error (3) | 25.0% |
| open.kg | KCMO | 4 | 4 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| rareearthexchanges.com | CMW+KCMO | 4 | 2 | 2 | 0 | 0 | 100.0% | - | 100.0% |
| spot.uz | KCMO | 4 | 4 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| suaradewata.com | KCMO | 4 | 4 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| baodautu.vn | KCMO | 3 | 3 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| biz.chosun.com | KCMO | 3 | 3 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| cnnindonesia.com | KCMO | 3 | 3 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| daryo.uz | KCMO | 3 | 3 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| english.hani.co.kr | KCMO | 3 | 3 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| habarileo.co.tz | KCMO | 3 | 3 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| kt.kz | KCMO | 3 | 3 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| listrikindonesia.com | KCMO | 3 | 3 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| news.sbs.co.kr | KCMO | 3 | 3 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| reuters.com | CMW+KCMO | 3 | 0 | 0 | 3 | 0 | 0.0% | bot_block (3) | 100.0% |
| tapchicongthuong.vn | KCMO | 3 | 3 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| alphabiz.co.kr | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| caspianpost.com | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| dunia-energi.com | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| en.antaranews.com | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| en.yna.co.kr | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| ibtimes.sg | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| informasi.com | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| internazionale.it | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| kz.kursiv.media | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| lestari.kompas.com | KCMO | 2 | 1 | 0 | 1 | 0 | 50.0% | parse_fail (1) | 100.0% |
| minews.id | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| miningweekly.com | CMW | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| nasional.kontan.co.id | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| news.jkn.co.kr | KCMO | 2 | 0 | 0 | 0 | 2 | 0.0% | parse_fail (2) | 0.0% |
| nguoiquansat.vn | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| rmol.id | KCMO | 2 | 0 | 0 | 0 | 2 | 0.0% | bot_block (2) | 0.0% |
| timesindonesia.co.id | KCMO | 2 | 1 | 0 | 0 | 1 | 50.0% | http_error (1) | 50.0% |
| trend.az | KCMO | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| usgs.gov | CMW | 2 | 2 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| africanminingmarket.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| amp.suara.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| antaranews.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| apply.deloitte.com | CMW | 1 | 0 | 0 | 1 | 0 | 0.0% | parse_fail (1) | 100.0% |
| babelpos.disway.id | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| careers.spglobal.com | CMW | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| ekonomi.republika.co.id | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| en.vietnamplus.vn | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| epaper.mediaindonesia.com | KCMO | 1 | 0 | 1 | 0 | 0 | 100.0% | - | 100.0% |
| finance.yahoo.com | KCMO | 1 | 0 | 0 | 0 | 1 | 0.0% | timeout (1) | 0.0% |
| happyvietnam.vnanet.vn | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| iea.org | CMW | 1 | 0 | 0 | 0 | 1 | 0.0% | bot_block (1) | 0.0% |
| indexbox.io | CMW | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| indonesia.hallo.id | KCMO | 1 | 0 | 0 | 0 | 1 | 0.0% | bot_block (1) | 0.0% |
| investortrust.id | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| jpnn.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| kabarhalmahera.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| kabartimur.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| kalkine.com.au | CMW | 1 | 0 | 1 | 0 | 0 | 100.0% | - | 0.0% |
| kalkinemedia.com | CMW | 1 | 0 | 1 | 0 | 0 | 100.0% | - | 0.0% |
| kompasiana.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| koran-jakarta.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| koreapost.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| m.ajupress.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| manufacturingtodayindia.com | CMW | 1 | 0 | 0 | 1 | 0 | 0.0% | bot_block (1) | 100.0% |
| montsame.mn | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| nationalbusiness.kz | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| news.mongabay.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| politikindonesia.id | KCMO | 1 | 0 | 0 | 0 | 1 | 0.0% | bot_block (1) | 0.0% |
| rmolsumsel.id | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| rri.co.id | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| setkab.go.id | KCMO | 1 | 0 | 0 | 0 | 1 | 0.0% | http_error (1) | 0.0% |
| sinarindonesia.id | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| sonora.co.id | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| streamlinefeed.co.ke | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| streetwisereports.com | CMW | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| suaralandak.co.id | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| surabaya.inews.id | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| theinvestor.vn | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| thejakartapost.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| tv.kontan.co.id | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| uk.finance.yahoo.com | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| upi.com | KCMO | 1 | 0 | 0 | 0 | 1 | 0.0% | bot_block (1) | 0.0% |
| usatoday.com | CMW | 1 | 0 | 0 | 1 | 0 | 0.0% | http_error (1) | 0.0% |
| vnexpress.net | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| voi.id | KCMO | 1 | 1 | 0 | 0 | 0 | 100.0% | - | 100.0% |
| wncy.com | KCMO | 1 | 0 | 0 | 1 | 0 | 0.0% | bot_block (1) | 100.0% |
| wsau.com | KCMO | 1 | 0 | 0 | 1 | 0 | 0.0% | bot_block (1) | 100.0% |

## 4. 실패 사례 20건

| # | 서비스 | 제목 | 도메인 | HTTP | 상태 | 차단유형 | 비고 |
|---:|---|---|---|---:|---|---|---|
| 1 | KCMO | South Korea, Kazakhstan sign MoU on atomic energy, explore mineral tra | wsau.com | 403 | lead_only | bot_block |  |
| 2 | KCMO | Tanzania lures Korean investments in energy, infrastructure, logistics | dailynews.co.tz | 500 | title_only | http_error |  |
| 3 | KCMO | Korea, Uzbekistan agree on cooperation in critical mineral supply chai | koreatimes.co.kr | - | title_only | http_error | HTTPSConnectionPool(host='www.koreatimes.co.kr', port=443):  |
| 4 | KCMO | South Korea, Uzbekistan Forge 'Future' Alliance with 13 Landmark Deals | news.jkn.co.kr | 200 | title_only | parse_fail |  |
| 5 | KCMO | China-Mongolia mineral ties pose risk to South Korea diversification - | upi.com | 403 | title_only | bot_block |  |
| 6 | KCMO | Amigo Resources, STAMICO sign MoU for graphite project in Tanzania - Y | finance.yahoo.com | - | title_only | timeout | timeout |
| 7 | KCMO | South Korea, Kazakhstan sign MoU on atomic energy, explore mineral tra | wncy.com | 403 | lead_only | bot_block |  |
| 8 | KCMO | South Korea, Kazakhstan sign MoU on atomic energy, explore mineral tra | reuters.com | 401 | lead_only | bot_block |  |
| 9 | KCMO | Foto : Nikel, Kekuatan Besar, dan Tanggung Jawab di Balik Hilirisasi I | lestari.kompas.com | 200 | lead_only | parse_fail |  |
| 10 | KCMO | Kinerja Satgas Hilirisasi Berbuah Manis, Indonesia Kuasai 41 Persen Ni | rmol.id | 403 | title_only | bot_block |  |
| 11 | KCMO | Indonesia Bidik Industri AI Global, Hilirisasi Nikel dan Tembaga Jadi  | indonesia.hallo.id | 403 | title_only | bot_block |  |
| 12 | KCMO | Wamenkomdigi: Hilirisasi Mineral Bisa Jadi Modal Industri AI - TIMES I | timesindonesia.co.id | - | title_only | http_error | HTTPSConnectionPool(host='timesindonesia.co.id', port=443):  |
| 13 | KCMO | Presiden Prabowo Luncurkan 11 Proyek Hilirisasi dengan Total Investasi | setkab.go.id | - | title_only | http_error | ('Connection aborted.', ConnectionResetError(10054, '현재 연결은  |
| 14 | KCMO | Prabowo Hadiri Groundbreaking 11 Proyek Hilirisasi Nikel di Maluku Uta | politikindonesia.id | 403 | title_only | bot_block |  |
| 15 | CMW | Pentagon backs ReElement Technologies with US$25M investment to expand | projectblue.com | 200 | lead_only | parse_fail |  |
| 16 | CMW | Speech by Commissioner Jørgensen at the inauguration of the Greensand  | ec.europa.eu | 200 | title_only | parse_fail |  |
| 17 | CMW | Neo begins commercial shipments from Estonia rare earth magnet plant - | fastmarkets.com | 200 | title_only | parse_fail |  |
| 18 | CMW | Insights from the Global Critical Minerals Outlook 2026: Special Focus | iea.org | 403 | title_only | bot_block |  |
| 19 | CMW | From exploration to processing: The missing link in India’s critical m | manufacturingtodayindia.com | 403 | lead_only | bot_block |  |
| 20 | CMW | US E - GPS Consulting - Critical Minerals Profile - new- Core- Consult | apply.deloitte.com | 200 | lead_only | parse_fail |  |
