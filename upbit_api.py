import os
from dotenv import load_dotenv
import pyupbit
import pybithumb
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
    log("ERR", f"fetch_data: {max_retries}회 재시도 후 데이터 수신 실패")
    return None

@log_function_call
def GET_QUAN_COIN(ticker, *args):   # 보유 코인수량 리턴
    try:
        res = fetch_data(lambda: upbit.get_balance(ticker)) # 'upbit.get_balance(ticker)' 를 실행하는 lambda 함수를 fetch_data() 함수로 보내 데이터 수신
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

@log_function_call
def GET_MARKET_TREND(ticker, price, days_short, days_long):  
    # ticker : Trading Ticker = 'KRW-XRP'
    # price : Current price = 10000 (won)
    # days_short : Moving average short(bottom) calc = 3 (days)
    # days_long : Moving average long(top) calc = 20 (days)
    
    ticker_bithumb = ticker.split('-')[1]   # ticker에서 '-'를 기준으로 분리하여 암호화폐 심볼을 추출 (pybithumb.get_ohlcv 함수 호출시 사용)
    price_gap = ma_short = last_ma_short = ma_long = last_ma_long = trend = None
    log("INFO","ticker_bithumb : " +str(ticker_bithumb))
    try:
        price_gap = price * 0.01    # 현재가격에 1%인 값을 price_gap으로 설정
        df = fetch_data(lambda: pybithumb.get_ohlcv(ticker_bithumb))    # pybithumb 라이브러리를 사용하여 암호화폐의 OHLCV 데이터 수신
        
        if df is None or df.empty:
            log("DG","OHLCV DataFrame Get Failed.")
            return 0

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
        log("TR", "Cur Price:"+str(price), "Trend price:"+str(last_ma_short),"Trend:"+trend)
        return trend
    
    except Exception as e:
        log("DG", e,
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


# def GET_MARKET_TREND_UP(ticker, price, days_short, days_long):
#     # 변수 사전 초기화 (예외 처리 블록에서 NameError 방지)
#     price_gap = ma_short = last_ma_short = ma_long = last_ma_long = trend = None
#     try:
#         price_gap = price * 0.01    # 현재가격의 1%를 price_gap으로 설정

#         # [CHANGED] pybithumb → pyupbit
#         # - ticker: "KRW-BTC" 형식 그대로 사용 (별도 파싱 불필요)
#         # - interval="day": 일봉 데이터 요청
#         # - count: rolling 계산에 필요한 최소 데이터 수 확보
#         df = fetch_data(lambda: pyupbit.get_ohlcv(ticker, interval="day", count=days_long + 5))
#         print(df)
        
#         if df is None or df.empty:
#             print("GET_MARKET_TREND: OHLCV 데이터 수신 실패")
#             return 0

#         ma_short = df['close'].rolling(window=days_short).mean()
#         print(ma_short)
#         last_ma_short = ma_short.iloc[-2] + price_gap   # 직전 봉 기준 단기 MA + gap
#         print(last_ma_short)

#         trend = None
#         if price > last_ma_short:
#             trend = "up"
#         else:
#             trend = "down"

#         ma_long = df['close'].rolling(window=days_long).mean()
#         print(ma_long)
#         last_ma_long = round((ma_long.iloc[-2] + price_gap) * 1.2)
#         print(last_ma_long)

#         if price > last_ma_long:
#             trend = "run-up"
#             last_ma_short = last_ma_long    # 로깅 편의용 (기존 로직 유지)

#         print("TR", "Cur Price:" + str(price), "Trend price:" + str(last_ma_short), "Trend:" + trend)
#         return trend

#     except Exception as e:
#         print("DG", e,
#             "ticker: "      + str(ticker),
#             "days_short: "  + str(days_short),
#             "days_long: "   + str(days_long),
#             "price: "       + str(price),
#             "price_gap: "   + str(price_gap),
#             "ma_short: "    + str(ma_short),
#             "last_ma_short: "+ str(last_ma_short),
#             "trend: "       + str(trend),
#             "ma_long: "     + str(ma_long),
#             "last_ma_long: "+ str(last_ma_long))
#         return 0

@log_function_call
def GET_ORDER_INFO(ticker, *args):  # 주문 내역 리턴 (uuid & bid or ask & 주문가 & 주문수량)
    try:
        ret = fetch_data(lambda: upbit.get_order(ticker))
        if ret and "error" in ret[0]:
            log("TR", "Error", ret[0])
            res = 0
        else:
            for i in range(0,len(ret)): # 주문 내역이 여러개인 경우 모두 출력
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
def GET_ORDER_STATE(uuid):   # 주문 상태 리턴 (오류:error / 대기:wait / 완료:done)
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


if __name__ == '__main__':
    print("upbit_api.py")