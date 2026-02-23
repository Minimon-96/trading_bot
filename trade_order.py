from upbit_api import *
from logger import *
import math

@log_function_call
def ORDER_BUY_MARKET(ticker, buy_amount):   # 시장가 매수 주문 후 결과 리턴(uuid를 포함한 매수 정보)
    if buy_amount < 5000:   # 매수 금액이 5000보다 작은 경우 실패(업비트 최소주문 단위)
        log("TR", "Fail",ticker, buy_amount,"amount is better than 5000")
        return 0
    try:
        res = upbit.buy_market_order(ticker,buy_amount) # 매수 주문 결과를 res 변수에 저장
        if 'error' in res:
            log("TR","Error", ticker, buy_amount, res)
            res = 0
            return res
        log("TR", "Success", ticker, buy_amount, res)
    except Exception as e:
        res = 0 
        log("TR", "Fail",ticker, buy_amount, e)
    return res

@log_function_call
def ORDER_SELL_MARKET(ticker, *args):   # 시장가 매도 주문 결과 리턴 (uuid를 포함한 정보)
    try:
        sell_quan = GET_QUAN_COIN(ticker)   # 현재 보유중인 수량 조회
        res = upbit.sell_market_order(ticker,sell_quan) # 현재 보유중인 코인 일괄매도
        if 'error' in res:
            log("TR","Error", ticker, sell_quan, res)
            res = 0
            return res
        log("TR", "Success", ticker, sell_quan, res)
    except Exception as e:
        log("TR", "Fail", ticker, sell_quan, e)
        res = 0 
    return res
    
@log_function_call
def ORDER_SELL_LIMIT(ticker, profit, *args):    # 지정가 매도 주문 결과 리턴 (지정한 Minimum Cash 가격에 도달한 경우 진행)
    if profit < 1.01:
        log("TR", "Check your profiePer Value", profit)
    try:
        vol = math.floor(upbit.get_balance(ticker))     # 매도 수량 지정(소수점 첫째 자리에서 내림계산)
        buy_avg_price = math.floor(profit * GET_BUY_AVG(ticker))      # 평균 매수가를 매도 주문 가격으로 지정
        res = upbit.sell_limit_order(ticker, buy_avg_price, vol)    
        if 'error' in res:
            log("TR","Error", ticker, profit, buy_avg_price, res)
            return res
        log("TR", "Success", ticker, profit, buy_avg_price,res)
        res = 1
    except Exception as e:
        log("TR", "Fail", ticker, profit, buy_avg_price, e)
        res = e
    return res

if __name__ == '__main__':
    print("trade_order.py")