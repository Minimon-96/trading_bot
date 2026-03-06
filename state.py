"""
state.py
────────────────────────────────────────────────────────────────
코인별 거래 상태를 JSON 파일로 저장/복구하는 모듈.

TTL(Time-to-Live) 정책:
  - 재시작 후 저장된 상태가 2시간 이내 → 이전 상태 복구
  - 재시작 후 저장된 상태가 2시간 초과 → DEFAULT_STATE로 초기화
  - 파일 없음 / 손상 / 코인 불일치   → DEFAULT_STATE로 초기화

파일 경로 규칙:
  data/trade_state_KRW_BTC.json   (KRW-BTC)
  data/trade_state_KRW_ETH.json   (KRW-ETH)
  data/trade_state_KRW_XRP.json   (KRW-XRP)
"""

import json
import os
import time
from logger import log

# ── 상수 ────────────────────────────────────────────────────
TTL_SECONDS = 2 * 60 * 60      # 2시간 (초 단위)
STATE_DIR   = "data"

# ── 기본 상태값 ──────────────────────────────────────────────
# 봇이 최초 시작하거나 TTL이 만료된 경우 이 값으로 초기화됩니다.
DEFAULT_STATE = {
    "buy_price":        0.0,
    "sell_price":       0.0,
    "chk_15m_timer":    0,
    "chk_sell_order":   0,
    "timer_15m_start":  0.0,
    "timer_3h_start":   0.0,
}


def _get_path(ticker: str) -> str:
    """
    ticker → 상태 파일 경로 변환
    예: "KRW-BTC" → "data/trade_state_KRW_BTC.json"
    """
    safe = ticker.replace("-", "_")         # 파일명에 '-' 사용 불가 방지
    return os.path.join(STATE_DIR, f"trade_state_{safe}.json")


def save_state(ticker: str, state: dict) -> None:
    """
    현재 상태를 타임스탬프와 함께 JSON 파일로 저장.
    루프 하단 time.sleep() 직전에 매 사이클마다 호출합니다.

    Args:
        ticker: 코인 티커 (예: "KRW-BTC")
        state:  저장할 상태 딕셔너리
    """
    os.makedirs(STATE_DIR, exist_ok=True)
    payload = {
        "ticker":   ticker,
        "saved_at": time.time(),    # Unix timestamp
        "state":    state,
    }
    path = _get_path(ticker)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log("ER", f"[state] save_state 실패 ({ticker}): {e}")


def load_state(ticker: str) -> dict:
    """
    저장된 상태를 로드. TTL 초과 또는 이상 감지 시 DEFAULT_STATE 반환.

    Args:
        ticker: 코인 티커 (예: "KRW-BTC")

    Returns:
        복구된 state dict 또는 DEFAULT_STATE.copy()
    """
    path = _get_path(ticker)

    # ① 파일 없음 → 최초 시작
    if not os.path.exists(path):
        log("INFO", f"[state] 상태 파일 없음 → 초기값으로 시작 ({ticker})")
        return DEFAULT_STATE.copy()

    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)

        # ② 코인 불일치 → 잘못된 파일
        if payload.get("ticker") != ticker:
            log("ER", f"[state] ticker 불일치 → 초기값으로 시작 ({ticker})")
            return DEFAULT_STATE.copy()

        # ③ TTL 검사
        age_seconds = time.time() - payload.get("saved_at", 0)
        age_minutes = int(age_seconds // 60)

        if age_seconds > TTL_SECONDS:
            log("INFO", f"[state] TTL 만료 ({age_minutes}분 경과) → 초기값으로 시작 ({ticker})")
            return DEFAULT_STATE.copy()

        # ④ 정상 복구
        log("INFO", f"[state] 상태 복구 성공 ({age_minutes}분 전 저장) ({ticker})")
        recovered = DEFAULT_STATE.copy()
        recovered.update(payload.get("state", {}))  # 누락된 키는 DEFAULT로 보완
        return recovered

    except (json.JSONDecodeError, KeyError) as e:
        log("ER", f"[state] 파일 손상 → 초기값으로 시작 ({ticker}): {e}")
        return DEFAULT_STATE.copy()


def clear_state(ticker: str) -> None:
    """
    상태 파일 삭제. 봇이 정상 종료(chk_run == 2)될 때 호출합니다.

    Args:
        ticker: 코인 티커 (예: "KRW-BTC")
    """
    path = _get_path(ticker)
    if os.path.exists(path):
        try:
            os.remove(path)
            log("INFO", f"[state] 상태 파일 삭제 완료 ({ticker})")
        except Exception as e:
            log("ER", f"[state] 상태 파일 삭제 실패 ({ticker}): {e}")