import pymysql
import time
import pyupbit
import os
from dotenv import load_dotenv

load_dotenv()

# ── DB 연결 설정 ─────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    "password": "root1234",
    "database": "test",
}

tickers = ["KRW-BTC", "KRW-XRP", "KRW-ETH"]


def get_conn():
    """매 호출 시 새 DB 연결을 반환합니다."""
    return pymysql.connect(**DB_CONFIG)


# ════════════════════════════════════════════════════════════════
#  기존 기능: 실시간 가격 기록 (upbit_tbl)
# ════════════════════════════════════════════════════════════════

def tb_upbit():
    """3개 코인의 현재가를 3초마다 upbit_tbl에 INSERT합니다."""
    print("upbit_tbl 기록 시작")
    while True:
        conn = None
        try:
            conn = get_conn()
            cursor = conn.cursor()
            for ticker in tickers:
                price = pyupbit.get_current_price(ticker)
                sql = "INSERT INTO upbit_tbl (name, price) VALUES (%s, %s)"
                cursor.execute(sql, (ticker, price))
            conn.commit()
            cursor.close()
        except Exception as e:
            print("에러 발생:", e)
        finally:
            if conn:
                conn.close()
        time.sleep(3)


# ════════════════════════════════════════════════════════════════
#  테이블 초기화 — 봇 시작 시 1회 호출
# ════════════════════════════════════════════════════════════════

def init_tables():
    """
    initial_asset, trade_history 테이블이 없으면 생성합니다.
    main.py __main__ 블록에서 1회 호출합니다.
    """
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()

        # 초기 기준 자산 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS initial_asset (
                ticker        VARCHAR(10)  NOT NULL,
                initial_money BIGINT       NOT NULL,
                created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker)
            )
        """)

        # 거래 이력 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trade_history (
                id            INT          NOT NULL AUTO_INCREMENT,
                ticker        VARCHAR(10)  NOT NULL,
                side          VARCHAR(4)   NOT NULL,        -- BUY / SELL
                price         BIGINT       NOT NULL,        -- 체결 가격 (KRW)
                amount        DECIMAL(20,8) NOT NULL,       -- 체결 수량 (코인)
                total         BIGINT       NOT NULL,        -- 체결 금액 (KRW)
                fee           DECIMAL(20,8) DEFAULT 0,      -- 수수료
                avg_buy_price BIGINT       DEFAULT 0,       -- 체결 시점 평균 매수가
                profit        BIGINT       DEFAULT 0,       -- 수익금 (SELL 시)
                profit_rate   DECIMAL(8,2) DEFAULT 0,       -- 수익률 % (SELL 시)
                wallet_before BIGINT       DEFAULT 0,       -- 거래 직전 지갑 총액
                wallet_after  BIGINT       DEFAULT 0,       -- 거래 직후 지갑 총액
                created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                INDEX idx_ticker (ticker),
                INDEX idx_side   (side),
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


# 기존 함수명 호환용 alias
def init_asset_table():
    init_tables()


# ════════════════════════════════════════════════════════════════
#  초기 기준 자산 관리 (initial_asset)
# ════════════════════════════════════════════════════════════════

def get_initial_asset(ticker: str) -> int | None:
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
    price:         int,     # 체결 가격
    amount:        float,   # 체결 수량
    total:         int,     # 체결 금액 (price × amount, KRW)
    fee:           float,   # 수수료
    avg_buy_price: int,     # 체결 시점 평균 매수가
    profit:        int,     # 수익금 (SELL만 의미 있음, BUY는 0)
    profit_rate:   float,   # 수익률 % (SELL만 의미 있음, BUY는 0)
    wallet_before: int,     # 거래 직전 지갑 총액
    wallet_after:  int,     # 거래 직후 지갑 총액
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
            VALUES
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            ticker, side, price, amount, total, fee,
            avg_buy_price, profit, profit_rate,
            wallet_before, wallet_after
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
#  참고용 테이블 DDL
# ════════════════════════════════════════════════════════════════
"""
CREATE TABLE upbit_tbl (
    id    INT(11)    NOT NULL AUTO_INCREMENT,
    name  VARCHAR(8) DEFAULT NULL,
    price FLOAT      DEFAULT NULL,
    time  TIMESTAMP  NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE initial_asset (
    ticker        VARCHAR(10) NOT NULL,
    initial_money BIGINT      NOT NULL,
    created_at    TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker)
);

CREATE TABLE trade_history (
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
);
"""

# ════════════════════════════════════════════════════════════════
#  기존 기능: 실시간 가격 기록 (upbit_tbl)
# ════════════════════════════════════════════════════════════════

def tb_upbit():
    """
    3개 코인의 현재가를 3초마다 upbit_tbl에 INSERT합니다.
    """
    print("upbit_tbl 기록 시작")
    while True:
        conn = None
        try:
            conn = get_conn()
            cursor = conn.cursor()
            for ticker in tickers:
                price = pyupbit.get_current_price(ticker)
                sql = "INSERT INTO upbit_tbl (name, price) VALUES (%s, %s)"
                cursor.execute(sql, (ticker, price))
            conn.commit()
            cursor.close()
        except Exception as e:
            print("에러 발생:", e)
        finally:
            if conn:
                conn.close()
        time.sleep(3)


# ════════════════════════════════════════════════════════════════
#  신규 기능: 코인별 초기 기준 자산 관리 (initial_asset 테이블)
# ════════════════════════════════════════════════════════════════

def init_asset_table():
    """
    initial_asset 테이블이 없으면 생성합니다.
    봇 최초 실행 시 또는 main.py 시작 시 1회 호출합니다.

    테이블 구조:
        ticker       VARCHAR(10)  PRIMARY KEY  -- 예: 'KRW-BTC'
        initial_money BIGINT                   -- 최초 기준 자산 (KRW)
        created_at   TIMESTAMP                 -- 최초 기록 시각
    """
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS initial_asset (
                ticker        VARCHAR(10)  NOT NULL,
                initial_money BIGINT       NOT NULL,
                created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (ticker)
            )
        """)
        conn.commit()
        cursor.close()
        print("[DB] initial_asset 테이블 준비 완료")
    except Exception as e:
        print(f"[DB] init_asset_table 실패: {e}")
    finally:
        if conn:
            conn.close()


def get_initial_asset(ticker: str) -> int | None:
    """
    DB에서 ticker의 초기 기준 자산을 조회합니다.

    Args:
        ticker: 코인 티커 (예: "KRW-BTC")

    Returns:
        initial_money (int)  — 레코드가 있는 경우
        None                 — 레코드가 없는 경우 (최초 실행)
    """
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT initial_money FROM initial_asset WHERE ticker = %s",
            (ticker,)
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

    Args:
        ticker:        코인 티커 (예: "KRW-BTC")
        initial_money: 기준으로 삼을 자산 금액 (KRW)

    Returns:
        True  — INSERT 성공
        False — 이미 존재하거나 실패
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
    수동으로 기준을 리셋하고 싶을 때 직접 호출하세요.
    다음 봇 시작 시 현재 잔고를 기준으로 다시 설정됩니다.

    Args:
        ticker: 코인 티커 (예: "KRW-BTC")

    Returns:
        True  — 삭제 성공
        False — 실패
    """
    conn = None
    try:
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM initial_asset WHERE ticker = %s",
            (ticker,)
        )
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
#  테이블 생성 SQL (참고용)
# ════════════════════════════════════════════════════════════════
"""
-- 기존 가격 기록 테이블
CREATE TABLE upbit_tbl (
    id    INT(11)     NOT NULL AUTO_INCREMENT,
    name  VARCHAR(8)  DEFAULT NULL,
    price FLOAT       DEFAULT NULL,
    time  TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);

-- 신규: 코인별 초기 기준 자산 테이블
CREATE TABLE initial_asset (
    ticker        VARCHAR(10) NOT NULL,
    initial_money BIGINT      NOT NULL,
    created_at    TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticker)
);
"""

if __name__ == '__main__':
    try:
        tb_upbit()
    except KeyboardInterrupt:
        pass