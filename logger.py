"""
logger.py
────────────────────────────────────────────────────────────────
코인별 독립 로그 파일을 생성하는 로거 모듈.

로그 파일 경로 규칙:
  /home/mini_trade/trading_bot/data/logs/scalper_KRW_BTC.YYYYMMDD
  /home/mini_trade/trading_bot/data/logs/scalper_KRW_ETH.YYYYMMDD
  /home/mini_trade/trading_bot/data/logs/scalper_KRW_XRP.YYYYMMDD
  /home/mini_trade/trading_bot/data/logs/scalper_SYSTEM.YYYYMMDD  ← 메인 프로세스용

사용법:
  # 프로세스 시작 시 1회 초기화 (coin = "KRW-BTC" 등)
  setup_logger(coin)

  # 이후 기존과 동일하게 사용
  log("INFO", "메시지")

  @log_function_call
  def MY_FUNC(...): ...
"""

import logging
import os
import functools
from logging.handlers import TimedRotatingFileHandler

# ── 경로 설정 ────────────────────────────────────────────────
BASE_DIR = "/home/mini_trade/trading_bot"
LOG_DIR  = os.path.join(BASE_DIR, "data", "logs")

# ── 모듈 내부 상태 ───────────────────────────────────────────
# 현재 프로세스에서 활성화된 logger 인스턴스를 보관
_active_logger: logging.Logger | None = None


# ════════════════════════════════════════════════════════════════
#  내부 유틸
# ════════════════════════════════════════════════════════════════

def _build_logger(name: str, log_prefix: str) -> logging.Logger:
    """
    name     : logging.getLogger에 사용할 고유 이름 (예: "KRW-BTC")
    log_prefix: 파일명 접두사       (예: "scalper_KRW_BTC")
    """
    os.makedirs(LOG_DIR, exist_ok=True)

    logger = logging.getLogger(name)

    # 중복 핸들러 방지
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # ── 파일 핸들러 (일별 교체) ──────────────────────────────
    log_base = os.path.join(LOG_DIR, log_prefix)
    file_handler = TimedRotatingFileHandler(
        filename    = log_base,
        when        = "midnight",
        interval    = 1,
        backupCount = 30,
        encoding    = "utf-8",
        utc         = False,
    )
    file_handler.suffix = "%Y%m%d"          # scalper_KRW_BTC.20240520
    file_handler.setLevel(logging.DEBUG)

    # ── 콘솔 핸들러 ─────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # ── 포매터 ──────────────────────────────────────────────
    formatter = logging.Formatter(
        fmt     = "%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt = "%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# ════════════════════════════════════════════════════════════════
#  공개 API
# ════════════════════════════════════════════════════════════════

def setup_logger(ticker: str = "SYSTEM") -> None:
    """
    현재 프로세스의 로거를 초기화합니다.
    multiprocessing.Process의 target 함수(run) 맨 첫 줄에서 1회 호출하세요.

    Args:
        ticker: 코인 티커 또는 식별자 (예: "KRW-BTC", "SYSTEM")

    파일명 예시:
        "KRW-BTC"  →  scalper_KRW_BTC.20240520
        "KRW-ETH"  →  scalper_KRW_ETH.20240520
        "SYSTEM"   →  scalper_SYSTEM.20240520
    """
    global _active_logger
    safe_name  = ticker.replace("-", "_")           # "KRW-BTC" → "KRW_BTC"
    log_prefix = f"scalper_{safe_name}"             # "scalper_KRW_BTC"
    _active_logger = _build_logger(ticker, log_prefix)


def _get_logger() -> logging.Logger:
    """
    활성 로거 반환. setup_logger()가 호출되지 않은 경우 SYSTEM 로거로 폴백.
    """
    global _active_logger
    if _active_logger is None:
        setup_logger("SYSTEM")
    return _active_logger


def log(level: str, *args) -> None:
    """
    기존 log() 호출 인터페이스를 그대로 유지합니다.
    level : "INFO" | "DG" | "TR" | "ER" | "WARN"
    args  : 로그에 출력할 메시지들 (여러 개 가능)

    사용 예:
        log("INFO", "현재가:", str(cur_price))
        log("TR",   "Success", res)
        log("DG",   "Margin Fail", e)
    """
    logger  = _get_logger()
    message = "  |  ".join(str(a) for a in args)

    level_upper = level.upper()
    if level_upper == "INFO":
        logger.info(message)
    elif level_upper in ("ER", "ERR", "ERROR"):
        logger.error(message)
    elif level_upper in ("WARN", "WARNING"):
        logger.warning(message)
    else:
        # "DG", "TR" 등 커스텀 레벨은 DEBUG로 기록
        logger.debug(f"[{level}] {message}")


def log_function_call(func):
    """
    @log_function_call 데코레이터.
    함수 진입/종료를 자동으로 DEBUG 레벨로 기록합니다.
    기존 upbit_api.py의 모든 @log_function_call 사용과 호환됩니다.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = _get_logger()
        logger.debug(f"[CALL] {func.__name__}() called  args={args[:2]}")
        result = func(*args, **kwargs)
        logger.debug(f"[CALL] {func.__name__}() returned  result={str(result)[:500]}")
        return result
    return wrapper