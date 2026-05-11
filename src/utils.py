"""
utils.py — 공통 유틸리티 (로깅, 재시도, 시간 처리)
"""
import logging
import time
import functools
import os
from datetime import datetime, timezone
from pathlib import Path


# ──────────────────────────────────────
#  로거 설정
# ──────────────────────────────────────

def setup_logger(name: str, log_dir: str = "logs") -> logging.Logger:
    """날짜별 파일 로거 + 콘솔 로거를 함께 반환합니다."""
    Path(log_dir).mkdir(parents=True, exist_ok=True)

    today = datetime.now().strftime("%Y%m%d")
    log_file = os.path.join(log_dir, f"report_{today}.log")

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # 중복 핸들러 방지
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 파일 핸들러
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(formatter)

    # 콘솔 핸들러
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


# ──────────────────────────────────────
#  재시도 데코레이터
# ──────────────────────────────────────

def retry(max_attempts: int = 3, delay: float = 2.0, exceptions=(Exception,)):
    """
    지정된 횟수만큼 자동 재시도하는 데코레이터.
    최종 실패 시 None을 반환하고 로그를 남깁니다.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(func.__module__)
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt < max_attempts:
                        logger.warning(
                            f"[Retry {attempt}/{max_attempts}] {func.__name__} 실패: {e} — {delay}초 후 재시도"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"[SKIP] {func.__name__} 최종 실패 (총 {max_attempts}회): {e}"
                        )
                        return None
        return wrapper
    return decorator


# ──────────────────────────────────────
#  시간 유틸리티
# ──────────────────────────────────────

def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_within_hours(dt: datetime, hours: int = 24) -> bool:
    """주어진 datetime이 현재로부터 hours 시간 이내인지 확인합니다."""
    if dt is None:
        return False
    now = get_utc_now()
    # timezone-naive datetime을 UTC로 처리
    if dt.tzinfo is None:
        from datetime import timezone as tz
        dt = dt.replace(tzinfo=tz.utc)
    diff = now - dt
    return diff.total_seconds() <= hours * 3600


def parse_rss_date(date_str: str) -> datetime | None:
    """feedparser의 다양한 날짜 형식을 파싱합니다."""
    import email.utils
    try:
        parsed = email.utils.parsedate_to_datetime(date_str)
        return parsed
    except Exception:
        pass
    # 공통 포맷 시도
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


# ──────────────────────────────────────
#  텍스트 유틸리티
# ──────────────────────────────────────

def truncate(text: str, max_chars: int = 500) -> str:
    """텍스트를 지정된 길이로 자르고 '...'을 붙입니다."""
    if not text:
        return ""
    text = text.strip().replace("\n", " ")
    return text[:max_chars] + "..." if len(text) > max_chars else text


def safe_float(value, default: float = 0.0) -> float:
    """안전하게 float 변환. 실패 시 default 반환."""
    try:
        if value is None or str(value).lower() in ("nan", "none", ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def format_market_cap(value: float) -> str:
    """시총을 읽기 좋은 형식으로 변환 (예: 3.2T, 450B)."""
    if value >= 1e12:
        return f"${value / 1e12:.2f}T"
    elif value >= 1e9:
        return f"${value / 1e9:.2f}B"
    elif value >= 1e6:
        return f"${value / 1e6:.2f}M"
    return f"${value:,.0f}"


def today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def today_display() -> str:
    return datetime.now().strftime("%Y년 %m월 %d일")
