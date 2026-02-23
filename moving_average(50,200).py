#It's difficult to say which automated trading technique is the most profitable, as it depends on various factors such as the market conditions, the strategy used, and the risk management techniques employed.

#That being said, one popular trading technique is the Moving Average Crossover strategy. This strategy uses two moving averages of different time periods, such as a 50-day moving average and a 200-day moving average. When the shorter-term moving average (50-day in this example) crosses above the longer-term moving average (200-day), it is considered a buy signal. Conversely, when the shorter-term moving average crosses below the longer-term moving average, it is considered a sell signal.

from platform import machine
import pybithumb
import sys
import requests
import json
import jwt
import hashlib
import os
import requests
import uuid
from urllib.parse import urlencode, unquote
from datetime import datetime
from logging import handlers
import logging
import time
import pyupbit
import pandas as pd


coin = "KRW-XRP"  # Coin Symbol

with open("key.txt") as f:
    access_key, secret_key = [line.strip() for line in f.readlines()]

upbit = pyupbit.Upbit(access_key, secret_key)  # Key Reference

def get_ohlcv(ticker, interval='day', count=200):
    """Get historical price data for a given ticker and interval."""
    ohlcv = pyupbit.get_ohlcv(ticker, interval=interval, count=count)
    return ohlcv

def get_current_price(ticker):
    """Get the current price of a given ticker."""
    current_price = pyupbit.get_current_price(ticker)
    return current_price

def get_position_size(ticker, budget, price):
    """Get the position size given a budget and price."""
    balance = upbit.get_balance(ticker)
    if balance > 0:
        return 0
    else:
        krw_balance = upbit.get_balance("KRW")
        return (krw_balance * budget) / price

def buy(ticker, price, size):
    #print("ticker : {}, price : {}, size : {}".format(ticker,price,size))
    """Place a buy market order at the given price and size."""
    orderbook = pyupbit.get_orderbook(ticker)
    sell_price = orderbook["orderbook_units"][0]["ask_price"]
    buy_result = upbit.buy_market_order(ticker, size)
    return buy_result

def sell(ticker, price, size):
    #print("ticker : {}, price : {}, size : {}".format(ticker,price,size))
    """Place a sell market order at the given price and size."""
    orderbook = pyupbit.get_orderbook(ticker)
    buy_price = orderbook["orderbook_units"][0]["bid_price"]
    sell_result = upbit.sell_market_order(ticker, size)
    return sell_result


def run(ticker, budget, short_ma=50, long_ma=200):
    """Run the Moving Average Crossover strategy for a given ticker and budget."""
    while True:
        try:
            ohlcv = get_ohlcv(ticker, interval='day', count=long_ma)
            current_price = get_current_price(ticker)
            short_rolling_mean = ohlcv['close'].rolling(short_ma).mean()
            long_rolling_mean = ohlcv['close'].rolling(long_ma).mean()

            if short_rolling_mean.iloc[-1] > long_rolling_mean.iloc[-1]:
                # buy
                size = get_position_size(ticker, budget, current_price)
                if size > 0:
                    buy_result = buy(ticker, current_price, size)
                    print("Buy:", buy_result)
            elif short_rolling_mean.iloc[-1] < long_rolling_mean.iloc[-1]:
                # sell
                size = upbit.get_balance(ticker)
                if size > 0:
                    sell_result = sell(ticker, current_price, size)
                    print("Sell:", sell_result)

            time.sleep(60)
        except Exception as e:
            print(e)
            time


run(coin,100000)