import json
import logging
from datetime import datetime
import gspread
from gspread_formatting import (
    CellFormat, Color, TextFormat, format_cell_range,
    ConditionalFormatRule, BooleanRule, BooleanCondition,
    GridRange, set_data_validation_for_cell_range,
    GradientRule, InterpolationPoint
)

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 구글 API 권한 설정
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

# ==========================================
# [사용자 설정 영역]
# ==========================================
# 1. 여기에 발급받은 JSON 키 파일의 경로를 입력하세요.
SERVICE_ACCOUNT_FILE = 'utopian-nimbus-489114-j7-a39172064b1f.json' 
SPREADSHEET_NAME = "AutoStock_Master_Database"
# 구글 시트를 생성한 후 공유받을 본인의 구글 계정 이메일을 입력하세요. (필수)
ADMIN_EMAIL = "swoo9823@gmail.com" 

# 시트 구조 정의
MARKET_SUMMARY_HEADERS = ["날짜", "Fear&Greed", "Market Mood", "주목 종목", "시장 요약", "오늘의 전략"]
DEEP_ANALYSIS_HEADERS = ["날짜", "Ticker", "현재가", "등락률", "시총", "PER", "목표가", "Sentiment 점수", "추천", "Fact Check", "Key Insight", "리스크", "상승촉매"]
DAILY_INSIGHTS_HEADERS = ["날짜", "Topic_Title", "Full_Summary", "Related_M7_Ticker", "Verified_Sources", "AI_Impact_Score", "AI_Impact_Reason"]
TRANSPARENCY_LOG_HEADERS = ["날짜", "수집 시간", "매체명", "기사 제목", "원문 링크"]

def authenticate_gsheet():
    """구글 시트 API 인증"""
    import os
    try:
        service_account_env = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        if service_account_env and service_account_env.startswith("{"):
            # 환경변수에서 직접 JSON 로드
            creds_dict = json.loads(service_account_env)
            client = gspread.service_account_from_dict(creds_dict, scopes=SCOPES)
            logging.info("환경변수(JSON 문자열)를 통해 구글 API 인증 성공")
        else:
            # 로컬 파일 사용
            json_file = SERVICE_ACCOUNT_FILE if not service_account_env else service_account_env
            client = gspread.service_account(filename=json_file, scopes=SCOPES)
            logging.info("JSON 키 파일을 통해 구글 API 인증 성공")
        return client
    except Exception as e:
        logging.error(f"구글 API 인증 실패. JSON 키 파일이나 환경변수를 확인하세요: {e}")
        raise

def get_or_create_spreadsheet(client, name):
    """스프레드시트 열기 또는 생성"""
    try:
        sheet = client.open(name)
        logging.info(f"기존 스프레드시트 '{name}'를 열었습니다.")
    except gspread.exceptions.SpreadsheetNotFound:
        sheet = client.create(name)
        sheet.share(ADMIN_EMAIL, perm_type='user', role='writer')
        logging.info(f"새 스프레드시트 '{name}'를 생성하고 {ADMIN_EMAIL}에게 공유했습니다.")
    return sheet

def setup_worksheet(sheet, title, headers):
    """워크시트 생성 및 헤더 설정"""
    try:
        ws = sheet.worksheet(title)
        logging.info(f"워크시트 '{title}'에 접근했습니다.")
    except gspread.exceptions.WorksheetNotFound:
        ws = sheet.add_worksheet(title=title, rows=1000, cols=max(20, len(headers)))
        logging.info(f"워크시트 '{title}'를 생성했습니다.")
    
    # 헤더 업데이트
    ws.update('A1', [headers])
    return ws

def apply_base_formatting(sheet, ws, headers):
    """기본 서식 적용 (헤더 스타일, 눈금선 제거)"""
    num_cols = len(headers)
    last_col_letter = chr(ord('A') + num_cols - 1)
    header_range = f"A1:{last_col_letter}1"
    
    # 1. 헤더 서식 (네이비 #1A237E, 흰색 글자, 굵게, 가운데 정렬)
    header_format = CellFormat(
        backgroundColor=Color(26/255, 35/255, 126/255),
        textFormat=TextFormat(bold=True, foregroundColor=Color(1, 1, 1)),
        horizontalAlignment='CENTER'
    )
    format_cell_range(ws, header_range, header_format)
    
    # 2. 눈금선(Gridlines) 제거
    sheet.batch_update({
        "requests": [
            {
                "updateSheetProperties": {
                    "properties": {
                        "sheetId": ws.id,
                        "gridProperties": {"hideGridlines": True}
                    },
                    "fields": "gridProperties.hideGridlines"
                }
            }
        ]
    })
    logging.info(f"'{ws.title}' 기본 서식 및 눈금선 제거 완료.")

def apply_conditional_formatting(ws):
    """Deep_Analysis 시트의 조건부 서식 적용"""
    # 등락률 (D열), Sentiment 점수 (H열), 추천 (I열) - 인덱스는 0부터 시작
    
    # 기존 조건부 서식 초기화 (선택사항)
    ws.clear_basic_filter()

    requests = []

    # 1. 등락률(D열: 인덱스 3) 양수 빨강, 음수 파랑
    rule_positive = {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": 3, "endColumnIndex": 4}],
                "booleanRule": {
                    "condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]},
                    "format": {"textFormat": {"foregroundColor": {"red": 1.0, "green": 0.0, "blue": 0.0}}} # Red
                }
            },
            "index": 0
        }
    }
    rule_negative = {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": 3, "endColumnIndex": 4}],
                "booleanRule": {
                    "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
                    "format": {"textFormat": {"foregroundColor": {"red": 0.0, "green": 0.0, "blue": 1.0}}} # Blue
                }
            },
            "index": 1
        }
    }
    requests.extend([rule_positive, rule_negative])

    # 2. 추천(I열: 인덱스 8) 배경색 설정
    # 매수: 초록 (#4CAF50), 관망: 회색 (#9E9E9E), 매도: 주황 (#FF9800)
    recommend_colors = {
        "매수": {"red": 76/255, "green": 175/255, "blue": 80/255},
        "관망": {"red": 158/255, "green": 158/255, "blue": 158/255},
        "매도": {"red": 255/255, "green": 152/255, "blue": 0/255}
    }
    
    for val, color in recommend_colors.items():
        requests.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": 8, "endColumnIndex": 9}],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": val}]},
                        "format": {"backgroundColor": color}
                    }
                },
                "index": len(requests)
            }
        })

    # 3. Sentiment 점수(H열: 인덱스 7) 컬러 스케일 (0~10: 빨강-노랑-초록)
    rule_sentiment = {
        "addConditionalFormatRule": {
            "rule": {
                "ranges": [{"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": 7, "endColumnIndex": 8}],
                "gradientRule": {
                    "minpoint": {"color": {"red": 1.0, "green": 0.0, "blue": 0.0}, "type": "NUMBER", "value": "0"},
                    "midpoint": {"color": {"red": 1.0, "green": 1.0, "blue": 0.0}, "type": "NUMBER", "value": "5"},
                    "maxpoint": {"color": {"red": 0.0, "green": 1.0, "blue": 0.0}, "type": "NUMBER", "value": "10"}
                }
            },
            "index": len(requests)
        }
    }
    requests.append(rule_sentiment)

    # API 호출로 서식 일괄 적용
    ws.spreadsheet.batch_update({"requests": requests})
    logging.info("조건부 서식 적용 완료.")

def sync_data(ws, data_list, unique_keys):
    """데이터 동기화 (존재하면 업데이트, 없으면 추가)"""
    if not data_list:
        return

    # 기존 데이터 가져오기
    existing_records = ws.get_all_records()
    
    # 업데이트할 행과 추가할 행 분류
    rows_to_append = []
    
    # 기존 데이터 인덱싱 (고유키 조합을 키로 사용)
    # unique_keys가 ["날짜", "Ticker"]인 경우
    record_map = {}
    for idx, row in enumerate(existing_records):
        key = tuple(str(row.get(k, "")) for k in unique_keys)
        record_map[key] = idx + 2 # Header가 1행이므로 실제 데이터는 2행부터 시작

    ws_headers = ws.row_values(1)
    for item in data_list:
        key = tuple(str(item.get(k, "")) for k in unique_keys)
        row_data = [item.get(col, "") for col in ws_headers]
        
        if key in record_map:
            # 업데이트
            row_num = record_map[key]
            # 전체 행 업데이트 (A열부터 시작)
            cell_list = ws.range(f'A{row_num}:{chr(ord("A") + len(row_data) - 1)}{row_num}')
            for i, cell in enumerate(cell_list):
                cell.value = row_data[i]
            ws.update_cells(cell_list)
            logging.info(f"데이터 업데이트: {key} (행: {row_num})")
        else:
            # 추가
            rows_to_append.append(row_data)
            logging.info(f"새 데이터 추가 예정: {key}")

    if rows_to_append:
        ws.append_rows(rows_to_append)
        logging.info(f"총 {len(rows_to_append)}개 행 추가 완료.")

def generate_email_html(deep_analysis_data):
    """이메일 뉴스레터용 HTML 테이블 생성"""
    if not deep_analysis_data:
        return "<p>오늘의 분석 데이터가 없습니다.</p>"

    html = [
        '<table style="width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 14px;">',
        '<thead>',
        '<tr style="background-color: #1A237E; color: white;">',
        '<th style="padding: 10px; border: 1px solid #ddd;">종목</th>',
        '<th style="padding: 10px; border: 1px solid #ddd;">현재가</th>',
        '<th style="padding: 10px; border: 1px solid #ddd;">등락률</th>',
        '<th style="padding: 10px; border: 1px solid #ddd;">추천</th>',
        '<th style="padding: 10px; border: 1px solid #ddd;">Key Insight</th>',
        '</tr>',
        '</thead>',
        '<tbody>'
    ]

    for row in deep_analysis_data:
        # 등락률 색상
        change_rate = float(str(row.get("등락률", "0")).replace('%', ''))
        color = "red" if change_rate > 0 else ("blue" if change_rate < 0 else "black")
        
        # 추천 배경색
        reco = row.get("추천", "관망")
        reco_bg = "#4CAF50" if reco == "매수" else ("#FF9800" if reco == "매도" else "#9E9E9E")

        html.append('<tr>')
        html.append(f'<td style="padding: 10px; border: 1px solid #ddd; text-align: center; font-weight: bold;">{row.get("Ticker", "")}</td>')
        html.append(f'<td style="padding: 10px; border: 1px solid #ddd; text-align: right;">{row.get("현재가", "")}</td>')
        html.append(f'<td style="padding: 10px; border: 1px solid #ddd; text-align: right; color: {color};">{row.get("등락률", "")}</td>')
        html.append(f'<td style="padding: 10px; border: 1px solid #ddd; text-align: center; background-color: {reco_bg}; color: white;">{reco}</td>')
        html.append(f'<td style="padding: 10px; border: 1px solid #ddd;">{row.get("Key Insight", "")}</td>')
        html.append('</tr>')

    html.append('</tbody></table>')
    return "".join(html)

def main():
    import glob
    import os
    
    # ------------------------------------------
    # 실제 파이프라인에서 생성된 JSON 파일 읽기
    # ------------------------------------------
    output_dir = "output"
    json_files = glob.glob(os.path.join(output_dir, "report_*.json"))
    if not json_files:
        logging.error("output 폴더에 JSON 결과 파일이 없습니다. 먼저 python main.py를 실행하세요.")
        return
    
    latest_file = max(json_files, key=os.path.getctime)
    logging.info(f"데이터 파일 로드 중: {latest_file}")
    with open(latest_file, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    analyses = data.get("analyses", {})
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Market Summary 데이터 구성
    market_sum = analyses.get("market_summary", {})
    fg_score = analyses.get("fear_greed", {}).get("score", "-")
    
    real_market_data = [{
        "날짜": today,
        "Fear&Greed": fg_score,
        "Market Mood": market_sum.get("market_mood", "-"),
        "주목 종목": market_sum.get("top_mover", "-"),
        "시장 요약": market_sum.get("market_summary", "-"),
        "오늘의 전략": market_sum.get("today_strategy", "-")
    }]
    
    # 2. Deep Analysis 데이터 구성 (M7 전체)
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
    real_deep_analysis_data = []
    
    for t in tickers:
        a = analyses.get(t)
        if not a or "error" in a: continue
        
        # 추천 한글 매핑
        reco = a.get("recommendation", "관망")
        if reco in ["buy", "strong_buy"]: reco = "매수"
        elif reco in ["sell", "strong_sell"]: reco = "매도"
        elif reco in ["hold"]: reco = "관망"
            
        real_deep_analysis_data.append({
            "날짜": today,
            "Ticker": t,
            "현재가": f"${a.get('price', 0):.2f}",
            "등락률": f"{a.get('change_pct', 0):.2f}%",
            "시총": a.get("market_cap", "-"),
            "PER": f"{a.get('pe_ratio', 0):.1f}",
            "목표가": f"${a.get('analyst_target', 0):.2f}",
            "Sentiment 점수": a.get("sentiment_score", "-"),
            "추천": reco,
            "Fact Check": a.get("fact_check", "-"),
            "Key Insight": a.get("key_insight", "-"),
            "리스크": "\n".join(a.get("risk_factors", [])),
            "상승촉매": "\n".join(a.get("catalysts", []))
        })

    try:
        # 인증 및 시트 준비
        client = authenticate_gsheet()
        sheet = get_or_create_spreadsheet(client, SPREADSHEET_NAME)

        # 1. Market_Summary 시트 설정 및 데이터 동기화
        ws_market = setup_worksheet(sheet, "Market_Summary", MARKET_SUMMARY_HEADERS)
        apply_base_formatting(sheet, ws_market, MARKET_SUMMARY_HEADERS)
        sync_data(ws_market, real_market_data, ["날짜"])

        # 2. Deep_Analysis 시트 설정 및 데이터 동기화
        ws_deep = setup_worksheet(sheet, "Deep_Analysis", DEEP_ANALYSIS_HEADERS)
        apply_base_formatting(sheet, ws_deep, DEEP_ANALYSIS_HEADERS)
        apply_conditional_formatting(ws_deep)
        sync_data(ws_deep, real_deep_analysis_data, ["날짜", "Ticker"])

        # 3. Daily_Insights 시트 설정 및 데이터 동기화
        daily_insights = analyses.get("daily_insights", {})
        if daily_insights:
            real_daily_insights_data = [{
                "날짜": today,
                "Topic_Title": daily_insights.get("Topic_Title", ""),
                "Full_Summary": daily_insights.get("Full_Summary", ""),
                "Related_M7_Ticker": daily_insights.get("Related_M7_Ticker", ""),
                "Verified_Sources": "\n".join(daily_insights.get("Verified_Sources", [])),
                "AI_Impact_Score": daily_insights.get("AI_Impact_Score", ""),
                "AI_Impact_Reason": daily_insights.get("AI_Impact_Reason", "")
            }]
            ws_insights = setup_worksheet(sheet, "Daily_Insights", DAILY_INSIGHTS_HEADERS)
            apply_base_formatting(sheet, ws_insights, DAILY_INSIGHTS_HEADERS)
            sync_data(ws_insights, real_daily_insights_data, ["날짜"])

        # 4. Transparency_Log 시트 설정 및 데이터 동기화
        news_data = data.get("collected", {}).get("news", [])
        if news_data:
            real_transparency_data = []
            for n in news_data:
                title = n.get("title", "").strip()
                link = n.get("link", "").strip()
                if not title or not link:
                    continue
                real_transparency_data.append({
                    "날짜": today,
                    "수집 시간": n.get("published", today),
                    "매체명": n.get("source", "Unknown"),
                    "기사 제목": title,
                    "원문 링크": link
                })
            ws_transparency = setup_worksheet(sheet, "Transparency_Log", TRANSPARENCY_LOG_HEADERS)
            apply_base_formatting(sheet, ws_transparency, TRANSPARENCY_LOG_HEADERS)
            # 투명성 로그는 매번 링크가 추가될 수 있으므로 날짜와 링크를 고유키로 사용하여 중복 방지
            sync_data(ws_transparency, real_transparency_data, ["날짜", "원문 링크"])

        # 5. 이메일 뉴스레터용 HTML 생성 및 로그로 출력
        html_table = generate_email_html(real_deep_analysis_data)
        logging.info("\n========== [뉴스레터용 HTML 테이블 본문 코드] ==========\n\n" + html_table + "\n\n=========================================================")

    except Exception as e:
        logging.error(f"스크립트 실행 중 오류 발생: {e}")

if __name__ == "__main__":
    main()
