from upbit_api import *
from logger import *
import math


@log_function_call
def ORDER_BUY_MARKET(ticker: str, buy_amount: int):
    """
    시장가 매수 주문.

    [FIX] res가 None이거나 list인 경우 'error' in res → TypeError 발생.
          → isinstance(res, dict) 체크 추가 후 error 키 검사.

    Returns:
        dict  — 주문 성공 (uuid 포함)
        0     — 실패
    """
    if buy_amount < 5000:
        log("TR", "Fail", ticker, buy_amount, "amount is less than 5000 (Upbit minimum)")
        return 0
    try:
        res = upbit.buy_market_order(ticker, buy_amount)

        # [FIX] res 타입 안전 검사
        if not isinstance(res, dict):
            log("TR", "Error", ticker, buy_amount, f"Unexpected response type: {type(res)}", res)
            return 0
        if 'error' in res:
            log("TR", "Error", ticker, buy_amount, res)
            return 0

        log("TR", "Success", ticker, buy_amount, res)
        return res

    except Exception as e:
        log("TR", "Fail", ticker, buy_amount, e)
        return 0


@log_function_call
def ORDER_SELL_MARKET(ticker: str, *args):
    """
    시장가 매도 주문 (전량 매도).

    [FIX] res 타입 안전 검사 추가.

    Returns:
        dict  — 주문 성공 (uuid 포함)
        0     — 실패
    """
    sell_quan = 0
    try:
        sell_quan = GET_QUAN_COIN(ticker)
        res = upbit.sell_market_order(ticker, sell_quan)

        # [FIX] res 타입 안전 검사
        if not isinstance(res, dict):
            log("TR", "Error", ticker, sell_quan, f"Unexpected response type: {type(res)}", res)
            return 0
        if 'error' in res:
            log("TR", "Error", ticker, sell_quan, res)
            return 0

        log("TR", "Success", ticker, sell_quan, res)
        return res

    except Exception as e:
        log("TR", "Fail", ticker, sell_quan, e)
        return 0


@log_function_call
def ORDER_SELL_LIMIT(ticker: str, profit: float, *args):
    """
    지정가 매도 주문.

    Args:
        ticker: 코인 티커 (예: "KRW-BTC")
        profit: 수익 배율 (예: 1.06 = 평균매수가 대비 6% 위)

    Returns:
        1     — 성공
        0     — 실패
        기타  — 예외 객체
    """
    if profit < 1.01:
        log("TR", "Check your profitPer Value — should be >= 1.01", profit)

    vol           = 0
    buy_avg_price = 0
    try:
        vol           = math.floor(upbit.get_balance(ticker))
        buy_avg_price = math.floor(profit * GET_BUY_AVG(ticker))
        res           = upbit.sell_limit_order(ticker, buy_avg_price, vol)

        # [FIX] res 타입 안전 검사
        if not isinstance(res, dict):
            log("TR", "Error", ticker, profit, buy_avg_price,
                f"Unexpected response type: {type(res)}", res)
            return 0
        if 'error' in res:
            log("TR", "Error", ticker, profit, buy_avg_price, res)
            return res

        log("TR", "Success", ticker, profit, buy_avg_price, res)
        return 1

    except Exception as e:
        log("TR", "Fail", ticker, profit, buy_avg_price, e)
        return e


if __name__ == '__main__':
    print("trade_order.py")