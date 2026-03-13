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
import importlib.util
import multiprocessing
import time

from logger import setup_logger, log, log_function_call
from upbit_api import *
from trade_order import *
from trade_calculator import *
from upbit_db import init_tables, get_initial_asset, set_initial_asset, insert_trade_history
from mod_telegram import send_buy_alert, send_sell_alert, send_monitor_report, send_error_alert

# ── config/state.py 절대 경로 import ────────────────────────
_state_spec   = importlib.util.spec_from_file_location(
    "state",
    "/home/mini_trade/trading_bot/config/state.py"
)
_state_module = importlib.util.module_from_spec(_state_spec)
_state_spec.loader.exec_module(_state_module)

load_state  = _state_module.load_state
save_state  = _state_module.save_state
clear_state = _state_module.clear_state


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
    cfg = configparser.RawConfigParser(inline_comment_prefixes=(";", "#"))
    cfg.read("/home/mini_trade/trading_bot/config/config.ini", encoding="utf-8")

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
    chk_15m_timer  = state["chk_15m_timer"]
    chk_sell_order = state["chk_sell_order"]
    timer_15m_start = state["timer_15m_start"] or time.time()
    timer_3h_start  = state["timer_3h_start"]  or time.time()

    if state["buy_price"] > 0:
        # 이전 상태 복구
        buy_price  = state["buy_price"]
        sell_price = state["sell_price"]

        # [FIX] sell_price가 0인데 보유 코인이 있으면 재계산
        # state에 sell_price=0이 저장된 채 재시작되면 매도 기회를 영원히 놓침
        if sell_price == 0.0 and cur_coin * cur_price >= min_sell_amount:
            sell_price = round(GET_BUY_AVG(coin) * sell_profit_rate)
            log("INFO", f"[{coin}] 거래 상태 복구 완료 (sell_price 재계산)",
                f"buy_price={buy_price}", f"sell_price={sell_price}")
        else:
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

    # ── ⑦ 거래 루프 ────────────────────────────────────────────
    chk_run         = 1
    timer_15m_start = time.time()
    timer_3h_start  = time.time()   # 3시간 모니터링 리포트 타이머
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

        if cur_coin * cur_price <= min_sell_amount:
            sell_price = 0.0

        # 보유 현금이 최솟값 미만이면 매수 중지
        min_cash = round((cur_cash + (cur_coin * cur_price)) * last_sell_order / 100)

        if cur_cash < min_cash:
            log("DG", f"[{coin}] Cash on hand is too low.")

        # 15분 타이머 초기화
        if chk_15m_timer != 0:
            if time.time() - timer_15m_start >= 900:
                log("INFO", f"[{coin}] Check Timer reset")
                chk_15m_timer   = 0
                timer_15m_start = time.time()

        # 3시간 모니터링 리포트 전송
        if time.time() - timer_3h_start >= 10800:
            try:
                _wallet  = round(cur_cash + (cur_coin * cur_price))
                _profit  = _wallet - start_money
                _prate   = round((_profit / start_money) * 100, 2) if start_money else 0
                _trend   = GET_MARKET_TREND(coin, cur_price, days_short, days_long)
                send_monitor_report([{
                    "ticker":      coin,
                    "cur_price":   cur_price,
                    "buy_price":   buy_price,
                    "sell_price":  sell_price,
                    "cur_coin":    cur_coin,
                    "cur_cash":    cur_cash,
                    "trend":       _trend,
                    "wallet":      _wallet,
                    "profit":      _profit,
                    "profit_rate": _prate,
                }])
                log("INFO", f"[{coin}] 3시간 모니터링 리포트 전송 완료")
            except Exception as e:
                log("ER", f"[{coin}] 모니터링 리포트 전송 실패: {e}")
            finally:
                timer_3h_start = time.time()    # 성공/실패 무관하게 타이머 갱신

        # ── 매수/매도 구간 ──────────────────────────────────────
        if cur_cash > min_cash:
            try:
                wallet = round(cur_cash + (cur_coin * cur_price))
                log("DG", f"[{coin}] WALLET: {wallet}",
                    f"ACCOUNT: {round(cur_cash)}",
                    f"COIN_{coin}: {cur_coin}")

                # ── 추세 판단 및 buy_price 재설정 ─────────────
                # trend == "up" / "run-up" : 가격이 올랐으므로
                #   buy_price를 현재가 기준으로 다시 내려 설정 후 대기
                # trend == "down"          : buy_price 유지,
                #   cur_price < buy_price 이면 매수 진행
                trend = GET_MARKET_TREND(coin, cur_price, days_short, days_long)
                log("DG", f"[{coin}] Trend={trend}")

                if trend in ("up", "run-up"):
                    # [FIX] rise_chk 플래그 제거 — 조건 충족 시 즉시 재설정
                    buy_price = cur_price - (one_tick * 3)
                    log("INFO", f"[{coin}] Trend={trend} → buy_price reset",
                        f"One Tick: {one_tick}",
                        f"Cur Price: {cur_price}",
                        f"New Buy Price: {buy_price}")

                log("DG", f"[{coin}] CUR_PRICE: {cur_price}", f"BUY_PRICE: {buy_price}")

                # ── 시장가 매수 ────────────────────────────────
                # 조건: trend == "down" 이고 cur_price < buy_price
                # [FIX] 매수 실행 후 did_buy 플래그를 세워
                #       같은 사이클에 매도가 연속 실행되는 것을 방지
                did_buy = False
                if trend == "down" and cur_price < buy_price:
                    log("INFO", f"[{coin}] Buy condition met.",
                        f"One Tick: {one_tick}", f"Cur Price: {cur_price}")
                    if chk_15m_timer > buy_timer_limit:
                        buy_price = cur_price - (one_tick * 3)
                        log("DG", f"[{coin}] Purchased more than {buy_timer_limit} times in 15 minutes.")
                    else:
                        res = ORDER_BUY_MARKET(coin, buy_amount)
                        time.sleep(1)

                        if res != 0:
                            # ── 체결 완료 후 상세 정보 조회 ────────
                            order_uuid   = res.get("uuid", "")
                            order_detail = GET_ORDER_DETAIL(order_uuid) if order_uuid else None

                            if order_detail is None:
                                # 주문 취소(cancel) 또는 타임아웃 → 체결 안 됨
                                log("INFO", f"[{coin}] BUY ORDER cancelled or timeout — sell_price 갱신 skip")
                            else:
                                did_buy       = True
                                chk_15m_timer += 1
                                log("INFO", f"[{coin}] Check Timer: {chk_15m_timer}")
                                buy_price     = cur_price - (one_tick * 3)
                                new_avg       = GET_BUY_AVG(coin)
                                sell_price    = round(new_avg * sell_profit_rate)
                                wallet_after  = round(GET_CASH(coin) + (GET_QUAN_COIN(coin) * cur_price))

                                buy_amount_f = float(order_detail.get("executed_volume", 0))
                                fee          = float(order_detail.get("paid_fee", 0))
                                buy_total    = round(float(order_detail.get("price", cur_price)) * buy_amount_f) if buy_amount_f else buy_amount

                                log("INFO", f"[{coin}] BUY FILLED",
                                    f"volume={buy_amount_f}",
                                    f"fee={fee}",
                                    f"total={buy_total}")

                                # ── DB 거래 이력 기록 ──────────────────
                                insert_trade_history(
                                    ticker        = coin,
                                    side          = "BUY",
                                    price         = cur_price,
                                    amount        = buy_amount_f,
                                    total         = buy_total,
                                    fee           = fee,
                                    avg_buy_price = round(new_avg),
                                    profit        = 0,
                                    profit_rate   = 0.0,
                                    wallet_before = wallet,
                                    wallet_after  = wallet_after,
                                )

                                # ── 텔레그램 매수 알림 ─────────────────
                                send_buy_alert(
                                    ticker        = coin,
                                    price         = cur_price,
                                    amount        = buy_amount_f,
                                    total         = buy_total,
                                    avg_buy_price = round(new_avg),
                                    wallet_before = wallet,
                                    wallet_after  = wallet_after,
                                )

                                log("DG", f"[{coin}] BUY ORDER: {cur_price}",
                                    f"AMOUNT: {buy_amount}")

                log("DG", f"[{coin}] CUR_PRICE: {cur_price}", f"SELL_PRICE: {sell_price}")

                # ── 시장가 매도 ────────────────────────────────
                # 조건:
                #   1. sell_price > 0 (매도가 설정된 상태)         [FIX] sell_price==0 방지
                #   2. cur_price >= sell_price
                #   3. 보유 코인 평가금액 > min_sell_amount
                #   4. 이번 사이클에 매수가 실행되지 않았을 것       [FIX] 연속 매수+매도 방지
                if (
                    not did_buy
                    and sell_price > 0
                    and cur_price >= sell_price
                    and (cur_coin * cur_price) > min_sell_amount
                ):
                    res = ORDER_SELL_MARKET(coin)
                    time.sleep(1)

                    if res != 0:
                        # ── 체결 완료 후 상세 정보 조회 ────────────
                        order_uuid   = res.get("uuid", "")
                        order_detail = GET_ORDER_DETAIL(order_uuid) if order_uuid else None

                        if order_detail:
                            sell_amount = float(order_detail.get("executed_volume", 0))
                            fee         = float(order_detail.get("paid_fee", 0))
                            sell_total  = round(float(order_detail.get("price", cur_price)) * sell_amount) if sell_amount else 0
                        else:
                            sell_amount = float(res.get("executed_volume", 0))
                            fee         = float(res.get("paid_fee", 0))
                            sell_total  = 0

                        avg_buy      = GET_BUY_AVG(coin)
                        wallet_after = round(GET_CASH(coin) + (GET_QUAN_COIN(coin) * cur_price))
                        profit       = round(sell_total - (avg_buy * sell_amount) - fee)
                        profit_rate  = round((profit / (avg_buy * sell_amount)) * 100, 2) if avg_buy and sell_amount else 0.0

                        log("INFO", f"[{coin}] SELL FILLED",
                            f"volume={sell_amount}",
                            f"fee={fee}",
                            f"total={sell_total}",
                            f"profit={profit}")

                        # ── DB 거래 이력 기록 ──────────────────────
                        insert_trade_history(
                            ticker        = coin,
                            side          = "SELL",
                            price         = cur_price,
                            amount        = sell_amount,
                            total         = sell_total,
                            fee           = fee,
                            avg_buy_price = round(avg_buy),
                            profit        = profit,
                            profit_rate   = profit_rate,
                            wallet_before = wallet,
                            wallet_after  = wallet_after,
                        )

                        # ── 텔레그램 매도 알림 ─────────────────────
                        send_sell_alert(
                            ticker        = coin,
                            price         = cur_price,
                            amount        = sell_amount,
                            total         = sell_total,
                            avg_buy_price = round(avg_buy),
                            profit        = profit,
                            profit_rate   = profit_rate,
                            wallet_before = wallet,
                            wallet_after  = wallet_after,
                        )

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
            "chk_15m_timer":    chk_15m_timer,
            "chk_sell_order":   chk_sell_order,
            "timer_15m_start":  timer_15m_start,
            "timer_3h_start":   timer_3h_start,
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

    # initial_asset, trade_history 테이블 없으면 자동 생성
    init_tables()

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