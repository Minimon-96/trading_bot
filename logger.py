import logging
import os
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

# ──────────────────────────────────────────────
#  Path Configuration
# ──────────────────────────────────────────────
BASE_DIR = "/home/mini_trade/trading_bot"
LOG_DIR  = os.path.join(BASE_DIR, "data", "logs")

# Create log directory if it doesn't exist
os.makedirs(LOG_DIR, exist_ok=True)

# ──────────────────────────────────────────────
#  Log File: scalper.YYYYMMDD  (daily rotation)
# ──────────────────────────────────────────────
LOG_FILE_PREFIX = os.path.join(LOG_DIR, "scalper")

def get_logger(name: str = "trading_bot") -> logging.Logger:
    """
    Returns a logger that writes to a daily-rotated file:
        /home/mini_trade/trading_bot/data/logs/scalper.YYYYMMDD
    and also outputs to the console.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers on re-import
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # ── File Handler (daily rotation at midnight) ──
    file_handler = TimedRotatingFileHandler(
        filename=LOG_FILE_PREFIX,   # base name: scalper
        when="midnight",            # rotate at midnight
        interval=1,                 # every 1 day
        backupCount=30,             # keep last 30 days
        encoding="utf-8",
        utc=False
    )
    # Suffix produces: scalper.20240520
    file_handler.suffix = "%Y%m%d"
    file_handler.setLevel(logging.DEBUG)

    # ── Console Handler ──
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    # ── Formatter ──
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# ──────────────────────────────────────────────
#  Default logger instance
# ──────────────────────────────────────────────
logger = get_logger()

def log(level, *args):
    now = datetime.now()
    real_time = now.strftime('%Y-%m-%d %H:%M:%S')

    if level not in ("TR", "DG", "INFO"):   # 로그레벨 미지정시 에러
        logs = f"ERR|{real_time}|Log Level Error|"
        logger.info(logs)
        return 0

    logs = f"{level}|{real_time}"

    try:
        for i in args:  # log 함수에 인자로 받은 내용을 출력내용에 포함
            i = str(i)
            logs += f"| {i}"
    except Exception as e:
        logs += f"ER({e})"

    logger.info(logs)   # log 파일에 출력
    return 1
    
def log_function_call(func):
    def wrapper(*args, **kwargs):
        params = ", ".join([f"{arg}" for arg in args])  # 인자들을 문자열로 변환
        log("TR",func.__name__,params)  # 호출된 함수명과 파라미터를 로깅
        return func(*args, **kwargs)    # 제공된 인자들로 원본 함수를 호출
    return wrapper

if __name__ == '__main__':
    print("logger.py")