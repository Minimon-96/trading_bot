"""
mod_telegram.py
────────────────────────────────────────────────────
텔레그램 알림 모듈.

알림 종류:
  1. 매수 체결 알림          → send_buy_alert()
  2. 매도 체결 알림          → send_sell_alert()
  3. 3시간 모니터링 리포트   → send_monitor_report()
  4. 에러 알림               → send_error_alert()
  5. 범용 메시지             → send_telegram_msg()

토큰/Chat ID는 .env에서 로드합니다:
  TELEGRAM_TOKEN=<your_token>
  TELEGRAM_CHAT_ID=<your_chat_id>
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID        = os.getenv("TELEGRAM_CHAT_ID", "")

_EMOJI_BUY  = "🟢"
_EMOJI_SELL = "🔴"
_EMOJI_INFO = "📊"
_EMOJI_ERR  = "⚠️"
_EMOJI_UP   = "📈"
_EMOJI_DOWN = "📉"
_EMOJI_RUN  = "🚀"


# ════════════════════════════════════════════════════════════════
#  내부 전송 함수
# ════════════════════════════════════════════════════════════════

def send_telegram_msg(message: str) -> bool:
    """
    텔레그램 봇으로 메시지를 전송합니다.

    Returns:
        True  — 전송 성공
        False — 전송 실패 (봇이 멈추지 않도록 예외를 삼킵니다)
    """
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[Telegram] TOKEN 또는 CHAT_ID 미설정. .env를 확인하세요.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    CHAT_ID,
        "text":       message,
        "parse_mode": "Markdown",
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
        return True
    except Exception as e:
        print(f"[Telegram] 전송 실패: {e}")
        return False


# ════════════════════════════════════════════════════════════════
#  거래 알림
# ════════════════════════════════════════════════════════════════

def send_buy_alert(
    ticker:        str,
    price:         int,
    amount:        float,
    total:         int,
    avg_buy_price: int,
    wallet_before: int,
    wallet_after:  int,
) -> bool:
    """
    매수 체결 즉시 호출합니다.

    전송 예시:
        🟢 [매수 체결] KRW-ETH
        ─────────────────
        🕐 2024-05-20 14:32:05
        💰 체결가     :  3,850,000 KRW
        📦 체결수량   :  0.00259067 ETH
        💵 체결금액   :     10,000 KRW
        📊 평균매수가 :  3,820,000 KRW
        ─────────────────
        🏦 거래 전 자산:  312,500 KRW
        🏦 거래 후 자산:  302,500 KRW
    """
    now          = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    coin_symbol  = ticker.split("-")[1]
    msg = (
        f"{_EMOJI_BUY} *[매수 체결] {ticker}*\n"
        f"─────────────────\n"
        f"🕐 `{now}`\n"
        f"💰 체결가     : `{price:>15,} KRW`\n"
        f"📦 체결수량   : `{amount:>15.8f} {coin_symbol}`\n"
        f"💵 체결금액   : `{total:>15,} KRW`\n"
        f"📊 평균매수가 : `{avg_buy_price:>15,} KRW`\n"
        f"─────────────────\n"
        f"🏦 거래 전 자산: `{wallet_before:>13,} KRW`\n"
        f"🏦 거래 후 자산: `{wallet_after:>13,} KRW`"
    )
    return send_telegram_msg(msg)


def send_sell_alert(
    ticker:        str,
    price:         int,
    amount:        float,
    total:         int,
    avg_buy_price: int,
    profit:        int,
    profit_rate:   float,
    wallet_before: int,
    wallet_after:  int,
) -> bool:
    """
    매도 체결 즉시 호출합니다.

    전송 예시:
        🔴 [매도 체결] KRW-ETH
        ─────────────────
        🕐 2024-05-20 15:10:22
        💰 체결가     :  3,960,000 KRW
        📦 체결수량   :  0.00259067 ETH
        💵 체결금액   :     10,261 KRW
        📊 평균매수가 :  3,820,000 KRW
        ─────────────────
        📈 수익금     :     +261 KRW
        📈 수익률     :    +2.61 %
        ─────────────────
        🏦 거래 전 자산:  302,500 KRW
        🏦 거래 후 자산:  312,761 KRW
    """
    now          = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    coin_symbol  = ticker.split("-")[1]
    profit_sign  = "+" if profit >= 0 else ""
    rate_sign    = "+" if profit_rate >= 0 else ""
    profit_emoji = _EMOJI_UP if profit >= 0 else _EMOJI_DOWN

    msg = (
        f"{_EMOJI_SELL} *[매도 체결] {ticker}*\n"
        f"─────────────────\n"
        f"🕐 `{now}`\n"
        f"💰 체결가     : `{price:>15,} KRW`\n"
        f"📦 체결수량   : `{amount:>15.8f} {coin_symbol}`\n"
        f"💵 체결금액   : `{total:>15,} KRW`\n"
        f"📊 평균매수가 : `{avg_buy_price:>15,} KRW`\n"
        f"─────────────────\n"
        f"{profit_emoji} 수익금     : `{profit_sign}{profit:>14,} KRW`\n"
        f"{profit_emoji} 수익률     : `{rate_sign}{profit_rate:>13.2f} %`\n"
        f"─────────────────\n"
        f"🏦 거래 전 자산: `{wallet_before:>13,} KRW`\n"
        f"🏦 거래 후 자산: `{wallet_after:>13,} KRW`"
    )
    return send_telegram_msg(msg)


# ════════════════════════════════════════════════════════════════
#  3시간 모니터링 리포트
# ════════════════════════════════════════════════════════════════

def send_monitor_report(coin_stats: list) -> bool:
    """
    3시간마다 전체 코인 현황을 요약해서 전송합니다.
    main.py의 monitor_timer 로직에서 호출합니다.

    Args:
        coin_stats: 코인별 현황 딕셔너리 리스트
            [
                {
                    "ticker":      "KRW-BTC",
                    "cur_price":   90000000,
                    "buy_price":   89730000,
                    "sell_price":  92700000,   # 0이면 "미설정"
                    "cur_coin":    0.00123456,
                    "cur_cash":    50000,
                    "trend":       "run-up",   # up / down / run-up
                    "wallet":      160800,
                    "profit":      10800,
                    "profit_rate": 7.20,
                },
                ...
            ]

    전송 예시:
        📊 [모니터링 리포트]
        2024-05-20 15:00:00
        ══════════════════════

        📌 KRW-BTC  🚀 run-up
        현재가    :  90,000,000 KRW
        매수예정가:  89,730,000 KRW
        매도예정가:  92,700,000 KRW
        보유수량  :  0.00123456 BTC
        보유현금  :      50,000 KRW
        지갑총액  :     160,800 KRW
        수익      :    +10,800 KRW  (+7.20%)
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"{_EMOJI_INFO} *[모니터링 리포트]*",
        f"`{now}`",
        "══════════════════════",
    ]

    trend_emoji_map = {
        "up":     _EMOJI_UP,
        "run-up": _EMOJI_RUN,
        "down":   _EMOJI_DOWN,
    }

    for s in coin_stats:
        trend_str    = str(s.get("trend", "?"))
        t_emoji      = trend_emoji_map.get(trend_str, _EMOJI_DOWN)
        coin_symbol  = s["ticker"].split("-")[1]
        sell_str     = f"{s['sell_price']:,} KRW" if s.get("sell_price", 0) > 0 else "미설정"
        profit       = s.get("profit", 0)
        profit_rate  = s.get("profit_rate", 0.0)
        profit_sign  = "+" if profit >= 0 else ""
        rate_sign    = "+" if profit_rate >= 0 else ""

        lines += [
            f"\n📌 *{s['ticker']}*  {t_emoji} `{trend_str}`",
            f"현재가    : `{s['cur_price']:>15,} KRW`",
            f"매수예정가: `{s['buy_price']:>15,} KRW`",
            f"매도예정가: `{sell_str:>19}`",
            f"보유수량  : `{s['cur_coin']:>15.8f} {coin_symbol}`",
            f"보유현금  : `{int(s['cur_cash']):>15,} KRW`",
            f"지갑총액  : `{int(s['wallet']):>15,} KRW`",
            f"수익      : `{profit_sign}{profit:>13,} KRW  ({rate_sign}{profit_rate:.2f}%)`",
        ]

    return send_telegram_msg("\n".join(lines))


# ════════════════════════════════════════════════════════════════
#  에러 알림
# ════════════════════════════════════════════════════════════════

def send_error_alert(ticker: str, context: str, error: Exception) -> bool:
    """
    심각한 에러 발생 시 호출합니다.

    전송 예시:
        ⚠️ [에러 발생] KRW-ETH
        2024-05-20 16:45:11
        Context: ORDER_BUY_MARKET 실패
        Error  : HTTPError 500
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"{_EMOJI_ERR} *[에러 발생] {ticker}*\n"
        f"`{now}`\n"
        f"Context: `{context}`\n"
        f"Error  : `{str(error)[:200]}`"
    )
    return send_telegram_msg(msg)


# ════════════════════════════════════════════════════════════════
#  테스트
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    send_telegram_msg("🚀 trading_bot 텔레그램 연결 테스트")

    send_monitor_report([
        {
            "ticker": "KRW-BTC", "cur_price": 90000000,
            "buy_price": 89730000, "sell_price": 92700000,
            "cur_coin": 0.00123456, "cur_cash": 50000,
            "trend": "run-up", "wallet": 160800,
            "profit": 10800, "profit_rate": 7.20,
        },
        {
            "ticker": "KRW-ETH", "cur_price": 3850000,
            "buy_price": 3838450, "sell_price": 0,
            "cur_coin": 0.00259067, "cur_cash": 290000,
            "trend": "down", "wallet": 299973,
            "profit": -27, "profit_rate": -0.01,
        },
        {
            "ticker": "KRW-XRP", "cur_price": 720,
            "buy_price": 717, "sell_price": 741,
            "cur_coin": 13.88, "cur_cash": 1000,
            "trend": "up", "wallet": 100994,
            "profit": 994, "profit_rate": 0.99,
        },
    ])