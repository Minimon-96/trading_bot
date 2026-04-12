"""
main.py
────────────────────────────────────────────────────────────────
3개 코인(KRW-BTC, KRW-ETH, KRW-XRP)을 multiprocessing으로
동시에 거래하는 메인 진입점.

[이번 수정 사항]
  1. calculate_trade_unit(cash, buy_count=chk_15m_timer) 연동
     → 매수 횟수에 따라 등비수열(RATIO≈1.0416)로 매수금 자동 증가
  2. 40회(MAX_BUY) 도달 시 지정가 매도(ORDER_SELL_LIMIT) 자동 전환
     → 평균매수가 × 1.06 가격으로 지정가 매도 주문
     → 텔레그램으로 "40회 도달 → 지정가 매도 전환" 알림 전송
     → chk_sell_order = 1 로 매도 완료 대기 루프 진입
  3. buy_amount 산출 시 buy_count(=chk_15m_timer) 를 함께 전달
"""

import configparser
import importlib.util
import multiprocessing
import time

from logger import setup_logger, log, log_function_call
from upbit_api import *
from trade_order import *
from trade_calculator import calculate_trade_unit, calculate_tick_unit, MAX_BUY
from upbit_db import init_tables, get_initial_asset, set_initial_asset, insert_trade_history
from mod_telegram import (send_buy_alert, send_sell_alert,
                           send_monitor_report, send_error_alert,
                           send_telegram_msg)

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
    cfg = configparser.RawConfigParser(inline_comment_prefixes=(";", "#"))
    cfg.read("/home/mini_trade/trading_bot/config/config.ini", encoding="utf-8")

    if ticker not in cfg:
        log("ER", f"[config] config.ini에 [{ticker}] 섹션이 없습니다. DEFAULT값 사용.")
        cfg[ticker] = {}

    return cfg[ticker]


# ════════════════════════════════════════════════════════════════
#  3시간 모니터링 리포트 헬퍼
# ════════════════════════════════════════════════════════════════

def _try_send_monitor(coin, cur_price, buy_price, sell_price,
                      cur_coin, cur_cash, start_money,
                      days_short, days_long,
                      split_count: int = 0,
                      buy_count: int = 0,
                      sell_count: int = 0):
    """
    3시간 모니터링 리포트 전송.
    메인 루프 / 매도 대기 루프 양쪽에서 호출.

    Args:
        split_count: 현재 미청산 분할매수 횟수 (chk_15m_timer)
        buy_count:   봇 시작 후 누적 매수 체결 횟수
        sell_count:  봇 시작 후 누적 매도 체결 횟수
    """
    try:
        _wallet = round(cur_cash + (cur_coin * cur_price))
        _profit = _wallet - start_money
        _prate  = round((_profit / start_money) * 100, 2) if start_money else 0
        _trend  = GET_MARKET_TREND(coin, cur_price, days_short, days_long)
        _avg    = GET_BUY_AVG(coin)
        send_monitor_report([{
            "ticker":        coin,
            "cur_price":     cur_price,
            "avg_buy_price": round(_avg) if _avg else 0,
            "buy_price":     buy_price,
            "sell_price":    sell_price,
            "cur_coin":      cur_coin,
            "cur_cash":      cur_cash,
            "trend":         _trend,
            "wallet":        _wallet,
            "profit":        _profit,
            "profit_rate":   _prate,
            "split_count":   split_count,
            "buy_count":     buy_count,
            "sell_count":    sell_count,
        }])
        log("INFO", f"[{coin}] 3시간 모니터링 리포트 전송 완료 "
            f"(분할 {split_count}/{MAX_BUY}회 | 누적 매수 {buy_count}회 / 매도 {sell_count}회)")
    except Exception as e:
        log("ER", f"[{coin}] 모니터링 리포트 전송 실패: {e}")


# ════════════════════════════════════════════════════════════════
#  40회 도달 → 지정가 매도 전환 헬퍼
# ════════════════════════════════════════════════════════════════

def _trigger_max_buy_limit_sell(coin: str, profit_per: float) -> int:
    """
    분할매수 40회(MAX_BUY) 도달 시 호출.
    평균매수가 × profit_per 가격으로 지정가 매도 주문을 넣고
    텔레그램으로 상황을 알립니다.

    Args:
        coin:       코인 티커
        profit_per: 지정가 배율 (예: 1.06 = 평균매수가 +6%)

    Returns:
        1  — 지정가 매도 주문 성공
        0  — 실패
    """
    try:
        avg   = GET_BUY_AVG(coin)
        limit = round(avg * profit_per)
        res   = ORDER_SELL_LIMIT(coin, profit_per)

        msg = (
            f"🚨 *[{coin}] 분할매수 {MAX_BUY}회 도달 — 지정가 매도 전환*\n"
            f"평균매수가 : `{round(avg):>15,} KRW`\n"
            f"지정매도가 : `{limit:>15,} KRW`  (+{round((profit_per-1)*100)}%)\n"
            f"주문결과   : `{res}`"
        )
        send_telegram_msg(msg)
        log("INFO", f"[{coin}] MAX_BUY({MAX_BUY}회) 도달 → 지정가 매도",
            f"avg={round(avg)}", f"limit={limit}", f"res={res}")

        return 1 if res == 1 else 0

    except Exception as e:
        log("ER", f"[{coin}] _trigger_max_buy_limit_sell 실패: {e}")
        send_error_alert(coin, f"MAX_BUY 지정가 매도 실패", e)
        return 0


# ════════════════════════════════════════════════════════════════
#  메인 거래 루프
# ════════════════════════════════════════════════════════════════

def run(coin: str) -> None:
    """
    단일 코인에 대한 전체 거래 루프.
    multiprocessing.Process의 target으로 호출됩니다.
    """

    # ── ① 로거 초기화 ────────────────────────────────────────
    setup_logger(coin)

    # ── ② 설정 로드 ──────────────────────────────────────────
    cfg = load_config(coin)

    last_sell_order  = cfg.getint  ("last_sell_order",  10)
    profitPer        = cfg.getfloat("profit_per",       1.06)   # 지정가 매도 배율
    sell_profit_rate = cfg.getfloat("sell_profit_rate", 1.03)
    days_short       = cfg.getint  ("days_short",       3)
    days_long        = cfg.getint  ("days_long",        20)
    min_sell_amount  = cfg.getint  ("min_sell_amount",  6_000)

    # [변경] buy_timer_limit 제거 — MAX_BUY(40회)가 상한 역할을 대신함
    # config.ini에 buy_timer_limit 항목이 있어도 무시됩니다.

    log("INFO", f"[{coin}] 설정 로드 완료",
        f"days_short={days_short}", f"days_long={days_long}",
        f"profitPer={profitPer}", f"MAX_BUY={MAX_BUY}")

    # ── ③ 초기 시장 데이터 조회 ──────────────────────────────
    cur_cash  = GET_CASH(coin)
    cur_price = GET_CUR_PRICE(coin)
    cur_coin  = GET_QUAN_COIN(coin)
    one_tick  = calculate_tick_unit(cur_price)

    if cur_cash < 1:
        log("DG", f"[{coin}] GET_CASH() Error", str(cur_cash))
        time.sleep(10)
        return

    # ── ④ 초기 기준 자산 로드 (DB) ───────────────────────────
    start_money = get_initial_asset(coin)

    if start_money is None:
        start_money = round(cur_cash + (cur_coin * cur_price))
        inserted = set_initial_asset(coin, start_money)
        if inserted:
            log("INFO", f"[{coin}] 초기 기준 자산 DB 저장 완료: {start_money} KRW")
        else:
            log("ER", f"[{coin}] 초기 기준 자산 DB 저장 실패 — 로컬 값으로 계속 진행")
    else:
        log("INFO", f"[{coin}] 초기 기준 자산 DB 로드 완료: {start_money} KRW")

    # ── ⑤ 상태 복구 ──────────────────────────────────────────
    state           = load_state(coin)
    chk_15m_timer   = state["chk_15m_timer"]    # 현재 미청산 분할매수 횟수
    chk_sell_order  = state["chk_sell_order"]
    timer_15m_start = state["timer_15m_start"] or time.time()
    timer_3h_start  = state["timer_3h_start"]  or time.time()
    buy_count       = state["buy_count"]        # 누적 매수 체결 횟수 (TTL 무관 유지)
    sell_count      = state["sell_count"]       # 누적 매도 체결 횟수 (TTL 무관 유지)

    if state["buy_price"] > 0:
        buy_price  = state["buy_price"]
        sell_price = state["sell_price"]
        if sell_price == 0.0 and cur_coin * cur_price >= min_sell_amount:
            sell_price = round(GET_BUY_AVG(coin) * sell_profit_rate)
            log("INFO", f"[{coin}] 거래 상태 복구 완료 (sell_price 재계산)",
                f"buy_price={buy_price}", f"sell_price={sell_price}",
                f"buy_count={chk_15m_timer}")
        else:
            log("INFO", f"[{coin}] 거래 상태 복구 완료",
                f"buy_price={buy_price}", f"sell_price={sell_price}",
                f"buy_count={chk_15m_timer}")
    else:
        buy_price = cur_price - (one_tick * 3)
        if cur_coin * cur_price >= min_sell_amount:
            sell_price = round(GET_BUY_AVG(coin) * sell_profit_rate)
        else:
            sell_price = 0.0

    # ── ⑥ 거래 루프 ──────────────────────────────────────────
    chk_run        = 1
    timer_3h_start = time.time()
    time.sleep(1)

    while chk_run == 1:

        # ── 현재 잔고 및 가격 조회 ────────────────────────────
        cur_cash = GET_CASH(coin)
        if cur_cash == 0:
            log("DG", f"[{coin}] The balance is confirmed as $0.")
            time.sleep(10)
            continue

        cur_price = GET_CUR_PRICE(coin)
        if cur_price == 0:
            log("DG", f"[{coin}] Current Price smaller than 1.")
            time.sleep(10)
            continue

        one_tick = calculate_tick_unit(cur_price)
        cur_coin = GET_QUAN_COIN(coin)

        # [변경] buy_count(=chk_15m_timer)를 함께 전달해 회차별 매수금 산출
        buy_amount = calculate_trade_unit(cur_cash, buy_count=chk_15m_timer)

        if cur_coin * cur_price <= min_sell_amount:
            sell_price = 0.0

        min_cash = round((cur_cash + (cur_coin * cur_price)) * last_sell_order / 100)

        if cur_cash < min_cash:
            log("DG", f"[{coin}] Cash on hand is too low.")

        # ── 3시간 모니터링 리포트 ────────────────────────────
        if time.time() - timer_3h_start >= 10_800:
            _try_send_monitor(coin, cur_price, buy_price, sell_price,
                              cur_coin, cur_cash, start_money,
                              days_short, days_long,
                              split_count=chk_15m_timer,
                              buy_count=buy_count,
                              sell_count=sell_count)
            timer_3h_start = time.time()

        # ════════════════════════════════════════════════════
        #  [신규] 40회(MAX_BUY) 도달 감지 → 지정가 매도 전환
        #
        #  조건:
        #    1. chk_15m_timer >= MAX_BUY  (40회 이상 매수 완료)
        #    2. 보유 코인 평가금 > min_sell_amount  (매도 가능 수량 있음)
        #    3. chk_sell_order == 0  (이미 대기 중인 주문 없음)
        #
        #  동작:
        #    - ORDER_SELL_LIMIT(coin, profitPer=1.06) 호출
        #    - 텔레그램 "40회 도달 → 지정가 매도" 알림
        #    - chk_sell_order = 1 로 세팅 → 매도 완료 대기 루프 진입
        # ════════════════════════════════════════════════════
        if (chk_15m_timer >= MAX_BUY
                and cur_coin * cur_price > min_sell_amount
                and chk_sell_order == 0):

            log("INFO", f"[{coin}] 분할매수 {MAX_BUY}회 도달 → 지정가 매도 전환 시작")
            result = _trigger_max_buy_limit_sell(coin, profitPer)

            if result == 1:
                chk_sell_order  = 1
                chk_15m_timer   = 0     # 매수 카운터 초기화 (매도 완료 후 재시작 대비)
                timer_15m_start = time.time()
                log("INFO", f"[{coin}] 지정가 매도 주문 완료 — 체결 대기 루프 진입")
            else:
                log("ER", f"[{coin}] 지정가 매도 주문 실패 — 다음 사이클 재시도")
                time.sleep(10)
                continue

        # ── 매수 / 매도 구간 ──────────────────────────────────
        elif cur_cash > min_cash:
            try:
                wallet = round(cur_cash + (cur_coin * cur_price))
                log("DG", f"[{coin}] WALLET: {wallet}",
                    f"ACCOUNT: {round(cur_cash)}",
                    f"COIN_{coin}: {cur_coin}",
                    f"BUY_COUNT: {chk_15m_timer}/{MAX_BUY}")

                trend = GET_MARKET_TREND(coin, cur_price, days_short, days_long)
                log("DG", f"[{coin}] Trend={trend}")

                if trend in ("up", "run-up"):
                    buy_price = cur_price - (one_tick * 3)
                    log("INFO", f"[{coin}] Trend={trend} → buy_price reset",
                        f"One Tick: {one_tick}",
                        f"Cur Price: {cur_price}",
                        f"New Buy Price: {buy_price}")

                log("DG", f"[{coin}] CUR_PRICE: {cur_price}", f"BUY_PRICE: {buy_price}")

                # ── 시장가 매수 ──────────────────────────────
                did_buy = False

                if trend == "down" and cur_price < buy_price:
                    log("INFO", f"[{coin}] Buy condition met.",
                        f"One Tick: {one_tick}",
                        f"Cur Price: {cur_price}",
                        f"buy_count: {chk_15m_timer}/{MAX_BUY}",
                        f"buy_amount: {buy_amount:,}원")

                    if buy_amount == 0:
                        # MAX_BUY 초과 또는 잔고 부족 — 이 분기는
                        # 위의 MAX_BUY 감지 블록이 먼저 처리하므로
                        # 여기서는 잔고 부족 케이스만 해당
                        log("DG", f"[{coin}] buy_amount=0 — 잔고 부족으로 매수 스킵")
                    else:
                        res = ORDER_BUY_MARKET(coin, buy_amount)
                        time.sleep(1)

                        if res != 0:
                            order_uuid   = res.get("uuid", "")
                            order_detail = GET_ORDER_DETAIL(order_uuid) if order_uuid else None

                            if order_detail is None:
                                # 잔고 기반 2차 체결 검증
                                coin_qty_after = GET_QUAN_COIN(coin)
                                if coin_qty_after * cur_price >= min_sell_amount:
                                    did_buy      = True
                                    buy_price    = cur_price - (one_tick * 3)
                                    new_avg      = GET_BUY_AVG(coin)
                                    sell_price   = round(new_avg * sell_profit_rate)
                                    wallet_after = round(GET_CASH(coin) + (coin_qty_after * cur_price))
                                    buy_amount_f = coin_qty_after
                                    fee          = round(buy_amount * 0.0005, 8)
                                    buy_total    = buy_amount

                                    # [변경] 매수 성공 시 chk_15m_timer 증가
                                    if chk_15m_timer == 0:
                                        timer_15m_start = time.time()
                                        log("INFO", f"[{coin}] 분할매수 타이머 시작 (1회차)")
                                    chk_15m_timer += 1
                                    log("INFO", f"[{coin}] BUY confirmed via coin balance "
                                        f"({chk_15m_timer}/{MAX_BUY}회)",
                                        f"buy_price={buy_price}", f"sell_price={sell_price}")

                                    insert_trade_history(
                                        ticker=coin, side="BUY",
                                        price=cur_price, amount=buy_amount_f,
                                        total=buy_total, fee=fee,
                                        avg_buy_price=round(new_avg),
                                        profit=0, profit_rate=0.0,
                                        wallet_before=wallet, wallet_after=wallet_after,
                                    )
                                    send_buy_alert(
                                        ticker=coin, price=cur_price,
                                        amount=buy_amount_f, total=buy_total,
                                        avg_buy_price=round(new_avg),
                                        wallet_before=wallet, wallet_after=wallet_after,
                                        buy_count=chk_15m_timer,
                                    )
                                    buy_count += 1
                                    save_state(coin, {"buy_count": buy_count, "sell_count": sell_count})
                                else:
                                    log("INFO", f"[{coin}] BUY cancelled or timeout — skip")

                            else:
                                did_buy = True
                                if chk_15m_timer == 0:
                                    timer_15m_start = time.time()
                                    log("INFO", f"[{coin}] 분할매수 타이머 시작 (1회차)")
                                chk_15m_timer += 1
                                log("INFO", f"[{coin}] BUY FILLED "
                                    f"({chk_15m_timer}/{MAX_BUY}회)")

                                buy_price    = cur_price - (one_tick * 3)
                                new_avg      = GET_BUY_AVG(coin)
                                sell_price   = round(new_avg * sell_profit_rate)
                                wallet_after = round(GET_CASH(coin) + (GET_QUAN_COIN(coin) * cur_price))

                                buy_amount_f = float(order_detail.get("executed_volume", 0))
                                fee          = float(order_detail.get("paid_fee", 0))
                                buy_total    = round(
                                    float(order_detail.get("price", cur_price)) * buy_amount_f
                                ) if buy_amount_f else buy_amount

                                log("DG", f"volume={buy_amount_f}",
                                    f"fee={fee}", f"total={buy_total}")

                                insert_trade_history(
                                    ticker=coin, side="BUY",
                                    price=cur_price, amount=buy_amount_f,
                                    total=buy_total, fee=fee,
                                    avg_buy_price=round(new_avg),
                                    profit=0, profit_rate=0.0,
                                    wallet_before=wallet, wallet_after=wallet_after,
                                )
                                send_buy_alert(
                                    ticker=coin, price=cur_price,
                                    amount=buy_amount_f, total=buy_total,
                                    avg_buy_price=round(new_avg),
                                    wallet_before=wallet, wallet_after=wallet_after,
                                    buy_count=chk_15m_timer,
                                )
                                buy_count += 1
                                save_state(coin, {"buy_count": buy_count, "sell_count": sell_count})

                log("DG", f"[{coin}] CUR_PRICE: {cur_price}", f"SELL_PRICE: {sell_price}")

                # ── 시장가 매도 (일반 익절) ───────────────────
                if (
                    not did_buy
                    and sell_price > 0
                    and cur_price >= sell_price
                    and (cur_coin * cur_price) > min_sell_amount
                ):
                    res = ORDER_SELL_MARKET(coin)
                    time.sleep(1)

                    if res != 0:
                        order_uuid   = res.get("uuid", "")
                        order_detail = GET_ORDER_DETAIL(order_uuid) if order_uuid else None

                        if order_detail:
                            sell_amount = float(order_detail.get("executed_volume", 0))
                            fee         = float(order_detail.get("paid_fee", 0))
                            sell_total  = round(
                                float(order_detail.get("price", cur_price)) * sell_amount
                            ) if sell_amount else 0
                        else:
                            sell_amount = float(res.get("executed_volume", 0))
                            fee         = float(res.get("paid_fee", 0))
                            sell_total  = 0

                        avg_buy      = GET_BUY_AVG(coin)
                        wallet_after = round(GET_CASH(coin) + (GET_QUAN_COIN(coin) * cur_price))
                        profit       = round(sell_total - (avg_buy * sell_amount) - fee)
                        profit_rate  = round(
                            (profit / (avg_buy * sell_amount)) * 100, 2
                        ) if avg_buy and sell_amount else 0.0

                        insert_trade_history(
                            ticker=coin, side="SELL",
                            price=cur_price, amount=sell_amount,
                            total=sell_total, fee=fee,
                            avg_buy_price=round(avg_buy),
                            profit=profit, profit_rate=profit_rate,
                            wallet_before=wallet, wallet_after=wallet_after,
                        )
                        send_sell_alert(
                            ticker=coin, price=cur_price,
                            amount=sell_amount, total=sell_total,
                            avg_buy_price=round(avg_buy),
                            profit=profit, profit_rate=profit_rate,
                            wallet_before=wallet, wallet_after=wallet_after,
                            buy_count=chk_15m_timer,
                            sell_type="MARKET",
                        )
                        sell_count += 1
                        save_state(coin, {"buy_count": buy_count, "sell_count": sell_count})
                        log("DG", f"[{coin}] SELL MARKET FILLED",
                            f"profit={profit}", f"profit_rate={profit_rate}%")

                        # 일반 익절 후 카운터 초기화
                        sell_price    = 0.0
                        chk_15m_timer = 0
                        timer_15m_start = time.time()

                margin  = round(wallet - start_money)
                margins = round((margin / start_money) * 100, 2)
                log("DG", f"[{coin}] Initial Money: {start_money}",
                    f"Margin: {margin} ({margins}%)")

            except Exception as e:
                log("DG", f"[{coin}] Margin CALC Fail", e)

        else:
            # ── 현금 부족 → 기존 지정가 매도 주문 확인 ──────
            try:
                order_info = GET_ORDER_INFO(coin)

                if order_info == 2:
                    last_order_res = ORDER_SELL_LIMIT(coin, profitPer)
                    log("INFO", f"[{coin}] Last Sell Order Result: {last_order_res}")
                elif order_info == 0:
                    log("DG", f"[{coin}] Fail to GET ORDER INFO")
                    time.sleep(5)
                    continue
                else:
                    order_info     = GET_ORDER_INFO(coin).split('&')
                    last_order_res = 1

                if last_order_res == 1:
                    log("DG", f"[{coin}] Last Order Success: {last_order_res}")
                    chk_sell_order = 1
                    time.sleep(10)
                else:
                    log("DG", f"[{coin}] Last Order Fail: {last_order_res}")
                    continue

            except Exception as e:
                log("DG", f"[{coin}] Fail", e)

        # ── 매도 완료 대기 루프 ──────────────────────────────
        # 진입 경로:
        #   A. 40회 도달 → 지정가 매도 주문 후 chk_sell_order=1
        #   B. 현금 부족 → ORDER_SELL_LIMIT 후 chk_sell_order=1
        while chk_sell_order == 1:
            try:
                # 대기 중에도 3시간 리포트 체크
                cur_price_w = GET_CUR_PRICE(coin)
                if cur_price_w and time.time() - timer_3h_start >= 10_800:
                    _try_send_monitor(coin, cur_price_w, buy_price, sell_price,
                                      cur_coin, GET_CASH(coin), start_money,
                                      days_short, days_long,
                                      split_count=chk_15m_timer,
                                      buy_count=buy_count,
                                      sell_count=sell_count)
                    timer_3h_start = time.time()

                tmp = GET_ORDER_INFO(coin)

                if tmp == 2:
                    chk_sell_order = 0
                    # 매도 완료 — 카운터 초기화
                    chk_15m_timer   = 0
                    timer_15m_start = time.time()
                    log("INFO", f"[{coin}] 지정가 매도 체결 완료 — 매수 카운터 초기화")
                    break
                elif tmp == 0:
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
                        f"Sell price: {order_info[2]}",
                        f"매도 대기 중 (40회 지정가 매도)")
                else:
                    log("DG", f"[{coin}] Sell Order Status: {order_status}")
                    chk_run        = 0
                    chk_sell_order = 0

                time.sleep(60)

            except Exception as e:
                log("DG", f"[{coin}] Fail", e)
                chk_run        = 2
                chk_sell_order = 0

        # ── 상태 저장 ────────────────────────────────────────
        save_state(coin, {
            "buy_price":       buy_price,
            "sell_price":      sell_price,
            "chk_15m_timer":   chk_15m_timer,
            "chk_sell_order":  chk_sell_order,
            "timer_15m_start": timer_15m_start,
            "timer_3h_start":  timer_3h_start,
            "buy_count":       buy_count,
            "sell_count":      sell_count,
        })

        time.sleep(10)

    # ── 정상 종료 처리 ────────────────────────────────────────
    if chk_run == 2:
        clear_state(coin)
        log("DG", f"[{coin}] Trade Exit.")


# ════════════════════════════════════════════════════════════════
#  진입점
# ════════════════════════════════════════════════════════════════

COINS = ["KRW-BTC", "KRW-ETH", "KRW-XRP"]

if __name__ == '__main__':
    setup_logger("SYSTEM")
    init_tables()

    processes = []
    for coin in COINS:
        p = multiprocessing.Process(
            target=run,
            args=(coin,),
            name=coin,
            daemon=True,
        )
        p.start()
        log("INFO", f"[main] 프로세스 시작: {coin} (PID: {p.pid})")
        processes.append(p)

    for p in processes:
        p.join()
        log("INFO", f"[main] 프로세스 종료: {p.name} (exitcode: {p.exitcode})")