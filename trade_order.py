from upbit_api import *
from logger import *
import math

@log_function_call
def ORDER_BUY_MARKET(ticker, buy_amount):   # 시장가 매수 주문 후 결과 리턴(uuid를 포함한 매수 정보)
    if buy_amount < 5000:   # 매수 금액이 5000보다 작은 경우 실패(업비트 최소주문 단위)
        log("TR", "Fail", ticker, buy_amount, "amount is better than 5000")
        return 0
    try:
        res = upbit.buy_market_order(ticker, buy_amount)
        if 'error' in res:
            log("TR", "Error", ticker, buy_amount, res)
            res = 0
            return res
        log("TR", "Success", ticker, buy_amount, res)
    except Exception as e:
        res = 0
        log("TR", "Fail", ticker, buy_amount, e)
    return res

@log_function_call
def ORDER_SELL_MARKET(ticker, *args):   # 시장가 매도 주문 결과 리턴 (uuid를 포함한 정보)
    sell_quan = 0   # [FIX] GET_QUAN_COIN() 실패 시 except 블록에서 NameError 방지
    try:
        sell_quan = GET_QUAN_COIN(ticker)
        res = upbit.sell_market_order(ticker, sell_quan)
        if 'error' in res:
            log("TR", "Error", ticker, sell_quan, res)
            res = 0
            return res
        log("TR", "Success", ticker, sell_quan, res)
    except Exception as e:
        res = 0
        log("TR", "Fail", ticker, sell_quan, e)
    return res

@log_function_call
def ORDER_SELL_LIMIT(ticker, profit, *args):    # 지정가 매도 주문 결과 리턴
    if profit < 1.01:
        log("TR", "Check your profitPer Value", profit)
    vol = 0             # [FIX] get_balance() 실패 시 except 블록에서 NameError 방지
    buy_avg_price = 0   # [FIX] GET_BUY_AVG() 실패 시 except 블록에서 NameError 방지
    try:
        vol = math.floor(upbit.get_balance(ticker))
        buy_avg_price = math.floor(profit * GET_BUY_AVG(ticker))
        res = upbit.sell_limit_order(ticker, buy_avg_price, vol)
        if 'error' in res:
            log("TR", "Error", ticker, profit, buy_avg_price, res)
            return res
        log("TR", "Success", ticker, profit, buy_avg_price, res)
        res = 1
    except Exception as e:
        log("TR", "Fail", ticker, profit, buy_avg_price, e)
        res = e
    return res

if __name__ == '__main__':
    print("trade_order.py")