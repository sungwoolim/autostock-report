"""
analyzer.py — Step 2: GPT-4o AI 교차 분석
수집된 데이터를 기반으로 종목별 Fact Check, Sentiment Score, Key Insight를 생성합니다.
"""
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from .utils import setup_logger, safe_float, truncate

logger = setup_logger("analyzer")


# ─────────────────────────────────────────────
#  OpenAI 클라이언트 초기화
# ─────────────────────────────────────────────

def _get_openai_client():
    """OpenAI 클라이언트를 생성합니다. 키 없으면 None 반환."""
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-xxx"):
        logger.warning("⚠️ OPENAI_API_KEY가 설정되지 않았습니다. AI 분석을 스킵합니다.")
        return None
    try:
        from openai import OpenAI
        return OpenAI(api_key=api_key)
    except ImportError:
        logger.error("❌ openai 패키지가 설치되지 않았습니다: pip install openai")
        return None
    except Exception as e:
        logger.error(f"❌ OpenAI 클라이언트 초기화 실패: {e}")
        return None


# ─────────────────────────────────────────────
#  뉴스 컨텍스트 준비
# ─────────────────────────────────────────────

def _build_news_context(ticker: str, news: list[dict], max_articles: int = 15) -> str:
    """특정 종목과 관련된 뉴스 헤드라인을 텍스트로 요약합니다."""
    relevant = []

    # 종목 이름으로 필터링
    ticker_lower = ticker.lower()
    company_keywords = {
        "AAPL": ["apple", "aapl", "iphone", "mac", "ios"],
        "MSFT": ["microsoft", "msft", "azure", "windows", "copilot"],
        "GOOGL": ["google", "googl", "alphabet", "gemini", "youtube", "android"],
        "AMZN": ["amazon", "amzn", "aws", "prime", "bezos"],
        "NVDA": ["nvidia", "nvda", "gpu", "cuda", "jensen huang", "blackwell"],
        "META": ["meta", "facebook", "instagram", "whatsapp", "llama", "zuckerberg"],
        "TSLA": ["tesla", "tsla", "elon", "musk", "ev", "cybertruck"],
    }
    keywords = company_keywords.get(ticker, [ticker_lower])

    for article in news:
        title = article.get("title", "").lower()
        summary = article.get("summary", "").lower()
        if any(kw in title or kw in summary for kw in keywords):
            relevant.append(article)

    # 관련 기사가 부족하면 전체 뉴스에서 보충
    if len(relevant) < 5:
        for article in news:
            if article not in relevant:
                relevant.append(article)
            if len(relevant) >= max_articles:
                break

    relevant = relevant[:max_articles]

    if not relevant:
        return "관련 뉴스 없음"

    lines = []
    for i, a in enumerate(relevant, 1):
        source = a.get("source", "Unknown")
        title = a.get("title", "")
        summary = a.get("summary", "")[:200]
        lines.append(f"{i}. [{source}] {title}\n   요약: {summary}")

    return "\n\n".join(lines)


# ─────────────────────────────────────────────
#  단일 종목 AI 분석
# ─────────────────────────────────────────────

def _analyze_ticker(
    client,
    ticker: str,
    stock_info: dict,
    news_context: str,
    fear_greed: dict,
    stocktwits: dict,
    gpt_model: str = "gpt-4o",
    max_tokens: int = 1500,
) -> dict:
    """GPT-4o를 호출해 단일 종목을 분석합니다."""

    company_name = stock_info.get("company_name", ticker)
    price = stock_info.get("price", 0)
    change_pct = stock_info.get("change_pct", 0)
    market_cap = stock_info.get("market_cap", "N/A")
    pe = stock_info.get("pe_ratio", 0)
    analyst_target = stock_info.get("analyst_target", 0)
    recommendation = stock_info.get("recommendation", "N/A")
    fg_score = fear_greed.get("score", 50)
    fg_rating = fear_greed.get("rating", "N/A")
    st = stocktwits.get(ticker, {})
    bullish_pct = st.get("bullish_pct", 50)

    prompt = f"""당신은 월가 최고의 투자 애널리스트입니다. 아래 데이터를 분석하여 **반드시 유효한 JSON만** 반환하세요. 
마크다운 코드블록(```), 주석, 설명 텍스트를 절대 포함하지 마세요.

## 분석 대상: {ticker} ({company_name})

### 시장 데이터
- 현재가: ${price:.2f}
- 전일 대비: {change_pct:+.2f}%
- 시가총액: {market_cap}
- PER: {pe:.1f}x
- 분석가 평균 목표가: ${analyst_target:.2f}
- 분석가 추천: {recommendation}
- CNN Fear & Greed: {fg_score}/100 ({fg_rating})
- Stocktwits Bullish 비율: {bullish_pct:.1f}%

### 최근 24시간 주요 뉴스 (최대 15개)
{news_context}

## 요청 형식 (JSON만 출력):
{{
  "ticker": "{ticker}",
  "fact_check": "루머와 공식 공시/뉴스를 교차 분석한 결과 2~3문장. 특정 헤드라인이 과장되었는지, 공식 확인된 사실인지 명시.",
  "sentiment_score": 7,
  "sentiment_reason": "점수 산정 이유 1문장 (뉴스 심리, Fear&Greed, Stocktwits 종합)",
  "key_insight": "주식 초보자도 이해할 수 있는 오늘의 핵심 투자 변수. 3문장으로 작성. 전문 용어 최소화.",
  "recommendation": "매수 / 관망 / 주의",
  "recommendation_reason": "추천 이유 1문장",
  "risk_factors": ["리스크1 (구체적으로)", "리스크2", "리스크3"],
  "catalysts": ["상승 촉매1", "상승 촉매2"],
  "summary_one_line": "한 줄 요약 (투자자가 오늘 기억해야 할 단 하나의 문장)"
}}

규칙:
1. sentiment_score는 1(매우 부정) ~ 10(매우 긍정) 정수
2. recommendation은 반드시 "매수", "관망", "주의" 중 하나
3. 모든 내용은 한국어로 작성
4. JSON 외 다른 텍스트 절대 금지"""

    try:
        response = client.chat.completions.create(
            model=gpt_model,
            messages=[
                {"role": "system", "content": "당신은 전문 투자 애널리스트입니다. 요청된 JSON 형식만 정확히 반환합니다."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=max_tokens,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)
        logger.info(f"  ✅ {ticker} AI 분석 완료 — Sentiment: {result.get('sentiment_score')}/10, 추천: {result.get('recommendation')}")
        return result

    except json.JSONDecodeError as e:
        logger.error(f"  ❌ {ticker} JSON 파싱 실패: {e}")
        return _fallback_analysis(ticker, stock_info)
    except Exception as e:
        logger.error(f"  ❌ {ticker} OpenAI 호출 실패: {e}")
        return _fallback_analysis(ticker, stock_info)


def _fallback_analysis(ticker: str, stock_info: dict) -> dict:
    """AI 분석 실패 시 기본 구조를 반환합니다."""
    change_pct = stock_info.get("change_pct", 0)
    sentiment = 6 if change_pct >= 0 else 4
    return {
        "ticker": ticker,
        "fact_check": "AI 분석 불가 — OpenAI API 호출 실패 또는 API 키 미설정.",
        "sentiment_score": sentiment,
        "sentiment_reason": f"주가 등락률({change_pct:+.2f}%) 기반 기계적 추정",
        "key_insight": f"{ticker}의 AI 분석을 완료하지 못했습니다. OPENAI_API_KEY를 .env 파일에 설정해주세요.",
        "recommendation": "관망",
        "recommendation_reason": "AI 분석 데이터 없음",
        "risk_factors": ["AI 분석 불가로 리스크 평가 불가"],
        "catalysts": ["데이터 수집 후 재분석 필요"],
        "summary_one_line": f"{ticker}: AI 분석 실패 — 수동 확인 필요",
    }


# ─────────────────────────────────────────────
#  시장 전체 요약 분석
# ─────────────────────────────────────────────

def _analyze_market_summary(
    client,
    analyses: list[dict],
    fear_greed: dict,
    gpt_model: str = "gpt-4o",
) -> dict:
    """M7 전체 분석 결과를 바탕으로 시장 요약 코멘트를 생성합니다."""

    summaries = "\n".join([
        f"- {a['ticker']}: Sentiment {a.get('sentiment_score', 'N/A')}/10, "
        f"추천={a.get('recommendation','N/A')}, {a.get('summary_one_line','')}"
        for a in analyses
    ])

    fg_score = fear_greed.get("score", 50)
    fg_rating = fear_greed.get("rating", "N/A")

    prompt = f"""당신은 수석 시장 전략가입니다. M7 분석 결과를 바탕으로 오늘의 시장 전체 요약을 JSON으로만 반환하세요.

## M7 분석 요약
{summaries}

## CNN Fear & Greed: {fg_score}/100 ({fg_rating})

## 요청 형식 (JSON만):
{{
  "market_summary": "오늘 시장 전반에 대한 2~3문장 요약. 초보 투자자용으로 쉽게 설명.",
  "top_mover": "오늘 가장 주목할 종목 티커 (예: NVDA)",
  "top_mover_reason": "해당 종목을 주목해야 하는 이유 1문장",
  "market_mood": "강세 / 약세 / 혼조",
  "today_strategy": "오늘 투자자가 취해야 할 전략 2문장"
}}"""

    try:
        response = client.chat.completions.create(
            model=gpt_model,
            messages=[
                {"role": "system", "content": "수석 시장 전략가. JSON만 반환."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=600,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)
        logger.info(f"  ✅ 시장 전체 요약 완료 — 무드: {result.get('market_mood')}")
        return result
    except Exception as e:
        logger.error(f"  ❌ 시장 요약 분석 실패: {e}")
        return {
            "market_summary": "시장 전체 AI 분석 불가.",
            "top_mover": "N/A",
            "top_mover_reason": "N/A",
            "market_mood": "혼조",
            "today_strategy": "충분한 데이터 확인 후 투자 결정을 권장합니다.",
        }

# ─────────────────────────────────────────────
#  Daily Insights (투명성 및 핵심 토픽 분석)
# ─────────────────────────────────────────────

def _analyze_daily_insights(client, news: list[dict], gpt_model: str = "gpt-4o") -> dict:
    """수집된 전체 뉴스를 바탕으로 오늘의 핵심 토픽과 M7 영향력을 추출합니다."""
    # 가장 최근 뉴스 위주로 최대 30개만 컨텍스트로 사용 (토큰 제한 방지)
    sorted_news = sorted(news, key=lambda x: x.get("published", ""), reverse=True)[:30]
    
    if not sorted_news:
        return {
            "Topic_Title": "오늘의 주요 뉴스 없음",
            "Full_Summary": "수집된 뉴스 데이터가 없습니다.",
            "Related_M7_Ticker": "N/A",
            "Verified_Sources": [],
            "AI_Impact_Score": 5,
            "AI_Impact_Reason": "데이터 부족"
        }

    news_text = ""
    for i, a in enumerate(sorted_news, 1):
        source = a.get("source", "Unknown")
        title = a.get("title", "")
        link = a.get("link", "")
        # 요약본은 짧게 (토큰 절약)
        summary = a.get("summary", "")[:150]
        news_text += f"[{i}] 매체: {source}\nURL: {link}\n제목: {title}\n요약: {summary}\n\n"

    prompt = f"""당신은 최고 수준의 데이터 저널리스트이자 AI 애널리스트입니다.
아래 제공된 20개 매체의 최신 뉴스 데이터를 바탕으로 오늘 시장을 관통하는 단 하나의 '핵심 토픽'을 선정하고 심층 분석하세요.
반드시 유효한 JSON만 반환하세요.

## 오늘 수집된 뉴스 데이터
{news_text}

## 요청 형식 (JSON만 출력):
{{
  "Topic_Title": "오늘의 가장 핵심적인 시장 토픽 제목 (예: AI 반도체 규제 우려와 시장 파급)",
  "Full_Summary": "여러 뉴스를 교차 분석한 팩트 기반 요약 (3~4문장). 특정 매체의 과장된 헤드라인을 배제하고 사실만 전달하세요.",
  "Related_M7_Ticker": "관련된 M7 티커 (쉼표로 구분. 예: NVDA, MSFT. 관련 없으면 N/A)",
  "Verified_Sources": ["분석에 활용된 구체적인 뉴스 원문 URL 1", "뉴스 원문 URL 2", "뉴스 원문 URL 3"],
  "AI_Impact_Score": 7,
  "AI_Impact_Reason": "위 점수(1~10)를 산정한 이유 1문장 (M7 기업 주가에 미칠 단기 영향력 기준. 1=매우 부정적, 10=매우 긍정적)"
}}"""

    try:
        response = client.chat.completions.create(
            model=gpt_model,
            messages=[
                {"role": "system", "content": "당신은 데이터 저널리스트입니다. JSON 형식만 정확히 반환합니다."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)
        logger.info(f"  ✅ Daily Insights 분석 완료 — 토픽: {result.get('Topic_Title')}")
        return result
    except Exception as e:
        logger.error(f"  ❌ Daily Insights 분석 실패: {e}")
        return {
            "Topic_Title": "AI 분석 실패",
            "Full_Summary": "OpenAI API 호출에 실패했습니다.",
            "Related_M7_Ticker": "N/A",
            "Verified_Sources": [],
            "AI_Impact_Score": 5,
            "AI_Impact_Reason": "에러 발생"
        }
# ─────────────────────────────────────────────
#  메인 분석 함수
# ─────────────────────────────────────────────

def run_analysis(collected_data: dict, config: dict) -> dict:
    """
    전체 AI 분석 파이프라인을 실행합니다.
    Returns: {ticker: analysis_dict, ..., "market_summary": {...}}
    """
    logger.info("=" * 60)
    logger.info("🤖 AI 분석 시작 (GPT-4o)")
    logger.info("=" * 60)

    client = _get_openai_client()
    gpt_model = config.get("gpt_model", "gpt-4o")
    max_tokens = config.get("max_tokens", 1500)

    tickers = config["tickers"]
    stock_data = collected_data.get("stock_data", {})
    news = collected_data.get("news", [])
    fear_greed = collected_data.get("fear_greed", {})
    stocktwits = collected_data.get("stocktwits", {})

    analyses = {}
    analysis_list = []

    for ticker in tickers:
        logger.info(f"\n🔍 [{ticker}] 분석 중...")
        stock_info = stock_data.get(ticker, {})

        if "error" in stock_info:
            logger.warning(f"  ⚠️ {ticker} 주가 데이터 없음 — 분석 스킵")
            analyses[ticker] = _fallback_analysis(ticker, {})
            continue

        news_context = _build_news_context(ticker, news)

        if client:
            result = _analyze_ticker(
                client, ticker, stock_info, news_context,
                fear_greed, stocktwits, gpt_model, max_tokens
            )
        else:
            result = _fallback_analysis(ticker, stock_info)

        # 주가 데이터 병합
        result["price"] = stock_info.get("price", 0)
        result["change_pct"] = stock_info.get("change_pct", 0)
        result["market_cap"] = stock_info.get("market_cap", "N/A")
        result["pe_ratio"] = stock_info.get("pe_ratio", 0)
        result["analyst_target"] = stock_info.get("analyst_target", 0)
        result["week_52_high"] = stock_info.get("week_52_high", 0)
        result["week_52_low"] = stock_info.get("week_52_low", 0)
        result["company_name"] = stock_info.get("company_name", ticker)
        result["analyzed_at"] = datetime.now(timezone.utc).isoformat()

        analyses[ticker] = result
        analysis_list.append(result)

        # API 요청 간격 (Rate limit 방지)
        if client:
            time.sleep(1.0)

    # 시장 전체 요약
    logger.info("\n📊 시장 전체 요약 분석 중...")
    if client and analysis_list:
        market_summary = _analyze_market_summary(client, analysis_list, fear_greed, gpt_model)
        daily_insights = _analyze_daily_insights(client, news, gpt_model)
    else:
        market_summary = {
            "market_summary": "AI 분석 불가 — OpenAI API 키를 설정해주세요.",
            "top_mover": "N/A",
            "top_mover_reason": "N/A",
            "market_mood": "혼조",
            "today_strategy": "수동 분석을 권장합니다.",
        }
        daily_insights = {
            "Topic_Title": "AI 분석 불가", "Full_Summary": "API 키 미설정",
            "Related_M7_Ticker": "N/A", "Verified_Sources": [],
            "AI_Impact_Score": 5, "AI_Impact_Reason": "분석 불가"
        }

    analyses["market_summary"] = market_summary
    analyses["daily_insights"] = daily_insights
    analyses["fear_greed"] = fear_greed
    analyses["analyzed_at"] = datetime.now(timezone.utc).isoformat()

    logger.info("=" * 60)
    logger.info(f"✅ AI 분석 완료 — {len(analysis_list)}/{len(tickers)}개 종목")
    logger.info("=" * 60)

    return analyses
