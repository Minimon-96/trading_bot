"""
mod_telegram.py
────────────────────────────────────────────────────────────────
텔레그램 알림 모듈.

채팅방 구조:
  ┌─────────────────────────────────────────────────────┐
  │  채팅방          │  전송 내용                        │
  ├─────────────────────────────────────────────────────┤
  │  BTC_CHAT        │  KRW-BTC 매수/매도 체결 알림      │
  │  ETH_CHAT        │  KRW-ETH 매수/매도 체결 알림      │
  │  XRP_CHAT        │  KRW-XRP 매수/매도 체결 알림      │
  │  MONITOR_CHAT    │  3시간 통합 리포트                │
  └─────────────────────────────────────────────────────┘

.env 필수 항목:
  TELEGRAM_TOKEN        = <봇 토큰>
  TELEGRAM_CHAT_BTC     = <BTC 채팅방 ID>
  TELEGRAM_CHAT_ETH     = <ETH 채팅방 ID>
  TELEGRAM_CHAT_XRP     = <XRP 채팅방 ID>
  TELEGRAM_CHAT_MONITOR = <모니터링 채팅방 ID>

공개 함수:
  send_buy_alert()        — 매수 체결 알림  (코인별 채팅방)
  send_sell_alert()       — 매도 체결 알림  (코인별 채팅방)
  send_monitor_report()   — 3시간 통합 리포트 (MONITOR 채팅방)
  send_error_alert()      — 에러 알림       (코인별 채팅방)
  send_telegram_msg()     — 범용 전송       (chat_id 직접 지정)
"""

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── 토큰 / 채팅방 ID 로드 ────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# 코인별 채팅방 (매수/매도 알림 전용)
_CHAT: dict[str, str] = {
    "KRW-BTC": os.getenv("TELEGRAM_CHAT_BTC",     ""),
    "KRW-ETH": os.getenv("TELEGRAM_CHAT_ETH",     ""),
    "KRW-XRP": os.getenv("TELEGRAM_CHAT_XRP",     ""),
}

# 통합 모니터링 채팅방
_CHAT_MONITOR = os.getenv("TELEGRAM_CHAT_MONITOR", "")

# ── 이모지 상수 ──────────────────────────────────────────────
_E_BUY   = "🟢"
_E_SELL  = "🔴"
_E_INFO  = "📊"
_E_ERR   = "⚠️"
_E_UP    = "📈"
_E_DOWN  = "📉"
_E_RUN   = "🚀"
_E_COIN  = "🪙"
_E_CLOCK = "🕐"
_E_BANK  = "🏦"
_E_WARN  = "🚨"


# ════════════════════════════════════════════════════════════════
#  내부 전송 함수
# ════════════════════════════════════════════════════════════════

def send_telegram_msg(message: str, chat_id: str = "") -> bool:
    """
    지정한 chat_id로 메시지를 전송합니다.

    Args:
        message: 전송할 텍스트 (Markdown 지원)
        chat_id: 전송 대상 채팅방 ID.
                 생략 시 _CHAT_MONITOR로 전송.

    Returns:
        True  — 전송 성공
        False — 설정 누락 또는 전송 실패
    """
    target = chat_id or _CHAT_MONITOR

    if not TELEGRAM_TOKEN:
        print("[Telegram] TOKEN 미설정. .env를 확인하세요.")
        return False
    if not target:
        print("[Telegram] chat_id 미설정. .env를 확인하세요.")
        return False

    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":    target,
        "text":       message,
        "parse_mode": "Markdown",
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        res.raise_for_status()
        return True
    except Exception as e:
        print(f"[Telegram] 전송 실패 (chat_id={target}): {e}")
        return False


def _chat_id_for(ticker: str) -> str:
    """
    ticker에 해당하는 채팅방 ID를 반환합니다.
    미등록 ticker면 빈 문자열 반환 → send_telegram_msg에서 오류 처리.
    """
    cid = _CHAT.get(ticker, "")
    if not cid:
        print(f"[Telegram] {ticker} 채팅방 ID 미설정. .env를 확인하세요.")
    return cid


# ════════════════════════════════════════════════════════════════
#  거래 알림 — 코인별 채팅방으로 전송
# ════════════════════════════════════════════════════════════════

def send_buy_alert(
    ticker:        str,
    price:         int,
    amount:        float,
    total:         int,
    avg_buy_price: int,
    wallet_before: int,
    wallet_after:  int,
    buy_count:     int = 0,     # 이번 매수가 몇 회차인지
) -> bool:
    """
    매수 체결 즉시 호출합니다. 코인별 채팅방으로 전송.

    전송 예시 (KRW-BTC 채팅방):
        🟢 [매수 체결] KRW-BTC  ·  7 / 40 회차
        ─────────────────
        🕐 2024-05-20 14:32:05
        💰 체결가     :   90,000,000 KRW
        📦 체결수량   :   0.00006667 BTC
        💵 체결금액   :        6,000 KRW
        📊 평균매수가 :   89,500,000 KRW
        ─────────────────
        🏦 거래 전 자산:   3,000,000 KRW
        🏦 거래 후 자산:   2,994,000 KRW
    """
    now         = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    coin_symbol = ticker.split("-")[1]
    msg = (
        f"{_E_BUY} *[매수 체결] {ticker}* · `{buy_count}/40회차`\n"
        f"───────────────\n"
        f"{_E_CLOCK} `{now}`\n"
        f"💰 체결가: `{price:,} KRW`\n"
        f"📦 수량: `{amount:.8f} {coin_symbol}`\n"
        f"💵 체결금액: `{total:,} KRW`\n"
        f"📊 평균매수가: `{avg_buy_price:,} KRW`\n"
        f"───────────────\n"
        f"{_E_BANK} 거래 전: `{wallet_before:,} KRW`\n"
        f"{_E_BANK} 거래 후: `{wallet_after:,} KRW`"
    )
    return send_telegram_msg(msg, chat_id=_chat_id_for(ticker))


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
    buy_count:     int = 0,     # 매도 시점의 총 매수 횟수
    sell_type:     str = "MARKET",  # "MARKET" | "LIMIT"
) -> bool:
    """
    매도 체결 즉시 호출합니다. 코인별 채팅방으로 전송.

    전송 예시 (KRW-ETH 채팅방):
        🔴 [매도 체결] KRW-ETH  ·  시장가  ·  3회차 후 청산
        ─────────────────────────
        ...
    """
    now          = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    coin_symbol  = ticker.split("-")[1]
    profit_sign  = "+" if profit >= 0 else ""
    rate_sign    = "+" if profit_rate >= 0 else ""
    profit_emoji = _E_UP if profit >= 0 else _E_DOWN
    sell_label   = "시장가" if sell_type == "MARKET" else f"지정가 (+{round((avg_buy_price/avg_buy_price-1)*100) if avg_buy_price else 0}%)"

    # 40회 지정가 매도인 경우 강조 표시
    header_suffix = (
        f"`{_E_WARN} 40회차 지정가 청산`"
        if sell_type == "LIMIT"
        else f"`{sell_label}  ·  {buy_count}회차 후 청산`"
    )

    msg = (
        f"{_E_SELL} *[매도 체결] {ticker}* · {header_suffix}\n"
        f"───────────────\n"
        f"{_E_CLOCK} `{now}`\n"
        f"💰 체결가: `{price:,} KRW`\n"
        f"📦 수량: `{amount:.8f} {coin_symbol}`\n"
        f"💵 체결금액: `{total:,} KRW`\n"
        f"📊 평균매수가: `{avg_buy_price:,} KRW`\n"
        f"───────────────\n"
        f"{profit_emoji} 수익금: `{profit_sign}{profit:,} KRW`\n"
        f"{profit_emoji} 수익률: `{rate_sign}{profit_rate:.2f}%`\n"
        f"───────────────\n"
        f"{_E_BANK} 거래 전: `{wallet_before:,} KRW`\n"
        f"{_E_BANK} 거래 후: `{wallet_after:,} KRW`"
    )
    return send_telegram_msg(msg, chat_id=_chat_id_for(ticker))


# ════════════════════════════════════════════════════════════════
#  3시간 통합 모니터링 리포트 — MONITOR 채팅방으로 전송
# ════════════════════════════════════════════════════════════════

def send_monitor_report(coin_stats: list) -> bool:
    """
    3시간마다 전체 코인 현황을 MONITOR 채팅방으로 전송합니다.

    Args:
        coin_stats: 코인별 현황 딕셔너리 리스트
            [
                {
                    "ticker":        "KRW-BTC",
                    "cur_price":     90_000_000,
                    "avg_buy_price": 89_000_000,   ← 평균매수가 (신규)
                    "buy_price":     89_730_000,   ← 다음 매수 예정가
                    "sell_price":    92_700_000,   ← 매도 예정가 (0이면 미설정)
                    "cur_coin":      0.00123456,
                    "cur_cash":      50_000,
                    "trend":         "run-up",
                    "wallet":        160_800,
                    "profit":        10_800,
                    "profit_rate":   7.20,
                    "split_count":   7,            ← 현재 미청산 분할매수 횟수
                    "buy_count":     42,           ← 봇 시작 후 누적 매수 횟수
                    "sell_count":    5,            ← 봇 시작 후 누적 매도 횟수
                },
                ...
            ]

    전송 예시 (MONITOR 채팅방):
        📊 [3시간 모니터링 리포트]
        2024-05-20 15:00:00
        ══════════════════════════

        📌 KRW-BTC  🚀 run-up
        현재가    :   90,000,000 KRW
        평균매수가:   89,000,000 KRW  (▲ +1.12%)
        매수예정가:   89,730,000 KRW
        매도예정가:   92,700,000 KRW
        분할매수  :   7 / 40 회차
        누적 매수 :   42 회
        누적 매도 :    5 회
        보유수량  :   0.00123456 BTC
        보유현금  :       50,000 KRW
        지갑총액  :      160,800 KRW
        수익      :    +10,800 KRW  (+7.20%)
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"{_E_INFO} *[3시간 모니터링 리포트]*",
        f"`{now}`",
        "══════════════════════════",
    ]

    trend_emoji_map = {
        "up":     _E_UP,
        "run-up": _E_RUN,
        "down":   _E_DOWN,
    }

    for s in coin_stats:
        trend_str   = str(s.get("trend", "?"))
        t_emoji     = trend_emoji_map.get(trend_str, _E_DOWN)
        coin_symbol = s["ticker"].split("-")[1]

        # 매도 예정가
        sell_str = (
            f"{s['sell_price']:,} KRW"
            if s.get("sell_price", 0) > 0
            else "미설정"
        )

        # 평균매수가 대비 현재가 등락률
        avg = s.get("avg_buy_price", 0)
        if avg and avg > 0:
            price_vs_avg      = (s["cur_price"] - avg) / avg * 100
            price_vs_avg_sign = "▲ +" if price_vs_avg >= 0 else "▼ "
            avg_str = (
                f"{avg:,} KRW  "
                f"({price_vs_avg_sign}{price_vs_avg:.2f}%)"
            )
        else:
            avg_str = "미조회"

        # 분할매수 및 누적 체결 횟수
        split_count = s.get("split_count", 0)   # 현재 미청산 분할매수 횟수
        buy_count   = s.get("buy_count",   0)   # 누적 매수 체결 횟수
        sell_count  = s.get("sell_count",  0)   # 누적 매도 체결 횟수

        # 수익
        profit      = s.get("profit", 0)
        profit_rate = s.get("profit_rate", 0.0)
        profit_sign = "+" if profit >= 0 else ""
        rate_sign   = "+" if profit_rate >= 0 else ""

        lines += [
            f"\n📌 *{s['ticker']}* {t_emoji} `{trend_str}`",
            f"{_E_COIN} 현재가: `{s['cur_price']:,} KRW`",
            f"📊 평균매수가: `{avg_str}`",
            f"🎯 매수예정가: `{s['buy_price']:,} KRW`",
            f"💹 매도예정가: `{sell_str}`",
            f"🔢 분할매수: `{split_count}/40회차`",
            f"📥 누적 매수: `{buy_count}회`",
            f"📤 누적 매도: `{sell_count}회`",
            f"📦 보유수량: `{s['cur_coin']:.8f} {coin_symbol}`",
            f"💵 보유현금: `{int(s['cur_cash']):,} KRW`",
            f"{_E_BANK} 지갑총액: `{int(s['wallet']):,} KRW`",
            f"{'📈' if profit >= 0 else '📉'} 수익: `{profit_sign}{profit:,} KRW ({rate_sign}{profit_rate:.2f}%)`",
        ]

    return send_telegram_msg("\n".join(lines), chat_id=_CHAT_MONITOR)


# ════════════════════════════════════════════════════════════════
#  에러 알림 — 코인별 채팅방으로 전송
# ════════════════════════════════════════════════════════════════

def send_error_alert(ticker: str, context: str, error: Exception) -> bool:
    """
    심각한 에러 발생 시 호출합니다. 코인별 채팅방으로 전송.
    ticker가 없는 시스템 에러는 MONITOR 채팅방으로 폴백.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = (
        f"{_E_ERR} *[에러 발생] {ticker}*\n"
        f"`{now}`\n"
        f"Context: `{context}`\n"
        f"Error  : `{str(error)[:200]}`"
    )
    chat_id = _chat_id_for(ticker) or _CHAT_MONITOR
    return send_telegram_msg(msg, chat_id=chat_id)


# ════════════════════════════════════════════════════════════════
#  테스트
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # ── .env 설정 확인 ──────────────────────────────────
    print("=== 채팅방 설정 확인 ===")
    print(f"TOKEN   : {'설정됨' if TELEGRAM_TOKEN else '❌ 미설정'}")
    for ticker, cid in _CHAT.items():
        status = cid if cid else '❌ 미설정'
        print(f"{ticker}: {status}")
    print(f"MONITOR : {_CHAT_MONITOR if _CHAT_MONITOR else '❌ 미설정'}")
    print()

    # ── 코인별 채팅방 테스트 (매수/매도 샘플) ───────────
    TEST_CASES = [
        {
            "ticker": "KRW-BTC",
            "price": 90_000_000, "amount": 0.00006667,
            "total": 6_000, "avg_buy_price": 89_500_000,
            "wallet_before": 3_000_000, "wallet_after": 2_994_000,
            "buy_count": 7,
        },
        {
            "ticker": "KRW-ETH",
            "price": 3_850_000, "amount": 0.00259067,
            "total": 9_977, "avg_buy_price": 3_900_000,
            "wallet_before": 1_500_000, "wallet_after": 1_490_023,
            "buy_count": 3,
        },
        {
            "ticker": "KRW-XRP",
            "price": 720, "amount": 8.333,
            "total": 6_000, "avg_buy_price": 715,
            "wallet_before": 500_000, "wallet_after": 494_000,
            "buy_count": 1,
        },
    ]

    print("=== 코인별 채팅방 매수 알림 테스트 ===")
    for t in TEST_CASES:
        ok = send_buy_alert(
            ticker=t["ticker"], price=t["price"],
            amount=t["amount"], total=t["total"],
            avg_buy_price=t["avg_buy_price"],
            wallet_before=t["wallet_before"],
            wallet_after=t["wallet_after"],
            buy_count=t["buy_count"],
        )
        print(f"{t['ticker']} 매수 알림: {'✅ 전송' if ok else '❌ 실패'}")

    print()
    print("=== 코인별 채팅방 매도 알림 테스트 ===")
    SELL_CASES = [
        {
            "ticker": "KRW-BTC", "price": 91_000_000,
            "amount": 0.00006667, "total": 6_066,
            "avg_buy_price": 89_500_000,
            "profit": 66, "profit_rate": 1.10,
            "wallet_before": 2_994_000, "wallet_after": 3_000_066,
            "buy_count": 7, "sell_type": "MARKET",
        },
        {
            "ticker": "KRW-ETH", "price": 4_017_000,
            "amount": 0.00259067, "total": 10_404,
            "avg_buy_price": 3_900_000,
            "profit": 427, "profit_rate": 4.27,
            "wallet_before": 1_490_023, "wallet_after": 1_500_427,
            "buy_count": 3, "sell_type": "MARKET",
        },
        {
            "ticker": "KRW-XRP", "price": 757,
            "amount": 8.333, "total": 6_308,
            "avg_buy_price": 715,
            "profit": 308, "profit_rate": 5.17,
            "wallet_before": 494_000, "wallet_after": 500_308,
            "buy_count": 40, "sell_type": "LIMIT",
        },
    ]
    for t in SELL_CASES:
        ok = send_sell_alert(
            ticker=t["ticker"], price=t["price"],
            amount=t["amount"], total=t["total"],
            avg_buy_price=t["avg_buy_price"],
            profit=t["profit"], profit_rate=t["profit_rate"],
            wallet_before=t["wallet_before"],
            wallet_after=t["wallet_after"],
            buy_count=t["buy_count"],
            sell_type=t["sell_type"],
        )
        print(f"{t['ticker']} 매도 알림: {'✅ 전송' if ok else '❌ 실패'}")

    # ── MONITOR 채팅방 통합 리포트 테스트 ───────────────
    print()
    print("=== MONITOR 채팅방 통합 리포트 테스트 ===")
    ok = send_monitor_report([
        {
            "ticker": "KRW-BTC", "cur_price": 90_000_000,
            "avg_buy_price": 89_000_000,
            "buy_price": 89_730_000, "sell_price": 92_700_000,
            "cur_coin": 0.00123456, "cur_cash": 50_000,
            "trend": "run-up", "wallet": 160_800,
            "profit": 10_800, "profit_rate": 7.20,
            "split_count": 7, "buy_count": 42, "sell_count": 5,
        },
        {
            "ticker": "KRW-ETH", "cur_price": 3_850_000,
            "avg_buy_price": 3_900_000,
            "buy_price": 3_838_450, "sell_price": 0,
            "cur_coin": 0.00259067, "cur_cash": 290_000,
            "trend": "down", "wallet": 299_973,
            "profit": -27, "profit_rate": -0.01,
            "split_count": 12, "buy_count": 18, "sell_count": 3,
        },
        {
            "ticker": "KRW-XRP", "cur_price": 720,
            "avg_buy_price": 710,
            "buy_price": 717, "sell_price": 741,
            "cur_coin": 13.88, "cur_cash": 1_000,
            "trend": "up", "wallet": 100_994,
            "profit": 994, "profit_rate": 0.99,
            "split_count": 3, "buy_count": 95, "sell_count": 22,
        },
    ])
    print(f"MONITOR 리포트: {'✅ 전송' if ok else '❌ 실패'}")