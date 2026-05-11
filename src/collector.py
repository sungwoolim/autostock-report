"""
collector.py — Step 1: 데이터 수집
20개 소스에서 주가 데이터 + 뉴스 헤드라인을 수집합니다.
각 소스는 독립적인 try/except로 감싸져 있어 일부 실패해도 전체 파이프라인이 계속됩니다.
"""
import os
import json
import time
import requests
import feedparser
import yfinance as yf
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from typing import Any

from .utils import (
    setup_logger, retry, is_within_hours, parse_rss_date,
    truncate, safe_float, format_market_cap, today_str
)

logger = setup_logger("collector")

# ─────────────────────────────────────────────
#  공통 헤더 (차단 방지)
# ─────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ─────────────────────────────────────────────
#  1. yfinance — 주가 & 재무지표
# ─────────────────────────────────────────────

def collect_stock_data(tickers: list[str]) -> dict[str, dict]:
    """
    yfinance를 통해 M7 종목의 현재가, 등락률, 주요 재무지표를 수집합니다.
    Returns: {ticker: {price, change_pct, market_cap, pe_ratio, ...}}
    """
    logger.info(f"📊 [yfinance] {len(tickers)}개 종목 데이터 수집 시작")
    result = {}

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info

            # 현재가 (장중: currentPrice, 장 후: previousClose 활용)
            price = safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
            prev_close = safe_float(info.get("previousClose") or info.get("regularMarketPreviousClose"))
            change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0

            result[ticker] = {
                "ticker": ticker,
                "price": price,
                "prev_close": prev_close,
                "change_pct": round(change_pct, 2),
                "market_cap_raw": safe_float(info.get("marketCap")),
                "market_cap": format_market_cap(safe_float(info.get("marketCap"))),
                "pe_ratio": safe_float(info.get("trailingPE")),
                "forward_pe": safe_float(info.get("forwardPE")),
                "revenue": safe_float(info.get("totalRevenue")),
                "eps": safe_float(info.get("trailingEps")),
                "week_52_high": safe_float(info.get("fiftyTwoWeekHigh")),
                "week_52_low": safe_float(info.get("fiftyTwoWeekLow")),
                "analyst_target": safe_float(info.get("targetMeanPrice")),
                "recommendation": info.get("recommendationKey", "N/A"),
                "sector": info.get("sector", "N/A"),
                "company_name": info.get("longName", ticker),
                "collected_at": datetime.now(timezone.utc).isoformat(),
            }
            logger.info(f"  ✅ {ticker}: ${price:.2f} ({change_pct:+.2f}%)")

        except Exception as e:
            logger.warning(f"  ⚠️ [SKIP] {ticker} yfinance 오류: {e}")
            result[ticker] = {"ticker": ticker, "error": str(e)}

        time.sleep(0.3)  # API rate limit 방지

    logger.info(f"📊 [yfinance] 수집 완료: {len([v for v in result.values() if 'error' not in v])}/{len(tickers)}개 성공")
    return result


def collect_yfinance_news(tickers: list[str], max_age_hours: int = 24) -> list[dict]:
    """yfinance .news 속성으로 종목별 뉴스를 수집합니다."""
    logger.info("[yfinance news] 종목별 뉴스 수집 시작")
    news_list = []

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            raw_news = stock.news or []
            for item in raw_news[:5]:  # 종목당 최대 5개
                pub_ts = item.get("providerPublishTime", 0)
                if pub_ts:
                    pub_dt = datetime.fromtimestamp(pub_ts, tz=timezone.utc)
                    if not is_within_hours(pub_dt, max_age_hours):
                        continue
                news_list.append({
                    "source": f"Yahoo Finance ({ticker})",
                    "ticker": ticker,
                    "title": item.get("title", ""),
                    "summary": item.get("summary", ""),
                    "link": item.get("link", ""),
                    "published": datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat() if pub_ts else "",
                    "category": "data",
                })
        except Exception as e:
            logger.warning(f"  ⚠️ [SKIP] {ticker} yfinance news 오류: {e}")

    logger.info(f"[yfinance news] {len(news_list)}개 수집 완료")
    return news_list


# ─────────────────────────────────────────────
#  2. RSS 피드 수집
# ─────────────────────────────────────────────

def collect_rss_feeds(sources: list[dict], max_age_hours: int = 24) -> list[dict]:
    """
    feedparser를 사용해 RSS 피드에서 최근 24시간 뉴스를 수집합니다.
    """
    logger.info(f"📰 [RSS] {len(sources)}개 소스 수집 시작")
    all_articles = []

    for source in sources:
        name = source.get("name", "Unknown")
        url = source.get("url", "")
        category = source.get("category", "general")

        try:
            feed = feedparser.parse(url, request_headers=HEADERS)

            if feed.bozo and not feed.entries:
                raise ValueError(f"피드 파싱 실패: {feed.bozo_exception}")

            count = 0
            for entry in feed.entries:
                # 날짜 파싱
                pub_str = entry.get("published") or entry.get("updated") or ""
                pub_dt = parse_rss_date(pub_str) if pub_str else None

                # 24시간 필터 (날짜 없으면 포함)
                if pub_dt and not is_within_hours(pub_dt, max_age_hours):
                    continue

                title = entry.get("title", "").strip()
                summary = truncate(
                    entry.get("summary") or entry.get("description") or "", 400
                )
                link = entry.get("link", "")

                if not title:
                    continue

                all_articles.append({
                    "source": name,
                    "category": category,
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published": pub_dt.isoformat() if pub_dt else "",
                })
                count += 1

            logger.info(f"  ✅ {name}: {count}개 기사 수집")

        except Exception as e:
            logger.warning(f"  ⚠️ [SKIP] {name} RSS 오류: {e}")

    logger.info(f"📰 [RSS] 총 {len(all_articles)}개 기사 수집 완료")
    return all_articles


# ─────────────────────────────────────────────
#  3. SEC EDGAR — 공시 데이터 (8-K / 10-K)
# ─────────────────────────────────────────────

@retry(max_attempts=2, delay=1.0)
def _fetch_sec_filings(cik: str, forms: list[str] = None) -> list[dict]:
    """SEC EDGAR REST API에서 최신 공시 목록을 가져옵니다."""
    if forms is None:
        forms = ["8-K", "10-K"]

    cik_normalized = cik.lstrip("0").zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{cik_normalized}.json"
    resp = requests.get(url, headers={**HEADERS, "User-Agent": "AutoStockBot contact@example.com"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    recent = data.get("filings", {}).get("recent", {})
    form_types = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    descriptions = recent.get("primaryDocument", [])
    accession_nums = recent.get("accessionNumber", [])

    results = []
    for i, form in enumerate(form_types):
        if form in forms:
            date_str = filing_dates[i] if i < len(filing_dates) else ""
            filing_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc) if date_str else None
            if filing_dt and not is_within_hours(filing_dt, 24 * 30):  # 30일 내
                continue
            acc = accession_nums[i].replace("-", "") if i < len(accession_nums) else ""
            link = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=5" if not acc else \
                   f"https://www.sec.gov/Archives/edgar/full-index/"
            results.append({
                "form": form,
                "date": date_str,
                "link": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=5",
            })
            if len(results) >= 3:
                break

    return results


def collect_sec_filings(cik_map: dict[str, str], forms: list[str]) -> list[dict]:
    """모든 종목의 SEC EDGAR 공시를 수집합니다."""
    logger.info(f"📋 [SEC EDGAR] {len(cik_map)}개 종목 공시 수집 시작")
    all_filings = []

    for ticker, cik in cik_map.items():
        try:
            filings = _fetch_sec_filings(cik, forms)
            if filings is None:
                raise ValueError("API 응답 없음")
            for f in filings:
                all_filings.append({
                    "source": "SEC EDGAR",
                    "category": "disclosure",
                    "ticker": ticker,
                    "title": f"[{f['form']}] {ticker} 공시 ({f['date']})",
                    "summary": f"{ticker}의 {f['form']} 공시가 SEC에 제출되었습니다.",
                    "link": f["link"],
                    "published": f["date"],
                })
            logger.info(f"  ✅ {ticker} ({cik}): {len(filings)}개 공시")
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"  ⚠️ [SKIP] {ticker} SEC EDGAR 오류: {e}")

    logger.info(f"📋 [SEC EDGAR] 총 {len(all_filings)}개 공시 수집 완료")
    return all_filings


# ─────────────────────────────────────────────
#  4. CNN Fear & Greed Index
# ─────────────────────────────────────────────

@retry(max_attempts=3, delay=1.5)
def collect_fear_greed_index() -> dict:
    """CNN Fear & Greed Index를 수집합니다."""
    logger.info("😨 [CNN F&G] Fear & Greed Index 수집")
    url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
    resp = requests.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    fg = data.get("fear_and_greed", {})
    score = safe_float(fg.get("score"))
    rating = fg.get("rating", "N/A")

    result = {
        "score": round(score, 1),
        "rating": rating,
        "description": f"CNN Fear & Greed: {score:.0f}/100 ({rating})",
    }
    logger.info(f"  ✅ Fear & Greed: {score:.0f} ({rating})")
    return result


# ─────────────────────────────────────────────
#  5. Reddit r/stocks (공개 JSON API)
# ─────────────────────────────────────────────

@retry(max_attempts=2, delay=2.0)
def collect_reddit(subreddit: str = "stocks", limit: int = 10) -> list[dict]:
    """Reddit의 공개 JSON API로 상위 스레드를 수집합니다 (인증 불필요)."""
    logger.info(f"🔴 [Reddit] r/{subreddit} 수집")
    url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit={limit}"
    resp = requests.get(url, headers={**HEADERS, "User-Agent": "AutoStockBot/1.0"}, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    posts = []
    for child in data.get("data", {}).get("children", []):
        post = child.get("data", {})
        score = post.get("score", 0)
        if score < 50:  # 너무 낮은 게시물 필터
            continue
        posts.append({
            "source": f"Reddit r/{subreddit}",
            "category": "sentiment",
            "title": post.get("title", ""),
            "summary": truncate(post.get("selftext", ""), 300),
            "link": f"https://reddit.com{post.get('permalink', '')}",
            "score": score,
            "comments": post.get("num_comments", 0),
            "published": datetime.fromtimestamp(
                post.get("created_utc", 0), tz=timezone.utc
            ).isoformat(),
        })

    logger.info(f"  ✅ Reddit: {len(posts)}개 게시물 수집")
    return posts


# ─────────────────────────────────────────────
#  6. Stocktwits — 종목별 감성
# ─────────────────────────────────────────────

def collect_stocktwits(tickers: list[str]) -> dict[str, dict]:
    """Stocktwits 공개 API로 종목별 Bullish/Bearish 비율을 수집합니다."""
    logger.info(f"💬 [Stocktwits] {len(tickers)}개 종목 감성 수집")
    result = {}

    for ticker in tickers:
        try:
            url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code == 429:
                logger.warning(f"  ⚠️ [SKIP] {ticker} Stocktwits 요청 한도 초과 (429)")
                continue
            resp.raise_for_status()
            data = resp.json()

            # sentiment 집계
            messages = data.get("messages", [])
            bullish = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish")
            bearish = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish")
            total = bullish + bearish

            result[ticker] = {
                "bullish": bullish,
                "bearish": bearish,
                "bullish_pct": round(bullish / total * 100, 1) if total else 0,
                "total_messages": len(messages),
            }
            logger.info(f"  ✅ {ticker}: Bullish {bullish}/{total}")
            time.sleep(0.5)

        except Exception as e:
            logger.warning(f"  ⚠️ [SKIP] {ticker} Stocktwits 오류: {e}")

    logger.info(f"💬 [Stocktwits] 완료: {len(result)}/{len(tickers)}개")
    return result


# ─────────────────────────────────────────────
#  7. TipRanks — 분석가 컨센서스 (스크래핑)
# ─────────────────────────────────────────────

def collect_tipranks(tickers: list[str]) -> dict[str, dict]:
    """TipRanks 공개 페이지에서 분석가 컨센서스를 스크래핑합니다."""
    logger.info(f"🎯 [TipRanks] {len(tickers)}개 종목 컨센서스 수집")
    result = {}

    for ticker in tickers:
        try:
            url = f"https://www.tipranks.com/stocks/{ticker.lower()}/forecast"
            resp = requests.get(url, headers=HEADERS, timeout=10)
            if resp.status_code in (403, 429, 503):
                logger.warning(f"  ⚠️ [SKIP] {ticker} TipRanks 접근 차단 ({resp.status_code})")
                continue

            soup = BeautifulSoup(resp.text, "lxml")

            # TipRanks 페이지에서 메타 정보 추출
            title_tag = soup.find("title")
            page_title = title_tag.text.strip() if title_tag else ""

            # og:description에서 간략한 정보 추출
            og_desc = soup.find("meta", property="og:description")
            description = og_desc["content"] if og_desc and og_desc.get("content") else "N/A"

            result[ticker] = {
                "page_title": page_title,
                "description": truncate(description, 300),
                "source_url": url,
            }
            logger.info(f"  ✅ {ticker}: TipRanks 메타 수집 완료")
            time.sleep(1.0)

        except Exception as e:
            logger.warning(f"  ⚠️ [SKIP] {ticker} TipRanks 오류: {e}")

    logger.info(f"🎯 [TipRanks] 완료: {len(result)}/{len(tickers)}개")
    return result


# ─────────────────────────────────────────────
#  메인 수집 함수
# ─────────────────────────────────────────────

def run_collection(config: dict, dry_run: bool = False) -> dict[str, Any]:
    """
    전체 데이터 수집 파이프라인을 실행합니다.
    dry_run=True: 실제 API 호출 없이 더미 데이터를 반환합니다.
    """
    if dry_run:
        logger.info("🧪 [DRY RUN] 더미 데이터로 실행합니다")
        return _get_dummy_data(config["tickers"])

    tickers = config["tickers"]
    max_age = config.get("max_news_age_hours", 24)
    cik_map = config.get("sec_cik_map", {})
    special = config.get("special_sources", {})

    logger.info("=" * 60)
    logger.info(f"🚀 AutoStock 데이터 수집 시작 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 60)

    # 1. 주가 데이터
    stock_data = collect_stock_data(tickers)

    # 2. yfinance 뉴스
    yf_news = collect_yfinance_news(tickers, max_age)

    # 3. RSS 뉴스
    rss_news = collect_rss_feeds(config.get("rss_sources", []), max_age)

    # 4. SEC EDGAR
    sec_filings = []
    if special.get("sec_edgar", {}).get("enabled", True) and cik_map:
        sec_forms = special["sec_edgar"].get("forms", ["8-K", "10-K"])
        sec_filings = collect_sec_filings(cik_map, sec_forms)

    # 5. CNN Fear & Greed
    fear_greed = {}
    if special.get("cnn_fear_greed", {}).get("enabled", True):
        try:
            fear_greed = collect_fear_greed_index() or {}
        except Exception as e:
            logger.warning(f"⚠️ [SKIP] CNN Fear & Greed: {e}")

    # 6. Reddit
    reddit_posts = []
    if special.get("reddit", {}).get("enabled", True):
        try:
            reddit_posts = collect_reddit(
                subreddit=special["reddit"].get("subreddit", "stocks"),
                limit=special["reddit"].get("limit", 10)
            ) or []
        except Exception as e:
            logger.warning(f"⚠️ [SKIP] Reddit: {e}")

    # 7. Stocktwits
    stocktwits_data = {}
    if special.get("stocktwits", {}).get("enabled", True):
        try:
            stocktwits_data = collect_stocktwits(tickers)
        except Exception as e:
            logger.warning(f"⚠️ [SKIP] Stocktwits: {e}")

    # 8. TipRanks
    tipranks_data = {}
    if special.get("tipranks", {}).get("enabled", True):
        try:
            tipranks_data = collect_tipranks(tickers)
        except Exception as e:
            logger.warning(f"⚠️ [SKIP] TipRanks: {e}")

    # 9. X(Twitter) — 스킵
    if not special.get("x_twitter", {}).get("enabled", False):
        logger.info("ℹ️  [X/Twitter] API 유료 구독 필요로 인해 스킵")

    # 통합 뉴스
    all_news = yf_news + rss_news + sec_filings + reddit_posts

    result = {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "stock_data": stock_data,
        "news": all_news,
        "fear_greed": fear_greed,
        "stocktwits": stocktwits_data,
        "tipranks": tipranks_data,
        "stats": {
            "total_news": len(all_news),
            "rss_count": len(rss_news),
            "yf_news_count": len(yf_news),
            "sec_count": len(sec_filings),
            "reddit_count": len(reddit_posts),
        }
    }

    logger.info("=" * 60)
    logger.info(f"✅ 데이터 수집 완료 — 총 뉴스: {len(all_news)}개")
    logger.info("=" * 60)

    return result


# ─────────────────────────────────────────────
#  Dry Run 더미 데이터
# ─────────────────────────────────────────────

def _get_dummy_data(tickers: list[str]) -> dict:
    """테스트용 더미 데이터를 반환합니다."""
    stock_data = {}
    dummy_prices = {"AAPL": 189.5, "MSFT": 415.2, "GOOGL": 172.3,
                    "AMZN": 185.7, "NVDA": 875.4, "META": 505.1, "TSLA": 172.0}
    for t in tickers:
        price = dummy_prices.get(t, 100.0)
        stock_data[t] = {
            "ticker": t, "price": price, "change_pct": round((hash(t) % 5 - 2) * 0.5, 2),
            "market_cap": "$2.89T", "pe_ratio": 28.5, "eps": 6.4,
            "week_52_high": price * 1.3, "week_52_low": price * 0.7,
            "analyst_target": price * 1.15, "recommendation": "buy",
            "company_name": t, "collected_at": datetime.now(timezone.utc).isoformat(),
        }
    return {
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "stock_data": stock_data,
        "news": [
            {"source": "Reuters [DRY RUN]", "category": "breaking",
             "title": f"[DRY RUN] {tickers[0]} 실적 발표 예정", "summary": "테스트 데이터입니다.",
             "link": "https://example.com", "published": datetime.now(timezone.utc).isoformat()},
            {"source": "CNBC [DRY RUN]", "category": "breaking",
             "title": "[DRY RUN] NVDA AI 칩 수요 급증", "summary": "더미 데이터 — AI 수요 관련 뉴스.",
             "link": "https://example.com", "published": datetime.now(timezone.utc).isoformat()},
        ],
        "fear_greed": {"score": 55.0, "rating": "Neutral", "description": "CNN Fear & Greed: 55/100 (Neutral) [DRY RUN]"},
        "stocktwits": {t: {"bullish": 6, "bearish": 4, "bullish_pct": 60.0, "total_messages": 10} for t in tickers},
        "tipranks": {t: {"description": "Analyst consensus: Strong Buy [DRY RUN]", "source_url": ""} for t in tickers},
        "stats": {"total_news": 2, "rss_count": 0, "yf_news_count": 2, "sec_count": 0, "reddit_count": 0},
    }
