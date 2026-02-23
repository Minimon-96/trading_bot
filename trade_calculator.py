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

if __name__ == '__main__':
    print(calculate_tick_unit(10000))