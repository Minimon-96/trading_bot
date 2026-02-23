import sqlite3
import datetime
import os

# 1. 원하는 경로 설정
DB_DIR = "./data"
DB_FILENAME = f"{DB_DIR}/trade_history.db"

# 2. 폴더가 없으면 자동으로 생성하는 함수
def ensure_dir_exists():
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
        print(f"[{DB_DIR}] 폴더를 새로 생성했습니다.")

def get_connection():
    ensure_dir_exists()  # DB 연결 전에 무조건 폴더가 있는지 확인!
    return sqlite3.connect(DB_FILENAME)

def init_db():
    # ... (기존 테이블 생성 코드와 동일) ...
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            uuid TEXT UNIQUE NOT NULL,
            ticker TEXT,
            price REAL,
            volume REAL,
            fee REAL,
            profit REAL,
            ma_short REAL,
            ma_long REAL,
            last_ma_short REAL,
            last_ma_long REAL,
            balance REAL,
            side TEXT,
            order_type TEXT,
            status TEXT DEFAULT 'Done',
            trade_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    print("DB 초기화 완료 (경로: ./data/trade_history.db)")

def insert_trade(uuid, ticker, price, volume, fee, profit, ma_short, ma_long, last_ma_short, last_ma_long, balance, side, order_type, status='Done'):
    """
    거래 발생 시 데이터를 Insert 하는 함수입니다. (profit 파라미터 추가)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # id는 AUTOINCREMENT 이므로 값을 직접 넣지 않아도 알아서 1, 2, 3... 으로 채워집니다.
        cursor.execute('''
            INSERT INTO trade_log (
                uuid, ticker, price, volume, fee, profit, ma_short, ma_long, 
                last_ma_short, last_ma_long, balance, side, order_type, status, trade_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (uuid, ticker, price, volume, fee, profit, ma_short, ma_long, last_ma_short, last_ma_long, balance, side, order_type, status, now))
        
        conn.commit()
        print(f"[DB 저장 성공] {side} | {order_type} | {price}원 | 수익금: {profit}원")
    except sqlite3.IntegrityError:
        print(f"[DB 저장 실패] 이미 존재하는 uuid 입니다: {uuid}")
    except Exception as e:
        print(f"[DB 저장 에러] {e}")
    finally:
        conn.close()

def update_limit_order(uuid, profit=0):
    """
    지정가 거래타입인 경우, uuid를 검색하여 거래시간, 상태, 그리고 수익금(profit)을 수정합니다.
    (지정가 매도의 경우 체결 시점에 수익금이 확정되기 때문입니다)
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute('''
            UPDATE trade_log 
            SET trade_time = ?, status = 'Done', profit = ?
            WHERE uuid = ?
        ''', (now, profit, uuid))
        
        conn.commit()
        print(f"[DB 업데이트 성공] 지정가 주문 체결 완료 (uuid: {uuid}, 수익금: {profit}원)")
    except Exception as e:
        print(f"[DB 업데이트 에러] {e}")
    finally:
        conn.close()
        

def get_all_trades(limit=10):
    """
    1. 최근 거래 내역 조회 (기본 10개)
    가장 최근에 발생한 거래부터 역순으로 보여줍니다.
    """
    conn = get_connection()
    # 결과를 딕셔너리처럼 이름으로 접근할 수 있게 해줍니다. (예: row['price'])
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT id, trade_time, ticker, side, price, volume, profit, status 
            FROM trade_log 
            ORDER BY id DESC 
            LIMIT ?
        ''', (limit,))
        
        rows = cursor.fetchall()
        print(f"\n--- 📋 최근 거래 내역 ({len(rows)}건) ---")
        for row in rows:
            print(f"[{row['id']}] {row['trade_time']} | {row['ticker']} | {row['side']} | 체결가: {row['price']} | 상태: {row['status']} | 수익금: {row['profit']}")
        return rows
    except Exception as e:
        print(f"[조회 에러] {e}")
    finally:
        conn.close()


def get_trades_by_status(status="Wait"):
    """
    2. 특정 상태의 거래 조회 (예: 미체결 지정가 주문 찾기)
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT id, uuid, trade_time, side, price, volume 
            FROM trade_log 
            WHERE status = ?
            ORDER BY id ASC
        ''', (status,))
        
        rows = cursor.fetchall()
        print(f"\n--- ⏳ 대기 중인 주문 ({len(rows)}건) ---")
        for row in rows:
            print(f"[{row['id']}] {row['side']} | 목표가: {row['price']} | 수량: {row['volume']} | UUID: {row['uuid']}")
        return rows
    except Exception as e:
        print(f"[조회 에러] {e}")
    finally:
        conn.close()


def get_total_profit():
    """
    3. 총 누적 수익금 계산
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # SUM 함수를 사용해 profit 컬럼의 모든 값을 더합니다.
        cursor.execute('SELECT SUM(profit) FROM trade_log')
        
        result = cursor.fetchone()[0]
        total_profit = result if result is not None else 0
        
        print(f"\n--- 💰 총 누적 수익금: {total_profit}원 ---")
        return total_profit
    except Exception as e:
        print(f"[조회 에러] {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    import uuid
    import time
    # 🌟 텔레그램 전송 함수 불러오기 (파일명이 mod_telegram.py 일 경우)
    from mod_telegram import send_telegram_msg 
    
    # 1. DB 초기화 및 폴더 확인
    ensure_dir_exists()
    init_db()
    
    print("\n--- 📝 테스트용 데이터 Insert 및 텔레그램 연동 시작 ---")
    
    # [테스트 1] 리플(XRP) 시장가 매수 + 텔레그램 알림
    price = 600
    volume = 100
    balance = 440000
    insert_trade(str(uuid.uuid4()), "KRW-XRP", price, volume, 30, 0, 590, 580, 585, 575, balance, "Buy", "Market", "Done")
    
    msg_buy = f"🟢 [시장가 매수 완료]\n▪️ 코인: KRW-XRP\n▪️ 체결가: {price}원\n▪️ 수량: {volume}\n💰 남은 잔고: {balance}원"
    send_telegram_msg(msg_buy)
    time.sleep(1) # 알림이 너무 빨리 가지 않게 1초 대기


    # [테스트 2] 리플(XRP) 시장가 매도 + 텔레그램 알림 (수익 +2900원)
    sell_price = 630
    profit = 2900
    balance = 502900
    insert_trade(str(uuid.uuid4()), "KRW-XRP", sell_price, 100, 31.5, profit, 620, 600, 610, 590, balance, "Sell", "Market", "Done")
    
    msg_sell = f"🔴 [시장가 매도 체결]\n▪️ 코인: KRW-XRP\n▪️ 체결가: {sell_price}원\n💸 수익금: +{profit}원\n💰 남은 잔고: {balance}원"
    send_telegram_msg(msg_sell)
    time.sleep(1)


    # [테스트 3~9] 나머지 데이터는 텔레그램 알림 없이 DB에만 조용히 넣기
    insert_trade(str(uuid.uuid4()), "KRW-BTC", 90000000, 0.001, 45, 0, 89000000, 88000000, 88500000, 87000000, 412855, "Buy", "Market", "Done")
    insert_trade(str(uuid.uuid4()), "KRW-BTC", 95000000, 0.001, 0, 0, 92000000, 89000000, 91000000, 88000000, 412855, "Sell", "Limit", "Wait")
    insert_trade(str(uuid.uuid4()), "KRW-ETH", 4500000, 0.05, 0, 0, 4600000, 4700000, 4650000, 4750000, 412855, "Buy", "Limit", "Wait")
    insert_trade(str(uuid.uuid4()), "KRW-XRP", 585, 100, 29.2, -1500, 580, 595, 590, 600, 411355, "Sell", "Market", "Done")
    insert_trade(str(uuid.uuid4()), "KRW-ETH", 4550000, 0.02, 45.5, 0, 4520000, 4500000, 4510000, 4490000, 320309, "Buy", "Market", "Done")
    insert_trade(str(uuid.uuid4()), "KRW-ETH", 4800000, 0.02, 48, 5000, 4750000, 4600000, 4700000, 4550000, 416309, "Sell", "Market", "Done")
    insert_trade(str(uuid.uuid4()), "KRW-DOGE", 200, 500, 50, 0, 195, 180, 190, 175, 316259, "Buy", "Limit", "Done")
    
    
    # [테스트 10] 도지코인(DOGE) 지정가 매도 대기 (목표가 250원)
    uuid_for_update = str(uuid.uuid4())
    insert_trade(uuid_for_update, "KRW-DOGE", 250, 500, 0, 0, 230, 200, 220, 190, 316259, "Sell", "Limit", "Wait")
    
    print("\n--- 🔍 조회 쿼리 테스트 ---")
    get_all_trades(5)
    get_trades_by_status("Wait")
    get_total_profit()
    
    # 4. [10]번 도지코인 지정가 매도 체결 시 Update + 텔레그램 알림!
    print("\n--- ⚡ 10번 지정가 매도 주문 체결 처리(업데이트) ---")
    limit_profit = 25000
    update_limit_order(uuid_for_update, profit=limit_profit)
    
    msg_limit_done = f"⚡ [지정가 매도 체결 완료]\n▪️ 코인: KRW-DOGE\n💸 수익금: +{limit_profit}원\n목표가에 도달하여 자동 판매되었습니다!"
    send_telegram_msg(msg_limit_done)
    
    get_trades_by_status("Wait")
    get_total_profit()