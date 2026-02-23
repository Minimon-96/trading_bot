import logging
from logging import handlers
from datetime import datetime
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# 로깅 설정 부분
LogFormatter = logging.Formatter('%(message)s')
today_ymd=datetime.today().strftime("%Y%m%d")

# 로그 파일명 지정 (00시 기준으로 '파일명.날짜' 형식으로 백업됨)
logFile="scalper"
default_log_dir = Path(__file__).resolve().parent / "logs"
logPath = os.getenv("LOG_PATH", default_log_dir)

if not os.path.exists(logPath):
    os.makedirs(logPath)

logFile = "scalper"
LOGPATH = os.path.join(logPath, logFile)

LogHandler = handlers.TimedRotatingFileHandler(filename=LOGPATH, when='midnight', interval=1, encoding='utf-8')
LogHandler.setFormatter(LogFormatter)
LogHandler.suffix = "%Y%m%d"

Logger = logging.getLogger()
Logger.setLevel(logging.INFO)
Logger.addHandler(LogHandler)

def log(level, *args):
    now = datetime.now()
    real_time = now.strftime('%Y-%m-%d %H:%M:%S')

    if level not in ("TR", "DG", "INFO"):   # 로그레벨 미지정시 에러
        logs = f"TR|{real_time}|Log Level Error|"
        Logger.info(logs)
        return 0

    logs = f"{level}|{real_time}"

    try:
        for i in args:  # log 함수에 인자로 받은 내용을 출력내용에 포함
            i = str(i)
            logs += f"| {i}"
    except Exception as e:
        logs += f"ER({e})"

    Logger.info(logs)   # log 파일에 출력
    return 1
    
def log_function_call(func):
    def wrapper(*args, **kwargs):
        params = ", ".join([f"{arg}" for arg in args])  # 인자들을 문자열로 변환
        log("TR",func.__name__,params)  # 호출된 함수명과 파라미터를 로깅
        return func(*args, **kwargs)    # 제공된 인자들로 원본 함수를 호출
    return wrapper

if __name__ == '__main__':
    print("logger.py")