import os
from dotenv import load_dotenv
import pyupbit
# [REMOVED] import pybithumb  ← pybithumb 완전 제거 (pyupbit으로 대체)
import time
from logger import *

# .env 파일 로드
load_dotenv()

access_key = os.getenv("UPBIT_ACCESS_KEY")
secret_key = os.getenv("UPBIT_SECRET_KEY")

# 키가 없는 경우 에러 처리
if not access_key or not secret_key:
    print("Error: .env 파일에 API KEY가 없습니다.")

# 업비트 연동
upbit = pyupbit.Upbit(access_key, secret_key)


# ──────────────────────────────────────────────
#  [REFACTORED] fetch_data
#  - 기존: 무한루프 → 네트워크 장애 시 봇 영구 정지 위험
#  - 변경: max_retries 파라미터 추가 (기본 10회), 초과 시 None 반환
# ──────────────────────────────────────────────
def fetch_data(fetch_func, max_retries: int = 10):
    for attempt in range(max_retries):
        res = fetch_func()
        if res is not None:
            return res
        time.sleep(0.5)
    log("ER", f"fetch_data: {max_retries}회 재시도 후 데이터 수신 실패")
    return None


@log_function_call
def GET_QUAN_COIN(ticker, *args):   # 보유 코인수량 리턴
    try:
        res = fetch_data(lambda: upbit.get_balance(ticker))
        log("TR", "Success", res)
    except Exception as e:
        res = 0
        log("TR", "Fail", e)
    return res


@log_function_call
def GET_BUY_AVG(ticker, *args):     # 평균매수가 리턴
    try:
        res = fetch_data(lambda: upbit.get_avg_buy_price(ticker))
        log("TR", "Success", res)
    except Exception as e:
        res = 0
        log("TR", "Fail", e)
    return res


@log_function_call
def GET_CUR_PRICE(ticker, *args):   # 현재가격 리턴
    try:
        res = fetch_data(lambda: pyupbit.get_current_price(ticker))
        log("TR", "Success", res)
    except Exception as e:
        res = 0
        log("TR", "Fail", e)
    return res


@log_function_call
def GET_CASH(ticker, *args):        # 현재 현금보유액 리턴 (미체결 주문액 제외)
    try:
        res = fetch_data(lambda: upbit.get_balance("KRW"))
        log("TR", "Success", res)
    except Exception as e:
        res = 0
        log("TR", "Fail", e)
    return round(res)


# ──────────────────────────────────────────────
#  [REFACTORED] GET_MARKET_TREND
#
#  핵심 변경사항:
#  1. pybithumb.get_ohlcv(ticker_bithumb)
#         ↓
#     pyupbit.get_ohlcv(ticker, interval="day", count=days_long + 5)
#
#  2. ticker_bithumb 파싱 로직 제거
#     - pybithumb은 "BTC" 형식 사용 → ticker.split('-')[1] 필요했음
#     - pyupbit은 "KRW-BTC" 형식 그대로 사용 → 파싱 불필요
#
#  3. count 파라미터 추가
#     - 기존 pybithumb은 기본값(200일)을 묵시적으로 사용
#     - pyupbit은 명시적으로 count를 지정해야 rolling 계산이 정확함
#     - days_long + 5로 설정하여 rolling mean 계산에 충분한 데이터 확보
#
#  4. 예외 처리 안전화
#     - 기존: except 블록에서 미할당 변수(ma_short 등) 참조 → NameError 위험
#     - 변경: 변수 사전 초기화로 NameError 방지
# ──────────────────────────────────────────────
@log_function_call
def GET_MARKET_TREND(ticker, price, days_short, days_long):
    # 변수 사전 초기화 (예외 처리 블록에서 NameError 방지)
    price_gap = ma_short = last_ma_short = ma_long = last_ma_long = trend = None
    try:
        price_gap = price * 0.01    # 현재가격의 1%를 price_gap으로 설정

        # [CHANGED] pybithumb → pyupbit
        # - ticker: "KRW-BTC" 형식 그대로 사용 (별도 파싱 불필요)
        # - interval="day": 일봉 데이터 요청
        # - count: rolling 계산에 필요한 최소 데이터 수 확보
        df = fetch_data(lambda: pyupbit.get_ohlcv(ticker, interval="day", count=days_long + 5))

        if df is None or df.empty:
            log("ER", "GET_MARKET_TREND: OHLCV 데이터 수신 실패")
            return 0

        ma_short = df['close'].rolling(window=days_short).mean()
        last_ma_short = ma_short.iloc[-2] + price_gap   # 직전 봉 기준 단기 MA + gap

        trend = None
        if price > last_ma_short:
            trend = "up"
        else:
            trend = "down"

        ma_long = df['close'].rolling(window=days_long).mean()
        last_ma_long = round((ma_long.iloc[-2] + price_gap) * 1.2)

        if price > last_ma_long:
            trend = "run-up"
            last_ma_short = last_ma_long    # 로깅 편의용 (기존 로직 유지)

        log("TR", "Cur Price:" + str(price), "Trend price:" + str(last_ma_short), "Trend:" + trend)
        return trend

    except Exception as e:
        log("TR", "Fail", e,
            "ticker: "      + str(ticker),
            "days_short: "  + str(days_short),
            "days_long: "   + str(days_long),
            "price: "       + str(price),
            "price_gap: "   + str(price_gap),
            "ma_short: "    + str(ma_short),
            "last_ma_short: "+ str(last_ma_short),
            "trend: "       + str(trend),
            "ma_long: "     + str(ma_long),
            "last_ma_long: "+ str(last_ma_long))
        return 0


@log_function_call
def GET_ORDER_INFO(ticker, *args):  # 주문 내역 리턴 (uuid & bid or ask & 주문가 & 주문수량)
    try:
        ret = fetch_data(lambda: upbit.get_order(ticker))
        if ret and "error" in ret[0]:
            log("TR", "Error", ret[0])
            res = 0
        else:
            for i in range(0, len(ret)):
                # [FIXED] 기존: `if ret[i]['side'] == 'ask' or 'bid'`
                #   → 'bid'는 항상 truthy이므로 조건이 항상 True (버그)
                # 변경: 명시적 비교로 수정
                if ret[i]['side'] == 'ask' or ret[i]['side'] == 'bid':
                    res = (ret[i]['uuid'] + "&" + ret[i]['side'] + "&" +
                           ret[i]['price'] + "&" + ret[i]['volume'])
                    log("TR", "Success", res)
    except IndexError as ie:
        res = 2
        log("TR", "Try Last Sell Order", ie)
    except Exception as e:
        res = 0
        log("TR", "Fail", e)
    return res  # 조회된 주문내역 중 가장 마지막(최근) 주문내역 리턴


@log_function_call
def GET_ORDER_STATE(uuid):  # 주문 상태 리턴 (오류:error / 대기:wait / 완료:done)
    try:
        retn = fetch_data(lambda: upbit.get_order(uuid, state='wait'))
        # [FIXED] 기존: `"error" in retn` → dict의 경우 key 검색만 함 (fragile)
        # 변경: None 체크 및 dict 타입 확인 후 'error' key 검사
        if retn is None or (isinstance(retn, dict) and "error" in retn):
            log("TR", "Error", retn)
            res = 0
        else:
            res = retn['state']
            log("TR", "Success", res)
    except Exception as e:
        res = 0
        log("TR", "Fail", e)
    return res


@log_function_call
def GET_ORDER_DETAIL(uuid: str):
    """
    uuid로 주문 상세 정보를 조회합니다.
    state가 done → 체결 완료 dict 반환
    state가 cancel → None 반환 (체결 실패)
    그 외 → 0.5초마다 최대 10회 폴링
    """
    for _ in range(10):
        try:
            res = upbit.get_order(uuid)
            if res and isinstance(res, dict):
                state = res.get("state")
                if state == "done":
                    log("TR", "Success", f"uuid={uuid}",
                        f"executed_volume={res.get('executed_volume')}",
                        f"paid_fee={res.get('paid_fee')}")
                    return res
                elif state == "cancel":
                    log("TR", f"Order cancelled: uuid={uuid}")
                    return None
                log("TR", f"Waiting for fill... state={state}")
        except Exception as e:
            log("TR", "Fail", e)
        time.sleep(0.5)

    log("TR", "Timeout: 주문 체결 대기 초과", uuid)
    return None


if __name__ == '__main__':
    print("upbit_api.py")