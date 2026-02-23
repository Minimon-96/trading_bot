import os
import math
from dotenv import load_dotenv
import pyupbit
import pybithumb
import time
from mod_telegram import send_telegram_msg

# .env 파일 로드
load_dotenv()

access_key = os.getenv("UPBIT_ACCESS_KEY")
secret_key = os.getenv("UPBIT_SECRET_KEY")

# 키가 없는 경우 에러 처리
if not access_key or not secret_key:
    print("Error: .env 파일에 API KEY가 없습니다.")
    
# 업비트 연동
upbit = pyupbit.Upbit(access_key, secret_key) 


def calculate_trade_unit(cash):
    if cash <= 600000:
        return 6000
    elif 500000 < cash <= 1000000:
        return 10000
    elif 1000000 < cash <= 1500000:
        return 15000
    elif 1500000 < cash <= 2000000:
        return 20000
    elif 2000000 < cash <= 3000000:
        return 25000
    elif 3000000 < cash <= 4000000:
        return 35000
    elif 4000000 < cash <= 8000000:
        return 50000
    elif 8000000 < cash:
        return 100000
    else:
        return 0

def calculate_tick_unit(price): # 코인 가격에 따른 tick 단위 지정
    if price < 1000:
        return 1
    elif price < 10000:
        return round(price * 0.0015)
    elif price < 100000:
        return round(price * 0.002)
    elif price < 500000:
        return round(price * 0.0025)
    elif price < 1000000:
        return round(price * 0.003)
    else:
        return round(price * 0.0035)

def fetch_data(fetch_func, max_retries=5):
    retries=0
    while retries < max_retries:
        try:
            res = fetch_func()
            if res is not None:
                return res
        except Exception as e:
            print(e)
            #log("DG", f"Data Fetch Error: {e}")
        time.sleep(0.5)
        retries+=1
    #log("ER", "Failed to fetch data after max_retries")
    return None
    # while True:
    #     res = fetch_func()  # fetch_func() 함수를 호출하여 데이터
    #     if res is not None: # 가져온 데이터가 None이 아닌 경우 루프를 종료
    #         break
    #     time.sleep(0.5) # 데이터를 가져오지 못한 경우 0.5초 동안 대기
    # return res

def GET_QUAN_COIN(ticker, *args):   # 보유 코인수량 리턴
    try:
        res = fetch_data(lambda: upbit.get_balance(ticker)) # 'upbit.get_balance(ticker)' 를 실행하는 lambda 함수를 fetch_data() 함수로 보내 데이터 수신
        print(res)
        ##log("TR", "Success", res)
    except Exception as e:
        res = 0
        print(e)
        ##log("TR", "Fail", e)
    return res

def GET_BUY_AVG(ticker, *args):     # 평균매수가 리턴
    try:
        res = fetch_data(lambda: upbit.get_avg_buy_price(ticker))
        ##log("TR", "Success", res)
        print(res)
    except Exception as e:
        res = 0
        print(e)
        ##log("TR", "Fail", e)
    return res

def GET_CUR_PRICE(ticker, *args):   # 현재가격 리턴
    try:
        res = fetch_data(lambda: pyupbit.get_current_price(ticker))
        ##log("TR", "Success", res)
        print(res)
    except Exception as e:
        res = 0
        print(e)
        ##log("TR", "Fail", e)
    return res

def GET_CASH(ticker, *args):        # 현재 현금보유액 리턴 (미체결 주문액 제외)
    try:
        res = fetch_data(lambda: upbit.get_balance("KRW"))
        ##log("TR", "Success", res)
        print(res)
    except Exception as e:
        res = 0
        print(e)
        ##log("TR", "Fail", e)
    return round(res)

def GET_MARKET_TREND_BIT(ticker, price, days_short, days_long):  
    ticker_bithumb = ticker.split('-')[1]   # ticker에서 '-'를 기준으로 분리하여 암호화폐 심볼을 추출 (pybithumb.get_ohlcv 함수 호출시 사용)
    ##log("INFO","ticker_bithumb : " +str(ticker_bithumb))
    print(f"INFO - ticker_bithumb : {str(ticker_bithumb)}")
    try:
        price_gap = price * 0.01    # 현재가격에 1%인 값을 price_gap으로 설정
        df = fetch_data(lambda: pybithumb.get_ohlcv(ticker_bithumb))    # pybithumb 라이브러리를 사용하여 암호화폐의 OHLCV 데이터 수신
        ma_short = df['close'].rolling(window=days_short).mean()    # 일정 기간(days_short) 동안의 종가 평균값(ma)을 계산
        last_ma_short = ma_short.iloc[-2] + price_gap    # (days_short) 기간 동안의 종가 평균값(ma)에 price_gap을 더한 값을 last_ma로 설정
        trend = None    # 추세(trend)를 초기화
        if price > last_ma_short: 
            trend = "up"    # 현재 가격(price)이 이전 기간의 종가 평균값(last_ma)보다 큰 경우 추세를 "up"으로 설정
        else:
            trend = "down"  # 그렇지 않은 경우 추세를 "down"으로 설정


        ma_long = df['close'].rolling(window=days_long).mean()
        last_ma_long = round((ma_long.iloc[-2] + price_gap)*1.2)   # 이전 기간의 종가 평균값(ma_long)에 price_gap을 더한 값에 1.2를 곱하여 last_ma_long으로 설정

        if price > last_ma_long:
            trend="run-up"  # 현재 가격(price)이 이전 기간의 종가 평균값(last_ma_long)보다 큰 경우 추세를 "run-up"으로 설정
            last_ma_short = last_ma_long # 별뜻없음 그냥 로깅 편하게 하려고
        ##log("TR", "Cur Price:"+str(price), "Trend price:"+str(last_ma_short),"Trend:"+trend)
        print(f"Price: {price}, MA{days_short}: {last_ma_short}, MA{days_long}: {last_ma_long}, Trend: {trend}")
        return trend
    except Exception as e:
        ##log("TR", "Fail", e, "ticker: " + str(ticker), "days: " + str(days_short), "price: " + str(price), "price_gap: " + str(price_gap), "ma5: " + str(ma_short), "last_ma5: " + str(last_ma_short), "trend: " + str(trend), "days_long: " + str(days_long), "ma20: " + str(ma_long), "last_ma20: " + str(last_ma_long))
        print(e)
        return 0

def GET_ORDER_INFO(ticker, *args):  # 주문 내역 리턴 (uuid & bid or ask & 주문가 & 주문수량)
    try:
        ret = fetch_data(lambda: upbit.get_order(ticker))
        if "error" in ret[0]:
            print(ret[0])
            ##log("TR", "Error", ret[0])
            res = 0
        else:
            for i in range(0,len(ret)): # 주문 내역이 여러개인 경우 모두 출력
                if ret[i]['side'] == 'ask' or 'bid':
                    res = ret[i]['uuid'] +"&"+ ret[i]['side'] +"&"+ ret[i]['price'] +"&"+ ret[i]['volume']
                    print(res)
                    ##log("TR", "Success", res)
    except IndexError as ie:
        res = 2
        print(ie)
        ##log("TR", "Try Last Sell Order", ie)
    except Exception as e:
        res = 0
        print(e)
        ##log("TR", "Fail", e)
    return res  # 조회된 주문내역 중 가장 마지막(최근) 주문내역 리턴

def ORDER_BUY_MARKET(ticker, buy_amount):   # 시장가 매수 주문 후 결과 리턴(uuid를 포함한 매수 정보)
    if buy_amount < 5000:   # 매수 금액이 5000보다 작은 경우 실패(업비트 최소주문 단위)
        #log("TR", "Fail",ticker, buy_amount,"amount is better than 5000")
        return 0
    try:
        res = upbit.buy_market_order(ticker,buy_amount) # 매수 주문 결과를 res 변수에 저장
        if 'error' in res:
            #log("TR","Error", ticker, buy_amount, res)
            print(res)
            res = 0
            return res
        print(res)
        #log("TR", "Success", ticker, buy_amount, res)
    except Exception as e:
        res = 0 
        print(e)
        #log("TR", "Fail",ticker, buy_amount, e)
    return res

def ORDER_SELL_MARKET(ticker, *args):   # 시장가 매도 주문 결과 리턴 (uuid를 포함한 정보)
    try:
        sell_quan = GET_QUAN_COIN(ticker)   # 현재 보유중인 수량 조회
        res = upbit.sell_market_order(ticker,sell_quan) # 현재 보유중인 코인 일괄매도
        if 'error' in res:
            #log("TR","Error", ticker, sell_quan, res)
            print(res)
            res = 0
            return res
        #log("TR", "Success", ticker, sell_quan, res)
    except Exception as e:
        print(e)
        #log("TR", "Fail", ticker, sell_quan, e)
        res = 0 
    return res
    
def ORDER_SELL_LIMIT(ticker, profit, *args):    # 지정가 매도 주문 결과 리턴 (지정한 Minimum Cash 가격에 도달한 경우 진행)
    if profit < 1.01:
        print(profit)
        #log("TR", "Check your profiePer Value", profit)
    try:
        vol = math.floor(upbit.get_balance(ticker))     # 매도 수량 지정(소수점 첫째 자리에서 내림계산)
        buy_avg_price = math.floor(profit * GET_BUY_AVG(ticker))      # 평균 매수가를 매도 주문 가격으로 지정
        res = upbit.sell_limit_order(ticker, buy_avg_price, vol)    
        if 'error' in res:
            print(res)
            #log("TR","Error", ticker, profit, buy_avg_price, res)
            return res
        print(res)
        #log("TR", "Success", ticker, profit, buy_avg_price,res)
        res = 1
    except Exception as e:
        print(e)
        #log("TR", "Fail", ticker, profit, buy_avg_price, e)
        res = e
    return res

def GET_MARKET_TREND_UP(ticker, price, days_short, days_long):
    """
    업비트 데이터를 사용하여 추세 판단 (빗썸 코드 제거됨)
    """
    try:
        # 업비트 OHLCV 데이터 가져오기 (일봉 기준)
        df = fetch_data(lambda: pyupbit.get_ohlcv(ticker, interval="day", count=days_long+2))
        if df is None:
            return "unknown"
        price_gap = price * 0.01    # 현재가격에 1%인 값을 price_gap으로 설정
        # 이동평균선 계산
        ma_short = df['close'].rolling(window=days_short).mean()
        ma_long = df['close'].rolling(window=days_long).mean()

        last_ma_short = round(ma_short.iloc[-2] + price_gap) # 전일 단기 이평
        last_ma_long = round((ma_long.iloc[-2] + price_gap) * 1.2)    # 전일 장기 이평

        trend = "sideways"
        
        # 단순 골든크로스/정배열 로직으로 변경 (수정 가능)
        if price > last_ma_short and last_ma_short > last_ma_long:
            trend = "up"
        elif price < last_ma_short:
            trend = "down"
            
        #log("INFO", f"Price: {price}, MA{days_short}: {last_ma_short}, MA{days_long}: {last_ma_long}, Trend: {trend}")
        print(f"Price: {price}, MA{days_short}: {last_ma_short}, MA{days_long}: {last_ma_long}, Trend: {trend}")
        return trend

    except Exception as e:
        print(e)
        #log("ER", f"Trend Check Fail: {e}")
        return "error"

ticker="KRW-ETH"

#obm_res=ORDER_BUY_MARKET(ticker,6000)

cur_price=GET_CUR_PRICE(ticker)
cur_cash=GET_CASH(ticker)
cur_coin=GET_QUAN_COIN(ticker)
order_info=GET_ORDER_INFO(ticker)

trend_UP=GET_MARKET_TREND_UP(ticker,cur_price,3,20)
trend_BIT=GET_MARKET_TREND_BIT(ticker,cur_price,3,20)
print(f"Price:{cur_price}\nCash:{cur_cash}\nCoin:{cur_coin}\nTrend:{trend_UP} {trend_BIT}\nOrder Info:{order_info}")

trend_UP=GET_MARKET_TREND_UP(ticker,cur_price,5,20)
trend_BIT=GET_MARKET_TREND_BIT(ticker,cur_price,5,20)
print(f"Price:{cur_price}\nCash:{cur_cash}\nCoin:{cur_coin}\nTrend:{trend_UP} {trend_BIT}\nOrder Info:{order_info}")

buy_price=cur_price - (calculate_tick_unit(cur_price) * 3)
print(buy_price)

msg = f"🟢 [매수 체결]\n- 코인: {ticker}\n- 매수가: {cur_price}원\n- 금액: {buy_price}원"
send_telegram_msg(msg)

#print(obm_res)
