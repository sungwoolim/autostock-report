"""
main.py — AutoStock Report 메인 실행 파일

사용법:
  python main.py                # 전체 파이프라인 실행
  python main.py --dry-run      # 더미 데이터로 테스트 (API 호출 없음)
  python main.py --no-sheets    # Google Sheets 업로드 스킵
  python main.py --no-email     # 이메일 발송 스킵

환경변수 (.env 파일):
  OPENAI_API_KEY=sk-...
  GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/service_account.json
  SMTP_EMAIL=your@gmail.com
  SMTP_PASSWORD=your_app_password
"""
import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# ── 프로젝트 루트를 sys.path에 추가
ROOT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROOT_DIR))

# ── 환경변수 로드
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT_DIR / ".env")
except ImportError:
    print("⚠️  python-dotenv 미설치. .env 파일을 수동으로 환경변수에 설정하거나 pip install python-dotenv 를 실행하세요.")

# ── 내부 모듈 임포트
from src.utils import setup_logger, today_str
from src.collector import run_collection
from src.analyzer import run_analysis
from src.sheets import upload_to_sheets
from src.newsletter import run_newsletter


# ─────────────────────────────────────────────
#  설정 파일 로드
# ─────────────────────────────────────────────

def load_config(config_path: str = "config.json") -> dict:
    path = ROOT_DIR / config_path
    if not path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────
#  JSON 결과 저장
# ─────────────────────────────────────────────

def save_json_output(data: dict, output_dir: str = "output") -> str:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = f"report_{today_str()}.json"
    filepath = ROOT_DIR / output_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return str(filepath)


# ─────────────────────────────────────────────
#  CLI 인자 파싱
# ─────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="AutoStock Report — M7 글로벌 빅테크 AI 투자 리포트 자동 생성 시스템",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python main.py                          # 전체 실행
  python main.py --dry-run                # API 호출 없이 테스트
  python main.py --dry-run --no-sheets    # 테스트 + Sheets 스킵
  python main.py --tickers AAPL NVDA      # 특정 종목만 분석
        """
    )
    parser.add_argument("--dry-run", action="store_true", help="더미 데이터로 전체 파이프라인 테스트")
    parser.add_argument("--no-sheets", action="store_true", help="Google Sheets 업로드 스킵")
    parser.add_argument("--no-email", action="store_true", help="이메일 발송 스킵")
    parser.add_argument("--tickers", nargs="+", help="분석할 종목 리스트 (기본: config.json)")
    parser.add_argument("--config", default="config.json", help="설정 파일 경로 (기본: config.json)")
    parser.add_argument("--output-dir", default="output", help="결과물 저장 디렉토리 (기본: output)")
    return parser.parse_args()


# ─────────────────────────────────────────────
#  메인 실행
# ─────────────────────────────────────────────

def main():
    args = parse_args()
    logger = setup_logger("main", log_dir=str(ROOT_DIR / "logs"))

    logger.info("=" * 70)
    logger.info("🚀 AutoStock Report 시작")
    logger.info(f"   실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"   모드: {'🧪 DRY RUN' if args.dry_run else '🔴 LIVE'}")
    logger.info("=" * 70)

    # ── 설정 로드
    try:
        config = load_config(args.config)
    except FileNotFoundError as e:
        logger.error(f"❌ {e}")
        sys.exit(1)

    # ── 종목 오버라이드
    if args.tickers:
        config["tickers"] = args.tickers
        logger.info(f"ℹ️  종목 오버라이드: {config['tickers']}")

    # ── 이메일 강제 비활성화
    if args.no_email:
        config.setdefault("email", {})["enabled"] = False

    output_dir = str(ROOT_DIR / args.output_dir)

    # ─────────────────────────────────────────
    #  STEP 1: 데이터 수집
    # ─────────────────────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("STEP 1/3 · 데이터 수집")
    logger.info("─" * 50)

    try:
        collected = run_collection(config, dry_run=args.dry_run)
    except Exception as e:
        logger.error(f"❌ 데이터 수집 중 치명적 오류: {e}", exc_info=True)
        sys.exit(1)

    # ─────────────────────────────────────────
    #  STEP 2: AI 분석
    # ─────────────────────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("STEP 2/3 · AI 교차 분석 (GPT-4o)")
    logger.info("─" * 50)

    try:
        analyses = run_analysis(collected, config)
    except Exception as e:
        logger.error(f"❌ AI 분석 중 치명적 오류: {e}", exc_info=True)
        sys.exit(1)

    # ─────────────────────────────────────────
    #  STEP 3: 결과물 배포
    # ─────────────────────────────────────────
    logger.info("\n" + "─" * 50)
    logger.info("STEP 3/3 · 결과물 배포")
    logger.info("─" * 50)

    # 3a. JSON 저장 (항상 실행)
    json_path = save_json_output({"collected": collected, "analyses": analyses}, output_dir)
    logger.info(f"✅ JSON 데이터 저장: {json_path}")

    # 3b. Google Sheets 업로드
    if not args.no_sheets:
        upload_to_sheets(analyses, config)
    else:
        logger.info("ℹ️  Google Sheets 업로드 스킵 (--no-sheets)")

    # 3c. HTML 뉴스레터 생성 & 이메일 발송
    html_path = run_newsletter(analyses, config, output_dir)

    # ─────────────────────────────────────────
    #  완료 요약
    # ─────────────────────────────────────────
    logger.info("\n" + "=" * 70)
    logger.info("🎉 AutoStock Report 완료!")
    logger.info(f"   📄 HTML 리포트: {html_path}")
    logger.info(f"   📊 JSON 데이터: {json_path}")
    logger.info(f"   📂 로그 파일:  {ROOT_DIR}/logs/report_{today_str()}.log")

    tickers = config.get("tickers", [])
    logger.info(f"\n{'종목':<8} {'현재가':>10} {'등락률':>8} {'Sentiment':>10} {'AI추천':>8}")
    logger.info("─" * 55)
    for ticker in tickers:
        a = analyses.get(ticker, {})
        if a and "error" not in a:
            price = a.get("price", 0)
            change = a.get("change_pct", 0)
            sentiment = a.get("sentiment_score", "N/A")
            rec = a.get("recommendation", "N/A")
            sign = "+" if change >= 0 else ""
            logger.info(f"   {ticker:<6} ${price:>9,.2f} {sign}{change:>6.2f}% {str(sentiment):>8}/10 {rec:>8}")

    market_sum = analyses.get("market_summary", {})
    logger.info(f"\n   시장 무드: {market_sum.get('market_mood','N/A')} | "
                f"주목 종목: {market_sum.get('top_mover','N/A')}")
    logger.info("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
