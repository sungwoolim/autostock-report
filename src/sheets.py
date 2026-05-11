"""
sheets.py — Step 3a: Google Sheets 자동 업로드
gspread를 사용해 분석 결과를 Google Sheets에 행(Row)으로 추가합니다.
"""
import os
from datetime import datetime
from typing import Any

from .utils import setup_logger, safe_float, today_display

logger = setup_logger("sheets")


# ─────────────────────────────────────────────
#  인증 & 클라이언트
# ─────────────────────────────────────────────

def _get_gspread_client():
    """gspread 클라이언트를 초기화합니다. 실패 시 None 반환."""
    json_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not json_path or not os.path.exists(json_path):
        logger.warning("⚠️ GOOGLE_SERVICE_ACCOUNT_JSON이 설정되지 않았거나 파일이 없습니다. Sheets 업로드를 스킵합니다.")
        return None
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(json_path, scopes=scopes)
        client = gspread.authorize(creds)
        logger.info("✅ Google Sheets 인증 성공")
        return client
    except ImportError:
        logger.error("❌ gspread 또는 google-auth 미설치: pip install gspread google-auth")
        return None
    except Exception as e:
        logger.error(f"❌ Google Sheets 인증 실패: {e}")
        return None


# ─────────────────────────────────────────────
#  헤더 행 보장
# ─────────────────────────────────────────────

HEADERS = [
    "날짜", "종목", "회사명", "현재가($)", "전일대비(%)",
    "시가총액", "PER", "분석가목표가($)", "분석가추천",
    "Sentiment점수(1-10)", "Sentiment이유", "Fact Check",
    "Key Insight", "AI추천", "AI추천이유",
    "리스크1", "리스크2", "리스크3",
    "상승촉매1", "상승촉매2",
    "한줄요약", "분석시각"
]


def _ensure_header(worksheet) -> None:
    """워크시트 첫 번째 행이 헤더인지 확인하고, 없으면 추가합니다."""
    try:
        first_row = worksheet.row_values(1)
        if first_row != HEADERS:
            worksheet.insert_row(HEADERS, index=1)
            logger.info("📝 헤더 행 추가 완료")
    except Exception as e:
        logger.warning(f"⚠️ 헤더 확인 실패: {e}")


# ─────────────────────────────────────────────
#  데이터 행 생성
# ─────────────────────────────────────────────

def _build_row(ticker: str, analysis: dict) -> list:
    """분석 결과를 Google Sheets 행 리스트로 변환합니다."""
    today = today_display()
    risks = analysis.get("risk_factors", [])
    catalysts = analysis.get("catalysts", [])

    return [
        today,
        ticker,
        analysis.get("company_name", ticker),
        safe_float(analysis.get("price")),
        safe_float(analysis.get("change_pct")),
        analysis.get("market_cap", "N/A"),
        safe_float(analysis.get("pe_ratio")),
        safe_float(analysis.get("analyst_target")),
        analysis.get("recommendation", "N/A"),           # yfinance 분석가 추천
        analysis.get("sentiment_score", "N/A"),          # AI Sentiment 점수
        analysis.get("sentiment_reason", ""),
        analysis.get("fact_check", ""),
        analysis.get("key_insight", ""),
        analysis.get("recommendation", "관망"),           # AI 추천
        analysis.get("recommendation_reason", ""),
        risks[0] if len(risks) > 0 else "",
        risks[1] if len(risks) > 1 else "",
        risks[2] if len(risks) > 2 else "",
        catalysts[0] if len(catalysts) > 0 else "",
        catalysts[1] if len(catalysts) > 1 else "",
        analysis.get("summary_one_line", ""),
        analysis.get("analyzed_at", ""),
    ]


# ─────────────────────────────────────────────
#  메인 업로드 함수
# ─────────────────────────────────────────────

def upload_to_sheets(analyses: dict, config: dict) -> bool:
    """
    분석 결과를 Google Sheets에 업로드합니다.
    Returns: True(성공) / False(실패 또는 스킵)
    """
    sheets_config = config.get("google_sheets", {})
    spreadsheet_id = sheets_config.get("spreadsheet_id", "")
    worksheet_name = sheets_config.get("worksheet_name", "DailyReport")

    if not spreadsheet_id or spreadsheet_id == "YOUR_SPREADSHEET_ID_HERE":
        logger.warning("⚠️ config.json에 google_sheets.spreadsheet_id가 설정되지 않았습니다.")
        return False

    client = _get_gspread_client()
    if client is None:
        return False

    try:
        logger.info(f"📊 [Google Sheets] 업로드 시작 — 스프레드시트 ID: {spreadsheet_id[:20]}...")
        spreadsheet = client.open_by_key(spreadsheet_id)

        # 워크시트 가져오기 또는 생성
        try:
            ws = spreadsheet.worksheet(worksheet_name)
        except Exception:
            ws = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=len(HEADERS))
            logger.info(f"  📝 새 워크시트 생성: {worksheet_name}")

        _ensure_header(ws)

        # 종목별 행 추가
        tickers = config.get("tickers", [])
        rows_added = 0

        for ticker in tickers:
            analysis = analyses.get(ticker)
            if not analysis or "error" in analysis:
                logger.warning(f"  ⚠️ {ticker} 데이터 없음 — 스킵")
                continue

            row = _build_row(ticker, analysis)
            ws.append_row(row, value_input_option="USER_ENTERED")
            rows_added += 1
            logger.info(f"  ✅ {ticker} 행 추가 완료")

        # 시장 요약을 별도 시트에 저장
        _upload_market_summary(spreadsheet, analyses.get("market_summary", {}), analyses.get("fear_greed", {}))

        logger.info(f"✅ [Google Sheets] 업로드 완료 — {rows_added}개 종목 행 추가")
        return True

    except Exception as e:
        logger.error(f"❌ [Google Sheets] 업로드 실패: {e}")
        return False


def _upload_market_summary(spreadsheet, market_summary: dict, fear_greed: dict) -> None:
    """시장 요약을 'MarketSummary' 시트에 업로드합니다."""
    if not market_summary:
        return
    try:
        try:
            ws = spreadsheet.worksheet("MarketSummary")
        except Exception:
            ws = spreadsheet.add_worksheet(title="MarketSummary", rows=200, cols=5)

        today = today_display()
        ws.append_row([
            today,
            market_summary.get("market_mood", "N/A"),
            market_summary.get("market_summary", ""),
            market_summary.get("top_mover", "N/A"),
            market_summary.get("top_mover_reason", ""),
            market_summary.get("today_strategy", ""),
            fear_greed.get("score", "N/A"),
            fear_greed.get("rating", "N/A"),
        ], value_input_option="USER_ENTERED")
        logger.info("  ✅ MarketSummary 시트 업데이트 완료")
    except Exception as e:
        logger.warning(f"  ⚠️ MarketSummary 업로드 실패: {e}")
