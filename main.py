"""
main.py
────────────────────────────────────────────────────────────────
3개 코인(KRW-BTC, KRW-ETH, KRW-XRP)을 multiprocessing으로
동시에 거래하는 메인 진입점.

변경 요약 (기존 main.py 대비):
  1. [신규] load_config()   : config.ini에서 코인별 설정 로드
  2. [신규] state.py 연동   : TTL 기반 거래 변수 복구/저장
  3. [신규] run(coin)       : coin을 인자로 받아 독립 실행 가능
  4. [신규] __main__ 블록   : multiprocessing.Process로 3개 코인 동시 실행
  5. [유지] 기존 거래 로직  : 매수/매도/추세 판단 로직 원본 유지
"""

import configparser
import multiprocessing
import time

from logger import setup_logger, log, log_function_call
from upbit_api import *
from trade_order import *
from trade_calculator import *
from state import load_state, save_state, clear_state
from upbit_db import init_asset_table, get_initial_asset, set_initial_asset


# ════════════════════════════════════════════════════════════════
#  설정 로드
# ════════════════════════════════════════════════════════════════

def load_config(ticker: str) -> configparser.SectionProxy:
    """
    config.ini에서 ticker에 해당하는 섹션을 읽어 반환.
    섹션에 없는 키는 [DEFAULT] 섹션의 값으로 자동 보완됩니다.

    Args:
        ticker: 코인 티커 (예: "KRW-BTC")

    Returns:
        configparser.SectionProxy — cfg["key"] 또는 cfg.getint("key") 형태로 사용
    """
    cfg = configparser.ConfigParser()
    cfg.read("config.ini", encoding="utf-8")

    if ticker not in cfg:
        log("ER", f"[config] config.ini에 [{ticker}] 섹션이 없습니다. DEFAULT값 사용.")
        # DEFAULT 섹션은 항상 존재하므로 임시 섹션으로 대체
        cfg[ticker] = {}

    return cfg[ticker]


# ════════════════════════════════════════════════════════════════
#  메인 거래 루프
# ════════════════════════════════════════════════════════════════

def run(coin: str) -> None:
    """
    단일 코인에 대한 전체 거래 루프.
    multiprocessing.Process의 target으로 호출됩니다.

    Args:
        coin: 거래할 코인 티커 (예: "KRW-BTC")
    """

    # ── ① 로거 초기화 (프로세스별 독립 로그 파일) ───────────────
    # 반드시 run() 최상단에서 호출해야 합니다.
    # 이 시점 이후의 모든 log() 호출은 코인별 파일에 기록됩니다.
    # 예: data/logs/scalper_KRW_BTC.20240520
    setup_logger(coin)

    # ── ③ 설정 로드 (config.ini) ───────────────────────────────
    cfg = load_config(coin)

    start_money      = None              # DB에서 로드 (아래에서 설정)
    last_sell_order  = cfg.getint  ("last_sell_order",  10)
    profitPer        = cfg.getfloat("profit_per",       1.06)
    sell_profit_rate = cfg.getfloat("sell_profit_rate", 1.03)
    days_short       = cfg.getint  ("days_short",       3)
    days_long        = cfg.getint  ("days_long",        20)
    buy_timer_limit  = cfg.getint  ("buy_timer_limit",  3)
    min_sell_amount  = cfg.getint  ("min_sell_amount",  6000)

    log("INFO", f"[{coin}] 설정 로드 완료",
        f"start_money={start_money}", f"days_short={days_short}", f"days_long={days_long}")

    # ── ④ 초기 시장 데이터 조회 ────────────────────────────────
    cur_cash  = GET_CASH(coin)
    cur_price = GET_CUR_PRICE(coin)
    cur_coin  = GET_QUAN_COIN(coin)
    one_tick  = calculate_tick_unit(cur_price)

    if cur_cash < 1:
        log("DG", f"[{coin}] GET_CASH() Error", str(cur_cash))
        time.sleep(10)
        return

    # ── ⑤ 초기 기준 자산 로드 (DB) ────────────────────────────
    #
    #  [동작 방식]
    #  DB에 ticker 레코드 있음 → initial_money를 start_money로 사용
    #  DB에 ticker 레코드 없음 → 현재 지갑 총액을 start_money로 계산 후 DB에 INSERT
    #
    #  수동 리셋 방법:
    #    from upbit_db import reset_initial_asset
    #    reset_initial_asset("KRW-BTC")
    #  → 다음 봇 시작 시 그 시점 잔고 기준으로 재설정됨
    #
    start_money = get_initial_asset(coin)

    if start_money is None:
        # 최초 실행 — 현재 지갑 총액을 기준 자산으로 DB에 기록
        start_money = round(cur_cash + (cur_coin * cur_price))
        inserted = set_initial_asset(coin, start_money)
        if inserted:
            log("INFO", f"[{coin}] 초기 기준 자산 DB 저장 완료: {start_money} KRW")
        else:
            log("ER", f"[{coin}] 초기 기준 자산 DB 저장 실패 — 로컬 값으로 계속 진행")
    else:
        log("INFO", f"[{coin}] 초기 기준 자산 DB 로드 완료: {start_money} KRW")

    # ── ⑥ 상태 복구 (state.py TTL 검사) ───────────────────────
    #
    #  [복구 우선순위]
    #  saved buy_price > 0  → 이전 매수가 복구 (재시작 2시간 이내)
    #  saved buy_price == 0 → 현재가 기준 새로 계산 (최초 시작 또는 TTL 만료)
    #
    state          = load_state(coin)
    rise_chk       = state["rise_chk"]
    chk_15m_timer  = state["chk_15m_timer"]
    chk_sell_order = state["chk_sell_order"]
    # 재시작 후 복구 시 타이머 기준 시각도 함께 복구.
    # 저장된 값이 0.0(최초 시작)이면 현재 시각으로 초기화.
    timer_15m_start = state["timer_15m_start"] or time.time()

    if state["buy_price"] > 0:
        # 이전 상태 복구
        buy_price  = state["buy_price"]
        sell_price = state["sell_price"]
        log("INFO", f"[{coin}] 거래 상태 복구 완료",
            f"buy_price={buy_price}", f"sell_price={sell_price}")
    else:
        # 초기값 계산
        buy_price = cur_price - (one_tick * 3)
        if cur_coin * cur_price >= min_sell_amount:
            sell_price = round(GET_BUY_AVG(coin) * sell_profit_rate)
            log("DG", f"[{coin}] Initial Sell Price: {sell_price}",
                f"Current Coin Qty: {cur_coin}")
        else:
            sell_price = 0.0

    buy_amount = calculate_trade_unit(cur_cash)

    log("INFO", f"[{coin}] Cur Price: {cur_price}", f"One Tick: {one_tick}",
        f"Buy Price: {buy_price}", f"Buy Amount: {buy_amount}")

    if buy_amount == 0:
        log("DG", f"[{coin}] calculate_trade_unit() Error")
        time.sleep(10)
        return

    before_buy_price = buy_price    # -아직 미사용-

    # ── ⑥ 거래 루프 ────────────────────────────────────────────
    chk_run = 1
    timer_15m_start = time.time()   # [FIX] 15분 타이머 기준 시각 (분 단위 % 방식 → time.time() 방식으로 변경)
    time.sleep(1)

    while chk_run == 1:

        # 현재 보유 현금이 0원인 경우 → 업비트 통신 오류로 판단, 10초 후 재시도
        cur_cash = GET_CASH(coin)
        if cur_cash == 0:
            log("DG", f"[{coin}] The balance is confirmed as $0.")
            time.sleep(10)
            continue

        # 현재 코인 가격이 0원인 경우 → 업비트 통신 오류로 판단, 10초 후 재시도
        cur_price = GET_CUR_PRICE(coin)
        if cur_price == 0:
            log("DG", f"[{coin}] Current Price smaller than 1.")
            time.sleep(10)
            continue

        one_tick = calculate_tick_unit(cur_price)
        cur_coin = GET_QUAN_COIN(coin)

        if cur_coin * cur_price <= one_tick:
            sell_price = 0.0

        # 보유 현금이 최솟값 미만이면 매수 중지
        min_cash = round((cur_cash + (cur_coin * cur_price)) * last_sell_order / 100)

        if cur_cash < min_cash:
            log("DG", f"[{coin}] Cash on hand is too low.")

        # 15분 타이머 초기화
        # [FIX] 기존: int(time.strftime("%M")) % 15 == 0
        #   → 루프 주기(10초)와 분의 경계가 맞지 않아 초기화가 누락되거나
        #     같은 분 안에서 중복 초기화될 수 있음
        # 변경: 마지막 초기화 시각으로부터 900초(15분) 경과 여부로 판단
        if chk_15m_timer != 0:
            if time.time() - timer_15m_start >= 900:
                log("INFO", f"[{coin}] Check Timer reset")
                chk_15m_timer   = 0
                timer_15m_start = time.time()   # 기준 시각 갱신

        # ── 매수/매도 구간 ──────────────────────────────────────
        if cur_cash > min_cash:
            try:
                wallet = round(cur_cash + (cur_coin * cur_price))
                log("DG", f"[{coin}] WALLET: {wallet}",
                    f"ACCOUNT: {round(cur_cash)}",
                    f"COIN_{coin}: {cur_coin}")

                # 추세 판단
                trend = GET_MARKET_TREND(coin, cur_price, days_short, days_long)
                if trend in ("up", "run-up"):
                    log("DG", f"[{coin}] Trend={trend}. Resetting buy price.")
                    rise_chk = 1

                if rise_chk == 1:
                    buy_price = cur_price - (one_tick * 3)
                    log("INFO", f"[{coin}] One Tick: {one_tick}",
                        f"Cur Price: {cur_price}", f"Buy Price: {buy_price}")
                    rise_chk = 0

                log("DG", f"[{coin}] CUR_PRICE: {cur_price}", f"BUY_PRICE: {buy_price}")

                # 시장가 매수
                if cur_price < buy_price:
                    log("INFO", f"[{coin}] One Tick: {one_tick}", f"Cur Price: {cur_price}")
                    if chk_15m_timer > buy_timer_limit:
                        buy_price = cur_price - (one_tick * 3)
                        log("DG", f"[{coin}] Purchased more than {buy_timer_limit} times in 15 minutes.")
                    else:
                        res = ORDER_BUY_MARKET(coin, buy_amount)
                        time.sleep(1)

                        if res != 0:
                            chk_15m_timer += 1
                            log("INFO", f"[{coin}] Check Timer: {chk_15m_timer}")
                            buy_price  = cur_price - (one_tick * 3)
                            sell_price = round(GET_BUY_AVG(coin) * sell_profit_rate)
                            log("DG", f"[{coin}] BUY ORDER: {cur_price}",
                                f"AMOUNT: {buy_amount}")

                log("DG", f"[{coin}] CUR_PRICE: {cur_price}", f"SELL_PRICE: {sell_price}")

                # 시장가 매도
                if cur_price >= sell_price and (cur_coin * cur_price) > min_sell_amount:
                    res = ORDER_SELL_MARKET(coin)
                    time.sleep(1)

                    if res != 0:
                        sell_amount = res['executed_volume']
                        log("DG", f"[{coin}] SELL ORDER: {sell_price}",
                            f"AMOUNT: {sell_amount}")
                        sell_price = 0.0

                margin  = round(wallet - start_money)
                margins = round((margin / start_money) * 100, 2)
                log("DG", f"[{coin}] Initial Money: {start_money}",
                    f"Margin: {margin} ({margins}%)")

            except Exception as e:
                log("DG", f"[{coin}] Margin CALC Fail", e)

        else:   # 현금 부족 → 지정가 매도 주문 후 대기
            try:
                order_info = GET_ORDER_INFO(coin)

                if order_info == 2:     # 주문 없음 → 지정가 매도 주문
                    last_order_res = ORDER_SELL_LIMIT(coin, profitPer)
                    log("INFO", f"[{coin}] Last Sell Order Result: {last_order_res}")
                elif order_info == 0:   # 조회 실패
                    log("DG", f"[{coin}] Fail to GET ORDER INFO")
                    time.sleep(5)
                    continue
                else:
                    order_info     = GET_ORDER_INFO(coin).split('&')
                    last_order_res = 1

                if last_order_res == 1:
                    log("DG", f"[{coin}] Last Order Success: {last_order_res}")
                    log("DG", f"[{coin}] UUID  : {order_info[0]}")
                    log("DG", f"[{coin}] PRICE : {order_info[2]}")
                    log("DG", f"[{coin}] VOLUME: {order_info[3]}")
                    chk_sell_order = 1
                    time.sleep(10)
                else:
                    log("DG", f"[{coin}] Last Order Fail: {last_order_res}")
                    continue

            except Exception as e:
                log("DG", f"[{coin}] Fail", e)

        # ── 매도 완료 대기 루프 ─────────────────────────────────
        while chk_sell_order == 1:
            try:
                tmp = GET_ORDER_INFO(coin)

                if tmp == 2:            # 주문 정보 없음 → 완료 처리
                    chk_sell_order = 0
                    break
                elif tmp == 0:          # 조회 실패
                    log("DG", f"[{coin}] Fail: GET ORDER INFO Return")
                    chk_sell_order = 0
                    time.sleep(10)
                    continue
                else:
                    order_info = tmp.split('&')

                order_uuid   = order_info[0]
                order_status = GET_ORDER_STATE(order_uuid)

                if order_status == 'wait':
                    log("DG", f"[{coin}] Cur Price: {GET_CUR_PRICE(coin)}",
                        f"Sell price: {order_info[2]}")
                    log("DG", f"[{coin}] Sell Order Status: {order_status}")
                else:
                    log("DG", f"[{coin}] Sell Order Status: {order_status}")
                    chk_run        = 0
                    chk_sell_order = 0

                time.sleep(60)

            except Exception as e:
                log("DG", f"[{coin}] Fail", e)
                chk_run        = 2
                chk_sell_order = 0

        # ── ⑦ 상태 저장 (매 사이클 종료 시) ───────────────────
        save_state(coin, {
            "buy_price":        buy_price,
            "sell_price":       sell_price,
            "rise_chk":         rise_chk,
            "chk_15m_timer":    chk_15m_timer,
            "chk_sell_order":   chk_sell_order,
            "timer_15m_start":  timer_15m_start,
        })

        time.sleep(10)

    # ── 정상 종료 처리 ──────────────────────────────────────────
    if chk_run == 2:
        clear_state(coin)
        log("DG", f"[{coin}] Trade Exit.")


# ════════════════════════════════════════════════════════════════
#  진입점 — 3개 코인을 독립 프로세스로 동시 실행
# ════════════════════════════════════════════════════════════════

# 거래할 코인 목록 (config.ini 섹션명과 일치해야 합니다)
COINS = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]

if __name__ == '__main__':
    # 메인 프로세스 자체 로그는 scalper_SYSTEM.YYYYMMDD 에 기록
    setup_logger("SYSTEM")

    # initial_asset 테이블이 없으면 자동 생성
    init_asset_table()

    processes = []

    for coin in COINS:
        p = multiprocessing.Process(
            target=run,
            args=(coin,),
            name=coin,          # 프로세스 이름 = 티커 (로그/디버깅 식별용)
            daemon=True,        # 메인 프로세스 종료 시 자식 프로세스도 함께 종료
        )
        p.start()
        log("INFO", f"[main] 프로세스 시작: {coin} (PID: {p.pid})")
        processes.append(p)

    # 모든 자식 프로세스가 종료될 때까지 메인 프로세스 대기
    for p in processes:
        p.join()
        log("INFO", f"[main] 프로세스 종료: {p.name} (exitcode: {p.exitcode})")