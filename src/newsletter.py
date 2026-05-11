"""
newsletter.py — Step 3b: HTML 뉴스레터 생성 & 이메일 발송 (선택)
이메일 클라이언트 호환 인라인 CSS로 전문적인 HTML 뉴스레터를 생성합니다.
"""
import os
import smtplib
import json
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from .utils import setup_logger, safe_float, today_str, today_display

logger = setup_logger("newsletter")


# ─────────────────────────────────────────────
#  색상 유틸리티
# ─────────────────────────────────────────────

def _change_color(pct: float) -> str:
    if pct > 0:
        return "#22c55e"   # 초록
    elif pct < 0:
        return "#ef4444"   # 빨강
    return "#94a3b8"       # 중립


def _sentiment_color(score: int) -> str:
    if score >= 8:
        return "#22c55e"
    elif score >= 6:
        return "#f59e0b"
    elif score >= 4:
        return "#f97316"
    return "#ef4444"


def _recommendation_badge(rec: str) -> tuple[str, str]:
    """(배경색, 텍스트) 반환"""
    rec = str(rec).strip()
    if rec == "매수":
        return "#22c55e", "⬆ 매수"
    elif rec == "주의":
        return "#ef4444", "⚠ 주의"
    return "#64748b", "◆ 관망"


def _fg_color(score: float) -> str:
    if score >= 75:
        return "#22c55e"
    elif score >= 55:
        return "#86efac"
    elif score >= 45:
        return "#f59e0b"
    elif score >= 25:
        return "#f97316"
    return "#ef4444"


def _mood_badge(mood: str) -> tuple[str, str]:
    if "강세" in mood:
        return "#22c55e", "📈 강세"
    elif "약세" in mood:
        return "#ef4444", "📉 약세"
    return "#f59e0b", "↔ 혼조"


# ─────────────────────────────────────────────
#  HTML 생성
# ─────────────────────────────────────────────

def generate_html(analyses: dict, config: dict) -> str:
    """전문적인 투자 뉴스레터 HTML을 생성합니다."""
    tickers = config.get("tickers", [])
    today = today_display()
    fear_greed = analyses.get("fear_greed", {})
    market_summary = analyses.get("market_summary", {})

    fg_score = safe_float(fear_greed.get("score", 50))
    fg_rating = fear_greed.get("rating", "N/A")
    fg_color = _fg_color(fg_score)
    market_mood = market_summary.get("market_mood", "혼조")
    mood_bg, mood_text = _mood_badge(market_mood)

    # ── 종목 카드 행 생성
    ticker_rows = ""
    for ticker in tickers:
        a = analyses.get(ticker, {})
        if not a or "error" in a:
            continue
        price = safe_float(a.get("price"))
        change = safe_float(a.get("change_pct"))
        change_color = _change_color(change)
        sentiment = a.get("sentiment_score", "N/A")
        s_color = _sentiment_color(int(sentiment)) if str(sentiment).isdigit() else "#94a3b8"
        rec = a.get("recommendation", "관망")
        rec_bg, rec_text = _recommendation_badge(rec)
        market_cap = a.get("market_cap", "N/A")
        pe = safe_float(a.get("pe_ratio"))
        target = safe_float(a.get("analyst_target"))
        company = a.get("company_name", ticker)

        ticker_rows += f"""
        <tr style="border-bottom:1px solid #1e293b;">
          <td style="padding:14px 12px;font-weight:700;font-size:15px;color:#f1f5f9;">{ticker}</td>
          <td style="padding:14px 12px;color:#94a3b8;font-size:13px;">{company}</td>
          <td style="padding:14px 12px;font-weight:700;font-size:15px;color:#f1f5f9;">${price:,.2f}</td>
          <td style="padding:14px 12px;font-weight:700;color:{change_color};">{change:+.2f}%</td>
          <td style="padding:14px 12px;color:#94a3b8;">{market_cap}</td>
          <td style="padding:14px 12px;color:#94a3b8;">{pe:.1f}x</td>
          <td style="padding:14px 12px;color:#94a3b8;">${target:,.2f}</td>
          <td style="padding:14px 12px;text-align:center;">
            <span style="background:{s_color};color:#0f172a;padding:3px 10px;border-radius:20px;font-weight:700;font-size:13px;">{sentiment}/10</span>
          </td>
          <td style="padding:14px 12px;text-align:center;">
            <span style="background:{rec_bg};color:#fff;padding:4px 12px;border-radius:20px;font-weight:700;font-size:12px;">{rec_text}</span>
          </td>
        </tr>"""

    # ── 종목별 AI 분석 카드 생성
    analysis_cards = ""
    for ticker in tickers:
        a = analyses.get(ticker, {})
        if not a or "error" in a:
            continue
        company = a.get("company_name", ticker)
        price = safe_float(a.get("price"))
        change = safe_float(a.get("change_pct"))
        change_color = _change_color(change)
        sentiment = a.get("sentiment_score", "N/A")
        s_color = _sentiment_color(int(sentiment)) if str(sentiment).isdigit() else "#94a3b8"
        rec = a.get("recommendation", "관망")
        rec_bg, rec_text = _recommendation_badge(rec)
        fact_check = a.get("fact_check", "분석 없음")
        key_insight = a.get("key_insight", "분석 없음")
        risks = a.get("risk_factors", [])
        catalysts = a.get("catalysts", [])
        one_line = a.get("summary_one_line", "")
        sentiment_reason = a.get("sentiment_reason", "")

        risk_items = "".join([f'<li style="margin-bottom:4px;color:#fca5a5;">⚠ {r}</li>' for r in risks])
        catalyst_items = "".join([f'<li style="margin-bottom:4px;color:#86efac;">✓ {c}</li>' for c in catalysts])

        analysis_cards += f"""
        <div style="background:#1e293b;border-radius:16px;padding:28px;margin-bottom:24px;border-left:4px solid {s_color};">
          <!-- 종목 헤더 -->
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:12px;">
            <div>
              <span style="font-size:22px;font-weight:800;color:#f1f5f9;">{ticker}</span>
              <span style="color:#64748b;margin-left:8px;font-size:14px;">{company}</span>
            </div>
            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
              <span style="font-size:20px;font-weight:700;color:#f1f5f9;">${price:,.2f}</span>
              <span style="color:{change_color};font-weight:700;">{change:+.2f}%</span>
              <span style="background:{s_color};color:#0f172a;padding:4px 12px;border-radius:20px;font-weight:800;">Sentiment {sentiment}/10</span>
              <span style="background:{rec_bg};color:#fff;padding:4px 14px;border-radius:20px;font-weight:700;">{rec_text}</span>
            </div>
          </div>

          <!-- 한줄요약 -->
          <div style="background:#0f172a;border-radius:10px;padding:14px 18px;margin-bottom:18px;border-left:3px solid #6366f1;">
            <p style="margin:0;color:#c7d2fe;font-style:italic;font-size:14px;">💡 {one_line}</p>
          </div>

          <!-- Sentiment 이유 -->
          <p style="color:#94a3b8;font-size:13px;margin-bottom:18px;">📊 <strong style="color:#e2e8f0;">Sentiment 근거:</strong> {sentiment_reason}</p>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px;">
            <!-- Fact Check -->
            <div style="background:#0f172a;border-radius:10px;padding:16px;">
              <h4 style="margin:0 0 10px;color:#fbbf24;font-size:13px;text-transform:uppercase;letter-spacing:1px;">🔍 Fact Check</h4>
              <p style="margin:0;color:#cbd5e1;font-size:14px;line-height:1.6;">{fact_check}</p>
            </div>
            <!-- Key Insight -->
            <div style="background:#0f172a;border-radius:10px;padding:16px;">
              <h4 style="margin:0 0 10px;color:#34d399;font-size:13px;text-transform:uppercase;letter-spacing:1px;">🎯 Key Insight</h4>
              <p style="margin:0;color:#cbd5e1;font-size:14px;line-height:1.6;">{key_insight}</p>
            </div>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;">
            <!-- 리스크 -->
            <div style="background:#0f172a;border-radius:10px;padding:16px;">
              <h4 style="margin:0 0 10px;color:#f87171;font-size:13px;text-transform:uppercase;letter-spacing:1px;">⚠ 리스크 요인</h4>
              <ul style="margin:0;padding-left:16px;color:#fca5a5;font-size:14px;line-height:1.7;">{risk_items if risk_items else '<li style="color:#64748b;">리스크 없음</li>'}</ul>
            </div>
            <!-- 촉매 -->
            <div style="background:#0f172a;border-radius:10px;padding:16px;">
              <h4 style="margin:0 0 10px;color:#34d399;font-size:13px;text-transform:uppercase;letter-spacing:1px;">🚀 상승 촉매</h4>
              <ul style="margin:0;padding-left:16px;font-size:14px;line-height:1.7;">{catalyst_items if catalyst_items else '<li style="color:#64748b;">촉매 없음</li>'}</ul>
            </div>
          </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AutoStock Report — {today}</title>
</head>
<body style="margin:0;padding:0;background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:900px;margin:0 auto;padding:20px;">

  <!-- 헤더 -->
  <div style="background:linear-gradient(135deg,#1e293b 0%,#0f172a 100%);border-radius:20px;padding:40px;margin-bottom:24px;text-align:center;border:1px solid #334155;">
    <div style="font-size:12px;letter-spacing:3px;color:#6366f1;text-transform:uppercase;margin-bottom:12px;">AI-Powered Investment Report</div>
    <h1 style="margin:0 0 8px;font-size:36px;font-weight:800;background:linear-gradient(135deg,#6366f1,#a78bfa,#38bdf8);-webkit-background-clip:text;-webkit-text-fill-color:transparent;">AutoStock Report</h1>
    <p style="margin:0;color:#94a3b8;font-size:16px;">{today} · M7 빅테크 AI 투자 분석</p>

    <!-- 시장 지표 배지 -->
    <div style="display:flex;justify-content:center;gap:16px;margin-top:24px;flex-wrap:wrap;">
      <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:12px 20px;">
        <div style="font-size:11px;color:#64748b;letter-spacing:1px;margin-bottom:4px;">FEAR & GREED</div>
        <div style="font-size:22px;font-weight:800;color:{fg_color};">{fg_score:.0f}</div>
        <div style="font-size:12px;color:{fg_color};">{fg_rating}</div>
      </div>
      <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:12px 20px;">
        <div style="font-size:11px;color:#64748b;letter-spacing:1px;margin-bottom:4px;">MARKET MOOD</div>
        <div style="font-size:18px;font-weight:800;color:{mood_bg};">{mood_text}</div>
      </div>
      <div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:12px 20px;">
        <div style="font-size:11px;color:#64748b;letter-spacing:1px;margin-bottom:4px;">COVERAGE</div>
        <div style="font-size:18px;font-weight:800;color:#f1f5f9;">M7 + 20 Sources</div>
      </div>
    </div>
  </div>

  <!-- 시장 요약 -->
  <div style="background:linear-gradient(135deg,#312e81,#1e1b4b);border-radius:16px;padding:28px;margin-bottom:24px;border:1px solid #4338ca;">
    <h2 style="margin:0 0 16px;color:#a5b4fc;font-size:16px;letter-spacing:2px;text-transform:uppercase;">📊 오늘의 시장 요약</h2>
    <p style="margin:0 0 16px;color:#e2e8f0;font-size:16px;line-height:1.7;">{market_summary.get("market_summary","분석 없음")}</p>
    <div style="background:#1e1b4b;border-radius:10px;padding:16px;margin-top:16px;">
      <p style="margin:0 0 8px;color:#94a3b8;font-size:13px;">🌟 <strong style="color:#fbbf24;">오늘의 주목 종목:</strong> {market_summary.get("top_mover","N/A")} — {market_summary.get("top_mover_reason","")}</p>
      <p style="margin:0;color:#94a3b8;font-size:13px;">💼 <strong style="color:#34d399;">오늘의 전략:</strong> {market_summary.get("today_strategy","")}</p>
    </div>
  </div>

  <!-- 데이터 테이블 -->
  <div style="background:#1e293b;border-radius:16px;padding:24px;margin-bottom:24px;overflow-x:auto;">
    <h2 style="margin:0 0 20px;color:#f1f5f9;font-size:18px;font-weight:700;">📈 M7 시장 데이터</h2>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead>
        <tr style="border-bottom:2px solid #334155;">
          <th style="text-align:left;padding:12px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:1px;font-size:11px;">종목</th>
          <th style="text-align:left;padding:12px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:1px;font-size:11px;">회사</th>
          <th style="text-align:left;padding:12px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:1px;font-size:11px;">현재가</th>
          <th style="text-align:left;padding:12px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:1px;font-size:11px;">등락률</th>
          <th style="text-align:left;padding:12px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:1px;font-size:11px;">시총</th>
          <th style="text-align:left;padding:12px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:1px;font-size:11px;">PER</th>
          <th style="text-align:left;padding:12px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:1px;font-size:11px;">목표가</th>
          <th style="text-align:center;padding:12px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:1px;font-size:11px;">Sentiment</th>
          <th style="text-align:center;padding:12px;color:#6366f1;font-weight:700;text-transform:uppercase;letter-spacing:1px;font-size:11px;">추천</th>
        </tr>
      </thead>
      <tbody>{ticker_rows}</tbody>
    </table>
  </div>

  <!-- AI 분석 카드 -->
  <h2 style="color:#f1f5f9;font-size:20px;margin:0 0 20px;font-weight:700;">🤖 AI 심층 분석</h2>
  {analysis_cards}

  <!-- 푸터 -->
  <div style="text-align:center;padding:32px;color:#334155;font-size:12px;line-height:1.8;">
    <p style="margin:0 0 8px;">AutoStock Report · Generated by AI · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    <p style="margin:0;">이 리포트는 투자 참고용입니다. 실제 투자 결정은 전문가 상담 후 신중하게 판단하세요.</p>
    <p style="margin:8px 0 0;color:#475569;">Data Sources: yfinance · Reuters · CNBC · Bloomberg · TechCrunch · SEC EDGAR · CNN F&G · Reddit · Stocktwits · TipRanks · ARK Invest · and more</p>
  </div>

</div>
</body>
</html>"""

    return html


# ─────────────────────────────────────────────
#  파일 저장
# ─────────────────────────────────────────────

def save_html(html: str, output_dir: str = "output") -> str:
    """HTML 파일을 output 디렉토리에 저장합니다."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filename = f"report_{today_str()}.html"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"✅ HTML 뉴스레터 저장: {filepath}")
    return filepath


# ─────────────────────────────────────────────
#  이메일 발송 (선택)
# ─────────────────────────────────────────────

def send_email(html: str, config: dict) -> bool:
    """
    Gmail SMTP를 통해 HTML 뉴스레터를 발송합니다.
    config.email.enabled=false이면 스킵합니다.
    """
    email_config = config.get("email", {})
    if not email_config.get("enabled", False):
        logger.info("ℹ️  이메일 발송 비활성화 (config.json email.enabled=false)")
        return False

    smtp_email = os.getenv("SMTP_EMAIL", "")
    smtp_password = os.getenv("SMTP_PASSWORD", "")
    recipients = email_config.get("recipients", [])

    if not smtp_email or not smtp_password:
        logger.warning("⚠️ SMTP_EMAIL 또는 SMTP_PASSWORD 미설정. 이메일 발송 스킵.")
        return False

    if not recipients:
        logger.warning("⚠️ 수신자 목록이 비어 있습니다 (config.json email.recipients).")
        return False

    try:
        today = today_display()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"📊 AutoStock 투자 리포트 — {today}"
        msg["From"] = smtp_email
        msg["To"] = ", ".join(recipients)

        part_html = MIMEText(html, "html", "utf-8")
        msg.attach(part_html)

        host = email_config.get("smtp_host", "smtp.gmail.com")
        port = email_config.get("smtp_port", 587)

        with smtplib.SMTP(host, port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_email, smtp_password)
            server.sendmail(smtp_email, recipients, msg.as_string())

        logger.info(f"✅ 이메일 발송 완료 → {recipients}")
        return True

    except Exception as e:
        logger.error(f"❌ 이메일 발송 실패: {e}")
        return False


# ─────────────────────────────────────────────
#  메인 뉴스레터 함수
# ─────────────────────────────────────────────

def run_newsletter(analyses: dict, config: dict, output_dir: str = "output") -> str:
    """뉴스레터 HTML 생성 → 저장 → (선택) 이메일 발송."""
    logger.info("=" * 60)
    logger.info("📧 뉴스레터 생성 시작")
    logger.info("=" * 60)

    html = generate_html(analyses, config)
    filepath = save_html(html, output_dir)
    send_email(html, config)

    logger.info(f"✅ 뉴스레터 완료: {filepath}")
    return filepath
