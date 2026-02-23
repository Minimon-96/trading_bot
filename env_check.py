import os
import pyupbit
import logging
from dotenv import load_dotenv
from pathlib import Path

# 1 Load environment
load_dotenv()

# 2 Path setup
# Define root and log paths using env variables
BASE_DIR = Path("/home/mini_trade/trading_bot")
LOG_FILE = BASE_DIR / "logs" / "app.log"

# 3 Logging configuration
# Clean format: No special characters like [ ] - :
class CleanFormatter(logging.Formatter):
    def format(self, record):
        # Remove common special characters from the message if any
        msg = record.getMessage()
        clean_msg = "".join(char for char in msg if char.isalnum() or char.isspace())
        record.msg = clean_msg
        return super().format(record)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# File handler for permanent logs
file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
# Simple format: Timestamp Level Message
formatter = CleanFormatter('%(asctime)s %(levelname)s %(message)s', datefmt='%Y/%m/%d %H:%M:%S')
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Console handler for VS Code terminal
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

def run():
    # Simple English messages only
    logger.info("Bot start")
    
    try:
        # Check price
        price = pyupbit.get_current_price("KRW-BTC")
        if price:
            logger.info(f"Price check success BTC {int(price)}")
        else:
            logger.error("Price check fail")
            
        # Check API keys from .env
        access = os.getenv("UPBIT_ACCESS_KEY")
        if access and access != "your_access_key_here":
            logger.info("API key load success")
        else:
            logger.warning("API key missing")

    except Exception as e:
        logger.error("System error occurred")

    logger.info("Bot stop")

if __name__ == "__main__":
    run()