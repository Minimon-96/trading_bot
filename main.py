from logger import log
from upbit_api import *
from trade_order import *
# from sim_upbit_api import *
from trade_calculator import *


def run(chk_run):
    if chk_run == 0:

        ### 초기변수 설정
        #coin = 'KRW-BTC'
        coin = 'KRW-ETH'
        #coin = 'KRW-XRP'
        start_money = 300000
        last_sell_order = 10                                # 시작금액 대비 보유현금이 N%인경우 전량 지정가 매도
        profitPer = 1.06                                    # 마지막 지정가 매도 주문 수익률
        rise_chk = 0
        chk_sell_order = 0
        chk_15m_timer = 0
        cur_coin = 0.0
        cur_cash = 0.0
        cur_price = 0.0
        buy_amount = 0.0
        buy_price = 0.0
        sell_amount = 0.0
        sell_price = 0.0

        cur_cash = GET_CASH(coin)                           # 현재 보유 현금 조회
        one_tick = calculate_tick_unit(cur_price)           # 호가(최소 변동폭) 단위 조회
        cur_price = GET_CUR_PRICE(coin)                     # 현재 코인 가격 조회
        cur_coin = GET_QUAN_COIN(coin)                      # 현재 보유 코인 조회

        if cur_cash < 1:
            log("DG","GET_CASH() Error ", str(cur_cash))
            time.sleep(10)
            return 0
        
        buy_price = cur_price - (one_tick * 3)              # 최초 매수가격은 현재 가격에서 3틱을 뺀 값으로 지정
        buy_amount = calculate_trade_unit(cur_cash)         # 보유 현금에 비례하여 1회당 매수 금액 지정

        if cur_coin > cur_price >= buy_amount:              # (현재 보유코인 * 현재 코인 가격) >= 최소거래 단위 인 경우 에러처리
            sell_price = round(GET_BUY_AVG(coin) * 1.03)
            log("DG","Initial Sell Price : "+str(sell_price), "Current Quntity Coin : "+str(cur_coin))
        else:
            sell_price = 0.0

        log("INFO","Cur Price : " + str(cur_price),"One Tick : " + str(one_tick), "Buy Price : " + str(buy_price), "Buy Amount : " + str(buy_amount))
        if buy_amount == 0:
            log("DG","calculate_trade_unit() Error")
            time.sleep(10)
            return 0
        before_buy_price = buy_price                        # -아직 미사용-

    """
    chk_run value
    0 : Reset the Settings. (not yet)
    1 : Trade Start
    2 : Program Exit
    """
    chk_run = 1
    time.sleep(1)

    while chk_run == 1:
        ### 현재 보유 현금이 0원인 경우는 업비트와의 통신에 문제가 있다고 판단하여 10초뒤 재실행
        cur_cash = GET_CASH(coin)
        if cur_cash == 0:
            log("DG","The balance is confirmed as $0.")
            time.sleep(10)
            continue

        ### 현재 코인의 가격이 0원인 경우 업비트와의 통신에 문제가 있다고 판단 하여 10초뒤 재실행
        cur_price = GET_CUR_PRICE(coin) 
        if cur_price == 0:
            log("DG","Current Price small than 1.")
            time.sleep(10)
            continue

        one_tick = calculate_tick_unit(cur_price)

        cur_coin = GET_QUAN_COIN(coin) 
        if cur_coin * cur_price <= one_tick:
            sell_price = 0.0

        ### 보유 현금액이 min_cash 미만이 되면 일괄매도 진행
        min_cash = round((cur_cash + (cur_coin * cur_price)) * last_sell_order/100)  # 최초 금액 대비 (10%) 가 되면 매수중지
        if cur_cash < min_cash:     
            log("DG","Cash on hand is too low.")

        if chk_15m_timer != 0:
            if int(time.strftime("%M")) % 15 == 0:  # 매시 15분 마다 타이머 초기화
                log("INFO","Check Timer reset")
                chk_15m_timer = 0

        if cur_cash > min_cash:
            try:
                wallet = round(cur_cash + (cur_coin * cur_price))
                log("DG","WALLET : " + str(wallet) , "ACCOUNT : " + str(round(cur_cash)),"COIN_" + str(coin) + " : " + str(cur_coin))

                trend = GET_MARKET_TREND(coin, cur_price, 3, 20)    # 단기를 3일, 장기를 20일 으로 평균 종가 계산 후 상승, 하락 추세 판단
                if  trend == "up":
                    log("DG","The price is high. Reset Buy price.")
                    rise_chk = 1
                elif trend == "run-up":
                    log("DG","The price is Crazy run-up. Reset Buy price.")
                    rise_chk = 1

                if rise_chk == 1:
                    buy_price = cur_price - (one_tick * 3)
                    log("INFO","One Tick : " + str(one_tick),"Cur Price : " + str(cur_price),"Buy Price : "+str(buy_price))
                    rise_chk = 0    

                log("DG","CUR_PRICE : " + str(cur_price), "BUY_PRICE  : " + str(buy_price))
                # 시장가 매수 진행
                if cur_price < buy_price:   # 가격이 지정한 매수가 밑으로 내려오면 매수 진행
                    log("INFO","One Tick : " + str(one_tick),"Cur Price : " + str(cur_price))
                    if chk_15m_timer > 3:   # 15분 동안 매수 3회 제한
                        buy_price = cur_price - (one_tick * 3)
                        log("DG","Purchased more than 3 times in 15 minutes.")
                    else:
                        res = ORDER_BUY_MARKET(coin, buy_amount)
                    time.sleep(1)

                    if res != 0:
                        chk_15m_timer += 1  # 매수 체결시 체크타이머 +1 (15분 마다 0으로 초기화)
                        log("INFO","Check Timer : " + str(chk_15m_timer))
                        buy_price = cur_price - (one_tick * 3)
                        sell_price = round(GET_BUY_AVG(coin) * 1.03)    # 평균 매수가 +n% 가격을 매도가로 설정
                        log("DG", "BUY OREDR " + str(coin)+ " : " + str(cur_price), "AMOUNT : " + str(buy_amount))

                log("DG","CUR_PRICE : " + str(cur_price), "SELL_PRICE : " + str(sell_price))
                # 시장가 매도 진행
                if cur_price >= sell_price and (cur_coin * cur_price) > 6000:   # 가격이 매도가보다 높고, 매도 금액이 최소 주문 단위인 6000원 초과인 경우 매도 진행
                    res = ORDER_SELL_MARKET(coin)
                    time.sleep(1)

                    if res != 0:
                        sell_amount = res['executed_volume']
                        log("DG", "SELL ORDER " + str(coin) + " : " + str(sell_price), "AMOUNT : " + str(sell_amount))
                        sell_price = 0.0
                    
                margin = round(wallet-start_money)  # 수익금
                margins = round((margin/start_money)*100,2) # 수익률
                log("DG", "Initial Money : " + str(start_money), "Margin : " + str(margin) + " ("+ str(margins)+" %)")
            except Exception as e:
                log("DG", "Margin CALC Fail",e)

        else:   # 매도가 이뤄지지 않아 보유 현금액의 n%가 되었을 때 (평단가*k%)값으로 매도주문 후 대기
            try:
                order_info = GET_ORDER_INFO(coin)
                if order_info == 2: # 조회는 성공했으나 주문이 없는 경우
                    last_order_res = ORDER_SELL_LIMIT(coin,profitPer)
                    log("INFO", "Last Sell Order Result" + str(last_order_res))
                elif order_info == 0:
                    log("DG", "Fail to GET ORDER INFO")
                    time.sleep(5)
                    continue
                else:
                    order_info = GET_ORDER_INFO(coin).split('&')
                    last_order_res = 1
                
                if last_order_res == 1:     
                    log("DG", "Last Order Success ", last_order_res)
                    log("DG", "UUID   : "+order_info[0])
                    log("DG", "PRICE  : "+order_info[2])
                    log("DG", "VOLUME : "+order_info[3])
                    chk_sell_order = 1  # 매도가 완료될 때 까지 대기하는 반복문을 실행
                    time.sleep(10)
                else:
                    log("DG", "Last Order Fail", last_order_res)
                    continue
                
            except Exception as e:
                log("DG", "Fail ", e)

        while chk_sell_order == 1:
            try:
                tmp = GET_ORDER_INFO(coin)
                # 조회는 성공했으나 주문 정보가 없는 경우
                if tmp == 2:
                    chk_sell_order = 0
                    break
                # 에러
                elif tmp == 0:
                    log("DG", "Fail","GET ORDER INFO Return")
                    chk_sell_order = 0
                    time.sleep(10)
                    continue
                else:
                    order_info = tmp.split('&')     # 주문 정보 파싱

                order_uuid = order_info[0]
                order_status = GET_ORDER_STATE(order_uuid)

                if order_status == 'wait':
                    log("DG", "Cur Price :" + GET_CUR_PRICE(coin), "Sell price : " + order_info[2])
                    log("DG", "Sell Order Status : " + order_status)
                else:
                    log("DG", "Sell Order Status : " + order_status)
                    chk_run = 0
                    chk_sell_order = 0
                time.sleep(60)

            except Exception as e:
                log("DG", "Fail",e)
                chk_run = 2
                chk_sell_order = 0

        time.sleep(10)
            

    """
    test
    """
    if chk_run == 2:
        log("DG","Trade Exit.")

### START ###
if __name__ == '__main__':
    while True:
        run(0)
