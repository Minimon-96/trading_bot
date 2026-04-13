"""
upbit_api.py
────────────────────────────────────────────────────────────────
업비트 API 래퍼 모듈.

[FIX]
  1. GET_ORDER_INFO — res 미초기화 NameError 방지 (res = 0 선언)
  2. GET_ORDER_INFO — ret 빈 리스트 처리 추가
  3. GET_ORDER_DETAIL — list/dict 반환 타입 정규화
  4. GET_MARKET_TREND — OHLCV TTL 캐시 적용 (10분, API 쿼터 절감)
"""

import os
import time
from dotenv import load_dotenv
import pyupbit
from logger import *

load_dotenv()

access_key = os.getenv("UPBIT_ACCESS_KEY")
secret_key = os.getenv("UPBIT_SECRET_KEY")

if not access_key or not secret_key:
    print("Error: .env 파일에 UPBIT_ACCESS_KEY / UPBIT_SECRET_KEY가 없습니다.")

upbit = pyupbit.Upbit(access_key, secret_key)


# ════════════════════════════════════════════════════════════════
#  재시도 래퍼
# ════════════════════════════════════════════════════════════════

def fetch_data(fetch_func, max_retries: int = 10):
    """
    fetch_func()를 최대 max_retries회 재시도합니다.
    None이 아닌 값이 오면 즉시 반환.
    초과 시 None 반환 (무한루프 방지).
    """
    for _ in range(max_retries):
        res = fetch_func()
        if res is not None:
            return res
        time.sleep(0.5)
    log("ER", f"fetch_data: {max_retries}회 재시도 후 실패")
    return None


# ════════════════════════════════════════════════════════════════
#  잔고 조회
# ════════════════════════════════════════════════════════════════

@log_function_call
def GET_QUAN_COIN(ticker, *args):
    try:
        res = fetch_data(lambda: upbit.get_balance(ticker))
        log("TR", "Success", res)
    except Exception as e:
        res = 0
        log("TR", "Fail", e)
    return res


@log_function_call
def GET_BUY_AVG(ticker, *args):
    try:
        res = fetch_data(lambda: upbit.get_avg_buy_price(ticker))
        log("TR", "Success", res)
    except Exception as e:
        res = 0
        log("TR", "Fail", e)
    return res


@log_function_call
def GET_CUR_PRICE(ticker, *args):
    try:
        res = fetch_data(lambda: pyupbit.get_current_price(ticker))
        log("TR", "Success", res)
    except Exception as e:
        res = 0
        log("TR", "Fail", e)
    return res


@log_function_call
def GET_CASH(ticker, *args):
    try:
        res = fetch_data(lambda: upbit.get_balance("KRW"))
        log("TR", "Success", res)
    except Exception as e:
        res = 0
        log("TR", "Fail", e)
    return round(res)


# ════════════════════════════════════════════════════════════════
#  추세 판단 — OHLCV TTL 캐시 적용
# ════════════════════════════════════════════════════════════════

_ohlcv_cache: dict = {}   # { ticker: {"df": DataFrame, "ts": float} }
_OHLCV_TTL   = 600        # 10분 (일봉 데이터는 하루 1회 갱신이므로 충분)


@log_function_call
def GET_MARKET_TREND(ticker, price, days_short, days_long):
    """
    단기/장기 이동평균 기반 추세를 반환합니다.

    Returns:
        "up"     — 단기 MA 위
        "run-up" — 장기 MA × 1.2 위 (강세)
        "down"   — 단기 MA 아래
        0        — 데이터 수신 실패
    """
    price_gap = ma_short = last_ma_short = ma_long = last_ma_long = trend = None
    try:
        price_gap = price * 0.01

        # ── TTL 캐시 ───────────────────────────────────────────
        now   = time.time()
        cache = _ohlcv_cache.get(ticker)
        if cache is None or (now - cache["ts"]) > _OHLCV_TTL:
            df = fetch_data(
                lambda: pyupbit.get_ohlcv(ticker, interval="day", count=days_long + 5)
            )
            if df is None or df.empty:
                log("ER", "GET_MARKET_TREND: OHLCV 수신 실패")
                return 0
            _ohlcv_cache[ticker] = {"df": df, "ts": now}
            log("TR", f"OHLCV 캐시 갱신 ({ticker})")
        else:
            df = cache["df"]

        ma_short      = df['close'].rolling(window=days_short).mean()
        last_ma_short = ma_short.iloc[-2] + price_gap
        trend         = "up" if price > last_ma_short else "down"

        ma_long      = df['close'].rolling(window=days_long).mean()
        last_ma_long = round((ma_long.iloc[-2] + price_gap) * 1.2)

        if price > last_ma_long:
            trend         = "run-up"
            last_ma_short = last_ma_long

        log("TR", f"Cur:{price}", f"Trend price:{last_ma_short}", f"Trend:{trend}")
        return trend

    except Exception as e:
        log("TR", "Fail", e,
            f"ticker:{ticker}", f"price:{price}",
            f"price_gap:{price_gap}", f"ma_short:{ma_short}",
            f"last_ma_short:{last_ma_short}", f"trend:{trend}",
            f"ma_long:{ma_long}", f"last_ma_long:{last_ma_long}")
        return 0


# ════════════════════════════════════════════════════════════════
#  주문 조회
# ════════════════════════════════════════════════════════════════

@log_function_call
def GET_ORDER_INFO(ticker, *args):
    """
    미체결 주문 목록에서 가장 최근 주문 정보를 반환합니다.

    Returns:
        "uuid&side&price&volume" — 주문 있음
        2                        — 주문 없음 (IndexError)
        0                        — 조회 실패
    """
    # [FIX] res 미초기화 → NameError 방지
    res = 0
    try:
        ret = fetch_data(lambda: upbit.get_order(ticker))

        # [FIX] 빈 리스트 처리
        if not ret:
            log("TR", "Empty order list")
            return 2

        # [FIX] dict 타입 오류 응답 처리
        if isinstance(ret, dict) and "error" in ret:
            log("TR", "Error", ret)
            return 0

        for i in range(len(ret)):
            if ret[i]['side'] in ('ask', 'bid'):
                res = (ret[i]['uuid'] + "&" + ret[i]['side'] + "&" +
                       ret[i]['price'] + "&" + ret[i]['volume'])
                log("TR", "Success", res)

    except IndexError as ie:
        res = 2
        log("TR", "Try Last Sell Order", ie)
    except Exception as e:
        res = 0
        log("TR", "Fail", e)
    return res


@log_function_call
def GET_ORDER_STATE(uuid):
    """
    주문 상태를 반환합니다.

    Returns:
        "wait" / "done" / "cancel" — 정상
        0                          — 실패
    """
    try:
        retn = fetch_data(lambda: upbit.get_order(uuid, state='wait'))
        if retn is None or (isinstance(retn, dict) and "error" in retn):
            log("TR", "Error", retn)
            return 0
        res = retn['state']
        log("TR", "Success", res)
        return res
    except Exception as e:
        log("TR", "Fail", e)
        return 0


@log_function_call
def GET_ORDER_DETAIL(uuid: str):
    """
    uuid로 주문 상세 정보를 조회합니다.

    [FIX] pyupbit 버전에 따라 list/dict 반환 타입이 달라지는 문제 대응.
          두 경우 모두 dict로 정규화 후 처리.

    cancel 처리:
      업비트 시장가 주문은 내부적으로 cancel → done 전환이 발생할 수 있음.
      cancel_retry_limit(3회) 재폴링 후 최종 판단.

    Returns:
        dict  — 체결 완료
        None  — 미체결 확정 또는 타임아웃
    """
    cancel_retry_count = 0
    cancel_retry_limit = 3

    for attempt in range(10):
        try:
            raw = upbit.get_order(uuid)

            # [FIX] 반환 타입 정규화
            if isinstance(raw, list):
                res = raw[0] if raw else None
            elif isinstance(raw, dict):
                res = raw
            else:
                res = None

            if res:
                state = res.get("state")
                if state == "done":
                    log("TR", "Success",
                        f"uuid={uuid}",
                        f"executed_volume={res.get('executed_volume')}",
                        f"paid_fee={res.get('paid_fee')}")
                    return res
                elif state == "cancel":
                    cancel_retry_count += 1
                    log("TR", f"cancel 감지 ({cancel_retry_count}/{cancel_retry_limit}): {uuid}")
                    if cancel_retry_count >= cancel_retry_limit:
                        log("TR", f"cancel 확정: {uuid}")
                        return None
                else:
                    log("TR", f"체결 대기... state={state} (attempt {attempt+1})")

        except Exception as e:
            log("TR", "Fail", e)

        time.sleep(0.5)

    log("TR", "Timeout: 주문 체결 대기 초과", uuid)
    return None


if __name__ == '__main__':
    print("upbit_api.py")