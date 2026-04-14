"""
trade_calculator.py
────────────────────────────────────────────────────────────────
매수 금액 및 호가 단위 계산 모듈.

분할매수 전략:
  - 코인당 예산 = 보유현금 / NUM_COINS
  - 1회 기준금  = 코인당예산 / 등비수열합계(20항)
  - 회차 매수금 = 기준금 × RATIO^buy_count
  - RATIO       = MAX_MULTIPLE^(1/(MAX_BUY-1)) ≈ 1.1067  (3배/19스텝)
  - 계산값이 MIN_ORDER 미달 시 MIN_ORDER(6,000원)로 하한 고정
  - 하한 고정 후에도 코인당 예산 초과 시 0 반환 (매수 불가)
  - 20회 도달 시 main.py에서 지정가 매도로 전환

[변경]
  MAX_BUY      40  → 20   (백테스트 최적값)
  MAX_MULTIPLE  5.0 → 3.0  (백테스트 최적값)
"""

# ── 분할매수 파라미터 ─────────────────────────────────────────
NUM_COINS    = 3        # 동시 거래 코인 수
MAX_BUY      = 20       # 코인당 최대 매수 횟수  ★ 40 → 20
MIN_ORDER    = 6_000    # 최소 매수금액 (KRW)
MAX_MULTIPLE = 3.0      # 1회차 대비 20회차 매수금 배율  ★ 5.0 → 3.0

# 등비수열 공비 역산: r^(MAX_BUY-1) = MAX_MULTIPLE
RATIO = MAX_MULTIPLE ** (1.0 / (MAX_BUY - 1))   # ≈ 1.10674


def _series_sum(n: int, ratio: float = RATIO) -> float:
    """
    등비수열 합계: 1 + r + r^2 + ... + r^(n-1)
    closed form: (r^n - 1) / (r - 1)
    """
    if abs(ratio - 1.0) < 1e-9:
        return float(n)
    return (ratio ** n - 1.0) / (ratio - 1.0)


# 20항 급수합계는 상수이므로 모듈 로드 시 1회만 계산
_SERIES_SUM_N = _series_sum(MAX_BUY)


def calculate_trade_unit(cash: int, buy_count: int = 0) -> int:
    """
    등비수열(공비 RATIO) 기반 분할매수 1회 매수금 반환.

    Args:
        cash:      현재 보유 현금 (KRW)
        buy_count: 현재 코인의 누적 매수 횟수 (0-based, chk_15m_timer 전달)

    Returns:
        이번 회차 매수금 (KRW, 1,000원 단위 반올림, 최소 6,000원).
        코인당 예산 초과 또는 MAX_BUY 초과 시 0.
    """
    if cash < MIN_ORDER * NUM_COINS:
        return 0

    if buy_count >= MAX_BUY:
        return 0

    per_coin_budget = cash / NUM_COINS
    base_unit       = per_coin_budget / _SERIES_SUM_N
    this_unit       = base_unit * (RATIO ** buy_count)

    result = round(this_unit / 1_000) * 1_000
    result = max(result, MIN_ORDER)

    if result > per_coin_budget:
        return 0

    return result


def calculate_tick_unit(price: int) -> int:
    """
    코인 현재가에 따른 호가 단위(tick) 반환.
    """
    if price < 1_000:
        return 1
    elif price < 10_000:
        return round(price * 0.0015)
    elif price < 100_000:
        return round(price * 0.002)
    elif price < 500_000:
        return round(price * 0.0025)
    elif price < 1_000_000:
        return round(price * 0.003)
    else:
        return round(price * 0.0035)


# ════════════════════════════════════════════════════════════════
#  단위 테스트
# ════════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print(f"RATIO        = {RATIO:.6f}")
    print(f"MAX_BUY      = {MAX_BUY}회")
    print(f"MAX_MULTIPLE = {MAX_MULTIPLE}배  (1회차 → {MAX_BUY}회차)")
    print(f"급수합계({MAX_BUY}항) = {_SERIES_SUM_N:.4f}\n")

    for cash in [3_000_000, 10_000_000, 30_000_000]:
        print(f"── 잔고 {cash:>12,}원 ──")
        budget = cash // NUM_COINS
        total  = 0
        for i in range(MAX_BUY):
            unit = calculate_trade_unit(cash, buy_count=i)
            total += unit
            if i + 1 in (1, 5, 10, 15, 20):
                print(f"  {i+1:>2}회차: {unit:>9,}원")
        print(f"  코인당예산  : {budget:>9,}원")
        print(f"  총사용금액  : {total:>9,}원\n")