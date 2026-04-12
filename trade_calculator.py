"""
trade_calculator.py
────────────────────────────────────────────────────────────────
매수 금액 및 호가 단위 계산 모듈.

분할매수 전략:
  - 코인당 예산 = 보유현금 / NUM_COINS
  - 1회 기준금  = 코인당예산 / 등비수열합계(40항)
  - 회차 매수금 = 기준금 × RATIO^buy_count
  - RATIO       = MAX_MULTIPLE^(1/(MAX_BUY-1)) ≈ 1.0416  (5배/39스텝)
  - 40회 도달 시 main.py에서 지정가 매도로 전환
"""

# ── 분할매수 파라미터 ─────────────────────────────────────────
NUM_COINS    = 3        # 동시 거래 코인 수
MAX_BUY      = 40       # 코인당 최대 매수 횟수
MIN_ORDER    = 6_000    # 최소 매수금액 (KRW) — 1,000원 단위 기준 최솟값
MAX_MULTIPLE = 5.0      # 1회차 대비 40회차 매수금 배율

# 등비수열 공비 역산: r^(MAX_BUY-1) = MAX_MULTIPLE
RATIO = MAX_MULTIPLE ** (1.0 / (MAX_BUY - 1))   # ≈ 1.04165


def _series_sum(n: int, ratio: float = RATIO) -> float:
    """
    등비수열 합계: 1 + r + r^2 + ... + r^(n-1)
    closed form: (r^n - 1) / (r - 1)
    """
    if abs(ratio - 1.0) < 1e-9:
        return float(n)
    return (ratio ** n - 1.0) / (ratio - 1.0)


# 40항 급수합계는 상수이므로 모듈 로드 시 1회만 계산
_SERIES_SUM_40 = _series_sum(MAX_BUY)


def calculate_trade_unit(cash: int, buy_count: int = 0) -> int:
    """
    등비수열(공비 RATIO) 기반 분할매수 1회 매수금 반환.

    Args:
        cash:      현재 보유 현금 (KRW) — 매 사이클 GET_CASH() 갱신값
        buy_count: 현재 코인의 누적 매수 횟수 (0-based)
                   main.py의 chk_15m_timer 를 그대로 전달

    Returns:
        이번 회차 매수금 (KRW, 1,000원 단위 반올림).
        반올림 후 6,000원 미달 또는 MAX_BUY 초과 시 0.
    """
    if cash < MIN_ORDER * NUM_COINS:
        return 0

    if buy_count >= MAX_BUY:
        # 40회 도달 — main.py에서 지정가 매도로 전환하도록 0 반환
        return 0

    per_coin_budget = cash / NUM_COINS
    base_unit       = per_coin_budget / _SERIES_SUM_40
    this_unit       = base_unit * (RATIO ** buy_count)

    # 1,000원 단위 반올림
    # 예) 6,400 → 6,000 / 6,500 → 7,000 / 5,499 → 5,000(MIN_ORDER 미달 → 0)
    result = round(this_unit / 1_000) * 1_000

    # 반올림 후에도 MIN_ORDER(6,000원) 미달이면 매수 불가
    return result if result >= MIN_ORDER else 0


def calculate_tick_unit(price: int) -> int:
    """
    코인 현재가에 따른 호가 단위(tick) 반환.
    매수/매도 지정가 계산 시 가격 간격 기준으로 사용.
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
    print(f"MAX_MULTIPLE = {MAX_MULTIPLE}배  (1회차 → 40회차)")
    print(f"급수합계(40항) = {_SERIES_SUM_40:.4f}\n")

    for cash in [3_000_000, 10_000_000, 30_000_000]:
        print(f"── 잔고 {cash:>12,}원 ──")
        budget = cash // NUM_COINS
        total  = 0
        valid  = 0
        for i in range(MAX_BUY):
            unit = calculate_trade_unit(cash, buy_count=i)
            total += unit
            if unit >= MIN_ORDER:
                valid += 1
            if i + 1 in (1, 10, 20, 30, 40):
                print(f"  {i+1:>2}회차: {unit:>9,}원")
        print(f"  코인당예산 : {budget:>9,}원")
        print(f"  총사용금액 : {total:>9,}원")
        print(f"  유효매수횟수: {valid}회\n")