"""
upbit_db.py
────────────────────────────────────────────────────────────────
DB 연결 및 거래 이력 관리 모듈.

[FIX]
  1. DB 계정/패스워드/DB명 하드코딩 제거 → .env 로드
  2. root 계정 직접 사용 제거 (전용 계정 사용 권장)
  3. DB명 'test' 제거 (전용 DB 사용 권장)
  4. 함수 중복 정의 전부 제거 (tb_upbit, init_asset_table 등)
  5. init_tables() 로 initial_asset + trade_history 통합 생성
  6. get_conn()에 ping(reconnect=True) 추가

.env 필수 항목:
  DB_HOST     = localhost
  DB_USER     = trade_bot        ← root 대신 전용 계정 사용
  DB_PASSWORD = <강한 비밀번호>
  DB_NAME     = trading          ← test 대신 전용 DB 사용
"""

import os
import pymysql
import time
import pyupbit
from dotenv import load_dotenv

load_dotenv()

# ── DB 연결 설정 — .env에서 로드 ─────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "localhost"),
    "user":     os.getenv("DB_USER",     "trade_bot"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME",     "trading"),
    "charset":  "utf8mb4",
}

tickers = ["KRW-BTC", "KRW-XRP", "KRW-ETH"]


def get_conn() -> pymysql.connections.Connection:
    """
    새 DB 연결을 반환합니다.
    ping(reconnect=True)로 장기 유휴 후 연결 끊김을 방어합니다.
    """
    conn = pymysql.connect(**DB_CONFIG)
    conn.ping(reconnect=True)
    return conn


# ════════════════════════════════════════════════════════════════
#  테이블 초기화 — 봇 시작 시 1회 호출
# ════════════════════════════════════════════════════════════════

def init_tables() -> None:
    """
    initial_asset, trade_history 테이블이 없으면 생성합니다.
    main.py __main__ 블록에서 1회 호출합니다.
    """
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS initial_asset (
                ticker        VARCHAR(10)   NOT NULL,
                initial_money BIGINT        NOT NULL,
                created_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_history (
                id            INT           NOT NULL AUTO_INCREMENT,
                ticker        VARCHAR(10)   NOT NULL,
                side          VARCHAR(4)    NOT NULL,
                price         BIGINT        NOT NULL,
                amount        DECIMAL(20,8) NOT NULL,
                total         BIGINT        NOT NULL,
                fee           DECIMAL(20,8) DEFAULT 0,
                avg_buy_price BIGINT        DEFAULT 0,
                profit        BIGINT        DEFAULT 0,
                profit_rate   DECIMAL(8,2)  DEFAULT 0,
                wallet_before BIGINT        DEFAULT 0,
                wallet_after  BIGINT        DEFAULT 0,
                created_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                INDEX idx_ticker     (ticker),
                INDEX idx_side       (side),
                INDEX idx_created_at (created_at)
            )
        """)

        conn.commit()
        cursor.close()
        print("[DB] 테이블 초기화 완료 (initial_asset, trade_history)")
    except Exception as e:
        print(f"[DB] init_tables 실패: {e}")
    finally:
        if conn:
            conn.close()


# 하위 호환 alias
def init_asset_table() -> None:
    init_tables()


# ════════════════════════════════════════════════════════════════
#  초기 기준 자산 관리 (initial_asset)
# ════════════════════════════════════════════════════════════════

def get_initial_asset(ticker: str) -> int | None:
    """
    DB에서 ticker의 초기 기준 자산을 조회합니다.

    Returns:
        initial_money (int) — 레코드가 있는 경우
        None                — 레코드가 없는 경우 (최초 실행)
    """
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT initial_money FROM initial_asset WHERE ticker = %s", (ticker,)
        )
        row = cursor.fetchone()
        cursor.close()
        return int(row[0]) if row else None
    except Exception as e:
        print(f"[DB] get_initial_asset 실패 ({ticker}): {e}")
        return None
    finally:
        if conn:
            conn.close()


def set_initial_asset(ticker: str, initial_money: int) -> bool:
    """
    ticker의 초기 기준 자산을 DB에 INSERT합니다.
    이미 레코드가 존재하면 아무것도 하지 않습니다 (INSERT IGNORE).
    """
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        affected = cursor.execute(
            "INSERT IGNORE INTO initial_asset (ticker, initial_money) VALUES (%s, %s)",
            (ticker, initial_money)
        )
        conn.commit()
        cursor.close()
        return affected > 0
    except Exception as e:
        print(f"[DB] set_initial_asset 실패 ({ticker}): {e}")
        return False
    finally:
        if conn:
            conn.close()


def reset_initial_asset(ticker: str) -> bool:
    """
    ticker의 초기 기준 자산 레코드를 삭제합니다.
    다음 봇 시작 시 현재 잔고를 기준으로 재설정됩니다.
    """
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM initial_asset WHERE ticker = %s", (ticker,))
        conn.commit()
        cursor.close()
        print(f"[DB] {ticker} 초기 자산 리셋 완료")
        return True
    except Exception as e:
        print(f"[DB] reset_initial_asset 실패 ({ticker}): {e}")
        return False
    finally:
        if conn:
            conn.close()


# ════════════════════════════════════════════════════════════════
#  거래 이력 기록 (trade_history)
# ════════════════════════════════════════════════════════════════

def insert_trade_history(
    ticker:        str,
    side:          str,     # "BUY" | "SELL"
    price:         int,
    amount:        float,
    total:         int,
    fee:           float,
    avg_buy_price: int,
    profit:        int,
    profit_rate:   float,
    wallet_before: int,
    wallet_after:  int,
) -> bool:
    """
    매수/매도 체결 직후 호출하여 거래 이력을 DB에 저장합니다.

    Returns:
        True  — INSERT 성공
        False — 실패 (로그만 남기고 거래 자체는 계속 진행)
    """
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO trade_history
                (ticker, side, price, amount, total, fee,
                 avg_buy_price, profit, profit_rate,
                 wallet_before, wallet_after)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            ticker, side, price, amount, total, fee,
            avg_buy_price, profit, profit_rate,
            wallet_before, wallet_after,
        ))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        print(f"[DB] insert_trade_history 실패 ({ticker} {side}): {e}")
        return False
    finally:
        if conn:
            conn.close()


# ════════════════════════════════════════════════════════════════
#  실시간 가격 기록 (upbit_tbl) — 별도 프로세스에서 실행
# ════════════════════════════════════════════════════════════════

def tb_upbit() -> None:
    """3개 코인의 현재가를 3초마다 upbit_tbl에 INSERT합니다."""
    print("upbit_tbl 기록 시작")
    while True:
        conn = None
        try:
            conn = get_conn()
            cursor = conn.cursor()
            for ticker in tickers:
                price = pyupbit.get_current_price(ticker)
                cursor.execute(
                    "INSERT INTO upbit_tbl (name, price) VALUES (%s, %s)",
                    (ticker, price)
                )
            conn.commit()
            cursor.close()
        except Exception as e:
            print(f"[DB] tb_upbit 에러: {e}")
        finally:
            if conn:
                conn.close()
        time.sleep(3)


if __name__ == "__main__":
    init_tables()