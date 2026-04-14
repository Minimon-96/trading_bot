"""
main.py
────────────────────────────────────────────────────────────────
3개 코인(KRW-BTC, KRW-ETH, KRW-XRP)을 multiprocessing으로
동시에 거래하는 메인 진입점.

[변경] 백테스트 최적 파라미터 적용
  - tick_multiplier를 config.ini에서 종목별로 읽도록 변경
    (기존: 하드코딩 * 3  →  변경: * tick_multiplier)
  - buy_price 계산 3곳 모두 tick_multiplier 변수 사용
"""

import configparser
import importlib.util
import multiprocessing
import pathlib
import time

from logger import setup_logger, log
from upbit_api import *
from trade_order import *
from trade_calculator import calculate_trade_unit, calculate_tick_unit, MAX_BUY
from upbit_db import init_tables, get_initial_asset, set_initial_asset, insert_trade_history
from upbit_health import is_upbit_alive, wait_until_alive, UpbitHealthMonitor
from mod_telegram import (
    send_buy_alert, send_sell_alert,
    send_monitor_report, send_error_alert,
    send_max_buy_alert, send_limit_sell_filled_alert,
)

_BASE       = pathlib.Path(__file__).parent
_state_path = _BASE / "config" / "state.py"
_state_spec = importlib.util.spec_from_file_location("state", _state_path)
_state_mod  = importlib.util.module_from_spec(_state_spec)
_state_spec.loader.exec_module(_state_mod)

load_state  = _state_mod.load_state
save_state  = _state_mod.save_state
clear_state = _state_mod.clear_state


# ════════════════════════════════════════════════════════════════
#  설정 로드
# ════════════════════════════════════════════════════════════════

def load_config(ticker: str) -> configparser.SectionProxy:
    cfg = configparser.RawConfigParser(inline_comment_prefixes=(";", "#"))
    cfg.read(_BASE / "config" / "config.ini", encoding="utf-8")
    if ticker not in cfg:
        log("ER", f"[config] [{ticker}] 섹션 없음. DEFAULT 사용.")
        cfg[ticker] = {}
    return cfg[ticker]


# ════════════════════════════════════════════════════════════════
#  3시간 모니터링 리포트 헬퍼
# ════════════════════════════════════════════════════════════════

def _try_send_monitor(
    coin, cur_price, buy_price, sell_price,
    cur_coin, cur_cash, start_money,
    trend,
    avg_buy_price,
    split_count: int = 0,
    buy_count:   int = 0,
    sell_count:  int = 0,
):
    try:
        _wallet = round(cur_cash + (cur_coin * cur_price))
        _profit = _wallet - start_money
        _prate  = round((_profit / start_money) * 100, 2) if start_money else 0
        send_monitor_report([{
            "ticker":        coin,
            "cur_price":     cur_price,
            "avg_buy_price": avg_buy_price,
            "buy_price":     buy_price,
            "sell_price":    sell_price,
            "cur_coin":      cur_coin,
            "cur_cash":      cur_cash,
            "trend":         trend,
            "wallet":        _wallet,
            "profit":        _profit,
            "profit_rate":   _prate,
            "split_count":   split_count,
            "buy_count":     buy_count,
            "sell_count":    sell_count,
        }])
        log("INFO", f"[{coin}] 모니터 리포트 전송 완료 "
            f"(분할 {split_count}/{MAX_BUY} | 매수 {buy_count}회 / 매도 {sell_count}회)")
    except Exception as e:
        log("ER", f"[{coin}] 모니터 리포트 전송 실패: {e}")


# ════════════════════════════════════════════════════════════════
#  MAX_BUY 도달 → 지정가 매도 전환 헬퍼
# ════════════════════════════════════════════════════════════════

def _trigger_max_buy_limit_sell(coin: str, profit_per: float) -> int:
    try:
        avg   = GET_BUY_AVG(coin)
        limit = round(avg * profit_per)
        res   = ORDER_SELL_LIMIT(coin, profit_per)

        send_max_buy_alert(
            ticker=coin,
            avg=round(avg),
            limit=limit,
            profit_per=profit_per,
        )
        log("INFO", f"[{coin}] MAX_BUY({MAX_BUY}회) → 지정가 매도",
            f"avg={round(avg)}", f"limit={limit}", f"res={res}")

        return 1 if res == 1 else 0

    except Exception as e:
        log("ER", f"[{coin}] _trigger_max_buy_limit_sell 실패: {e}")
        send_error_alert(coin, "MAX_BUY 지정가 매도 실패", e)
        return 0


# ════════════════════════════════════════════════════════════════
#  메인 거래 루프
# ════════════════════════════════════════════════════════════════

def run(coin: str) -> None:

    # ── ① 로거 초기화 ────────────────────────────────────────
    setup_logger(coin)

    # ── RSS 백그라운드 모니터 ────────────────────────────────
    _health_monitor = UpbitHealthMonitor(coin)
    _health_monitor.start()

    # ── ② 설정 로드 ──────────────────────────────────────────
    cfg = load_config(coin)

    last_sell_order  = cfg.getint  ("last_sell_order",  10)
    profitPer        = cfg.getfloat("profit_per",       1.06)
    sell_profit_rate = cfg.getfloat("sell_profit_rate", 1.03)
    days_short       = cfg.getint  ("days_short",       3)
    days_long        = cfg.getint  ("days_long",        20)
    min_sell_amount  = cfg.getint  ("min_sell_amount",  6_000)
    tick_multiplier  = cfg.getint  ("tick_multiplier",  3)      # ★ 추가

    log("INFO", f"[{coin}] 설정 로드 완료",
        f"days_short={days_short}", f"days_long={days_long}",
        f"profitPer={profitPer}", f"sell_profit_rate={sell_profit_rate}",
        f"tick_multiplier={tick_multiplier}", f"MAX_BUY={MAX_BUY}")

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
        if set_initial_asset(coin, start_money):
            log("INFO", f"[{coin}] 초기 기준 자산 저장: {start_money} KRW")
        else:
            log("ER", f"[{coin}] 초기 기준 자산 저장 실패 — 로컬값 사용")
    else:
        log("INFO", f"[{coin}] 초기 기준 자산 로드: {start_money} KRW")

    # ── ⑤ 상태 복구 ──────────────────────────────────────────
    state           = load_state(coin)
    chk_15m_timer   = state["chk_15m_timer"]
    chk_sell_order  = state["chk_sell_order"]
    timer_15m_start = state["timer_15m_start"] or time.time()
    timer_3h_start  = state["timer_3h_start"]  or time.time()
    buy_count       = state["buy_count"]
    sell_count      = state["sell_count"]

    if state["buy_price"] > 0:
        buy_price  = state["buy_price"]
        sell_price = state["sell_price"]
        if sell_price == 0.0 and cur_coin * cur_price >= min_sell_amount:
            sell_price = round(GET_BUY_AVG(coin) * sell_profit_rate)
        log("INFO", f"[{coin}] 상태 복구",
            f"buy_price={buy_price}", f"sell_price={sell_price}",
            f"split={chk_15m_timer} buy={buy_count} sell={sell_count}")
    else:
        # ★ 하드코딩 * 3  →  * tick_multiplier
        buy_price = cur_price - (one_tick * tick_multiplier)
        sell_price = (
            round(GET_BUY_AVG(coin) * sell_profit_rate)
            if cur_coin * cur_price >= min_sell_amount
            else 0.0
        )

    # ── ⑥ 거래 루프 ──────────────────────────────────────────
    chk_run        = 1
    timer_3h_start = time.time()

    cached_avg = round(GET_BUY_AVG(coin)) if cur_coin * cur_price >= min_sell_amount else 0

    time.sleep(1)

    while chk_run == 1:

        # ── 업비트 헬스체크 ─────────────────────────────────
        if not is_upbit_alive():
            wait_until_alive(coin)
            continue

        # ── 현재 잔고 및 가격 조회 ────────────────────────────
        cur_cash = GET_CASH(coin)
        if cur_cash == 0:
            log("DG", f"[{coin}] GET_CASH() = 0")
            time.sleep(10)
            continue

        cur_price = GET_CUR_PRICE(coin)
        if cur_price == 0:
            log("DG", f"[{coin}] GET_CUR_PRICE() = 0")
            time.sleep(10)
            continue

        one_tick   = calculate_tick_unit(cur_price)
        cur_coin   = GET_QUAN_COIN(coin)
        buy_amount = calculate_trade_unit(cur_cash, buy_count=chk_15m_timer)

        if cur_coin * cur_price <= min_sell_amount:
            sell_price = 0.0

        min_cash = round((cur_cash + (cur_coin * cur_price)) * last_sell_order / 100)

        if cur_cash < min_cash:
            log("DG", f"[{coin}] 현금 부족")

        trend = GET_MARKET_TREND(coin, cur_price, days_short, days_long)

        # ── 3시간 모니터링 리포트 ────────────────────────────
        if time.time() - timer_3h_start >= 10_800:
            _try_send_monitor(
                coin, cur_price, buy_price, sell_price,
                cur_coin, cur_cash, start_money,
                trend=trend,
                avg_buy_price=cached_avg,
                split_count=chk_15m_timer,
                buy_count=buy_count,
                sell_count=sell_count,
            )
            timer_3h_start = time.time()

        # ── MAX_BUY 도달 → 지정가 매도 전환 ─────────────────
        if (chk_15m_timer >= MAX_BUY
                and cur_coin * cur_price > min_sell_amount
                and chk_sell_order == 0):

            log("INFO", f"[{coin}] {MAX_BUY}회 도달 → 지정가 매도 전환")
            result = _trigger_max_buy_limit_sell(coin, profitPer)

            if result == 1:
                chk_sell_order  = 1
                chk_15m_timer   = 0
                timer_15m_start = time.time()
                log("INFO", f"[{coin}] 지정가 매도 주문 완료 — 체결 대기")
            else:
                log("ER", f"[{coin}] 지정가 매도 주문 실패 — 재시도")
                time.sleep(10)
                continue

        # ── 매수 / 매도 구간 ──────────────────────────────────
        elif cur_cash > min_cash:
            try:
                wallet = round(cur_cash + (cur_coin * cur_price))
                log("DG", f"[{coin}] WALLET:{wallet} CASH:{round(cur_cash)} "
                    f"COIN:{cur_coin} SPLIT:{chk_15m_timer}/{MAX_BUY} TREND:{trend}")

                if trend in ("up", "run-up"):
                    # ★ 하드코딩 * 3  →  * tick_multiplier
                    buy_price = cur_price - (one_tick * tick_multiplier)
                    log("INFO", f"[{coin}] Trend={trend} → buy_price={buy_price}")

                log("DG", f"[{coin}] CUR:{cur_price} BUY:{buy_price}")

                # ── 시장가 매수 ──────────────────────────────
                did_buy = False

                if trend == "down" and cur_price < buy_price:
                    log("INFO", f"[{coin}] 매수 조건 충족",
                        f"cur={cur_price} buy_price={buy_price}",
                        f"buy_amount={buy_amount:,}원 ({chk_15m_timer+1}/{MAX_BUY}회차)")

                    if buy_amount == 0:
                        log("DG", f"[{coin}] buy_amount=0 — 잔고 부족 스킵")
                    else:
                        res = ORDER_BUY_MARKET(coin, buy_amount)
                        time.sleep(1)

                        if res != 0:
                            order_uuid   = res.get("uuid", "")
                            order_detail = GET_ORDER_DETAIL(order_uuid) if order_uuid else None

                            if order_detail is None:
                                coin_qty_after = GET_QUAN_COIN(coin)
                                if coin_qty_after * cur_price < min_sell_amount:
                                    log("INFO", f"[{coin}] 매수 미체결 확정")
                                    order_detail = None
                                else:
                                    buy_amount_f = coin_qty_after
                                    fee          = round(buy_amount * 0.0005, 8)
                                    buy_total    = buy_amount
                                    order_detail = {
                                        "executed_volume": buy_amount_f,
                                        "paid_fee":        fee,
                                        "_fallback":       True,
                                    }

                            if order_detail is not None:
                                did_buy = True
                                if chk_15m_timer == 0:
                                    timer_15m_start = time.time()
                                    log("INFO", f"[{coin}] 분할매수 타이머 시작")
                                chk_15m_timer += 1

                                buy_amount_f = float(order_detail.get("executed_volume", 0))
                                fee          = float(order_detail.get("paid_fee", 0))
                                buy_total    = (
                                    buy_amount
                                    if order_detail.get("_fallback")
                                    else round(float(order_detail.get("price", cur_price)) * buy_amount_f)
                                         if buy_amount_f else buy_amount
                                )

                                new_avg      = GET_BUY_AVG(coin)
                                cached_avg   = round(new_avg)
                                sell_price   = round(new_avg * sell_profit_rate)
                                # ★ 하드코딩 * 3  →  * tick_multiplier
                                buy_price    = cur_price - (one_tick * tick_multiplier)
                                wallet_after = round(GET_CASH(coin) + (GET_QUAN_COIN(coin) * cur_price))

                                log("INFO", f"[{coin}] BUY FILLED ({chk_15m_timer}/{MAX_BUY}회)",
                                    f"volume={buy_amount_f} fee={fee} total={buy_total}")

                                insert_trade_history(
                                    ticker=coin, side="BUY",
                                    price=cur_price, amount=buy_amount_f,
                                    total=buy_total, fee=fee,
                                    avg_buy_price=cached_avg,
                                    profit=0, profit_rate=0.0,
                                    wallet_before=wallet, wallet_after=wallet_after,
                                )
                                send_buy_alert(
                                    ticker=coin, price=cur_price,
                                    amount=buy_amount_f, total=buy_total,
                                    avg_buy_price=cached_avg,
                                    wallet_before=wallet, wallet_after=wallet_after,
                                    buy_count=chk_15m_timer,
                                )
                                buy_count += 1
                                save_state(coin, {
                                    "buy_count":  buy_count,
                                    "sell_count": sell_count,
                                })

                # ── 시장가 매도 (일반 익절) ───────────────────
                log("DG", f"[{coin}] CUR:{cur_price} SELL:{sell_price}")

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
                        cached_avg   = round(avg_buy)
                        wallet_after = round(GET_CASH(coin) + (GET_QUAN_COIN(coin) * cur_price))
                        profit       = round(sell_total - (avg_buy * sell_amount) - fee)
                        profit_rate  = round(
                            (profit / (avg_buy * sell_amount)) * 100, 2
                        ) if avg_buy and sell_amount else 0.0

                        insert_trade_history(
                            ticker=coin, side="SELL",
                            price=cur_price, amount=sell_amount,
                            total=sell_total, fee=fee,
                            avg_buy_price=cached_avg,
                            profit=profit, profit_rate=profit_rate,
                            wallet_before=wallet, wallet_after=wallet_after,
                        )
                        send_sell_alert(
                            ticker=coin, price=cur_price,
                            amount=sell_amount, total=sell_total,
                            avg_buy_price=cached_avg,
                            profit=profit, profit_rate=profit_rate,
                            wallet_before=wallet, wallet_after=wallet_after,
                            buy_count=chk_15m_timer,
                            sell_type="MARKET",
                        )
                        sell_count += 1
                        save_state(coin, {
                            "buy_count":  buy_count,
                            "sell_count": sell_count,
                        })
                        log("INFO", f"[{coin}] SELL FILLED profit={profit} ({profit_rate}%)")

                        sell_price      = 0.0
                        chk_15m_timer   = 0
                        cached_avg      = 0
                        timer_15m_start = time.time()

                margin  = round(wallet - start_money)
                margins = round((margin / start_money) * 100, 2)
                log("DG", f"[{coin}] 기준:{start_money} 수익:{margin} ({margins}%)")

            except Exception as e:
                log("DG", f"[{coin}] 거래 루프 예외", e)

        else:
            try:
                order_info = GET_ORDER_INFO(coin)

                if order_info == 2:
                    last_order_res = ORDER_SELL_LIMIT(coin, profitPer)
                    log("INFO", f"[{coin}] Last Sell Order: {last_order_res}")
                elif order_info == 0:
                    log("DG", f"[{coin}] GET_ORDER_INFO 실패")
                    time.sleep(5)
                    continue
                else:
                    order_info     = GET_ORDER_INFO(coin).split('&')
                    last_order_res = 1

                if last_order_res == 1:
                    chk_sell_order = 1
                    time.sleep(10)
                else:
                    log("DG", f"[{coin}] Last Order Fail: {last_order_res}")
                    continue

            except Exception as e:
                log("DG", f"[{coin}] 현금부족 처리 예외", e)

        # ── 매도 완료 대기 루프 ──────────────────────────────
        while chk_sell_order == 1:
            try:
                cur_price_w = GET_CUR_PRICE(coin)

                if cur_price_w and time.time() - timer_3h_start >= 10_800:
                    trend_w = GET_MARKET_TREND(coin, cur_price_w, days_short, days_long)
                    _try_send_monitor(
                        coin, cur_price_w, buy_price, sell_price,
                        cur_coin, GET_CASH(coin), start_money,
                        trend=trend_w,
                        avg_buy_price=cached_avg,
                        split_count=chk_15m_timer,
                        buy_count=buy_count,
                        sell_count=sell_count,
                    )
                    timer_3h_start = time.time()

                tmp = GET_ORDER_INFO(coin)

                if tmp == 2:
                    cur_cash_w   = GET_CASH(coin)
                    cur_coin_w   = GET_QUAN_COIN(coin)
                    wallet_after = round(cur_cash_w + (cur_coin_w * (cur_price_w or cur_price)))
                    avg_buy      = GET_BUY_AVG(coin)
                    sell_total_approx  = max(wallet_after - wallet, 0)
                    profit_approx      = round(sell_total_approx * (profitPer - 1) / profitPer)
                    profit_rate_approx = round((profitPer - 1) * 100, 2)

                    send_limit_sell_filled_alert(
                        ticker=coin,
                        price=round((cur_price_w or cur_price) * profitPer),
                        amount=cur_coin,
                        total=sell_total_approx,
                        avg_buy_price=cached_avg,
                        profit=profit_approx,
                        profit_rate=profit_rate_approx,
                        wallet_before=wallet if 'wallet' in dir() else 0,
                        wallet_after=wallet_after,
                        profit_per=profitPer,
                    )

                    sell_count += 1
                    save_state(coin, {
                        "buy_count":  buy_count,
                        "sell_count": sell_count,
                    })

                    chk_sell_order  = 0
                    chk_15m_timer   = 0
                    cached_avg      = 0
                    timer_15m_start = time.time()
                    log("INFO", f"[{coin}] 지정가 매도 체결 완료 — 초기화 (sell_count={sell_count})")
                    break

                elif tmp == 0:
                    log("DG", f"[{coin}] GET_ORDER_INFO 실패")
                    chk_sell_order = 0
                    time.sleep(10)
                    continue
                else:
                    order_info = tmp.split('&')

                order_uuid   = order_info[0]
                order_status = GET_ORDER_STATE(order_uuid)

                if order_status == 'wait':
                    log("DG", f"[{coin}] 매도 대기 중 cur={GET_CUR_PRICE(coin)} sell={order_info[2]}")
                else:
                    log("DG", f"[{coin}] 매도 상태: {order_status}")
                    chk_run        = 0
                    chk_sell_order = 0

                time.sleep(60)

            except Exception as e:
                log("DG", f"[{coin}] 대기 루프 예외", e)
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
        p = multiprocessing.Process(target=run, args=(coin,), name=coin, daemon=True)
        p.start()
        log("INFO", f"[main] 시작: {coin} (PID: {p.pid})")
        processes.append(p)

    for p in processes:
        p.join()
        log("INFO", f"[main] 종료: {p.name} (exitcode: {p.exitcode})")