"""
upbit_health.py
────────────────────────────────────────────────────────────────
업비트 서비스 상태 감지 및 점검 대기 모듈.

[설계 원칙]
  업비트는 공식 RSS / 공지 API 를 제공하지 않으며
  공지 페이지(upbit.com)는 robots.txt로 크롤링을 차단합니다.
  따라서 신뢰할 수 있는 감지 수단은 API 헬스체크뿐입니다.

  사전 경보는 API 응답 속도 저하 감지로 대체합니다.
  점검 직전 업비트 서버가 느려지는 패턴을 이용합니다.

기능:
  1. is_upbit_alive()     — API 헬스체크 (즉시, 10초 타임아웃)
  2. wait_until_alive()   — 복구될 때까지 루프 블로킹 + 텔레그램 알림
  3. UpbitHealthMonitor   — daemon 스레드
                           · 1분 간격으로 API 응답속도 측정
                           · 응답 느림(>3초) → 사전 경보 텔레그램 전송
                           · 응답 없음       → wait_until_alive() 호출

사용 흐름 (main.py):
  # run() 최상단
  monitor = UpbitHealthMonitor(coin)
  monitor.start()

  # 거래 루프 상단 (매 사이클 10초마다)
  if not is_upbit_alive():
      wait_until_alive(coin)
      continue
"""

import threading
import time
import urllib.request
import urllib.error
from datetime import datetime

from logger import log

# ── 설정 ──────────────────────────────────────────────────────
_UPBIT_API_URL      = "https://api.upbit.com/v1/market/all"
_API_TIMEOUT        = 10      # 헬스체크 타임아웃 (초)
_MONITOR_INTERVAL   = 60      # 모니터 스레드 폴링 주기 (초)
_ALIVE_INTERVAL     = 60      # 점검 중 재확인 주기 (초)
_SLOW_THRESHOLD     = 3.0     # 응답 느림 기준 (초) — 사전 경보 발생
_SLOW_COUNT_ALERT   = 3       # 연속 느림 횟수 도달 시 경보 전송


# ════════════════════════════════════════════════════════════════
#  1. API 헬스체크
# ════════════════════════════════════════════════════════════════

def is_upbit_alive() -> bool:
    """
    업비트 API가 정상 응답하는지 확인합니다.

    Returns:
        True  — HTTP 200 응답
        False — 타임아웃 / 5xx / 네트워크 오류
    """
    try:
        req = urllib.request.Request(
            _UPBIT_API_URL,
            headers={"User-Agent": "Mozilla/5.0 trading-bot-health-check"},
        )
        with urllib.request.urlopen(req, timeout=_API_TIMEOUT) as resp:
            return resp.status == 200
    except Exception:
        return False


def _measure_response_time() -> float | None:
    """
    API 응답 시간을 측정합니다.

    Returns:
        float — 응답 시간(초)
        None  — 응답 실패
    """
    try:
        req = urllib.request.Request(
            _UPBIT_API_URL,
            headers={"User-Agent": "Mozilla/5.0 trading-bot-health-check"},
        )
        start = time.time()
        with urllib.request.urlopen(req, timeout=_API_TIMEOUT) as resp:
            if resp.status == 200:
                return time.time() - start
        return None
    except Exception:
        return None


# ════════════════════════════════════════════════════════════════
#  2. 복구 대기 — 거래 루프 블로킹
# ════════════════════════════════════════════════════════════════

def wait_until_alive(coin: str = "SYSTEM") -> None:
    """
    업비트 API 복구까지 _ALIVE_INTERVAL(60초) 간격으로 재확인.
    점검 감지 시 MONITOR 채팅방 알림.
    복구 시 코인별 + MONITOR 채팅방 알림.

    main.py 거래 루프에서 호출 — 반환될 때까지 블로킹.
    """
    from mod_telegram import send_telegram_msg, _CHAT_MONITOR, _chat_id_for

    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    down_msg = (
        f"🔴 *[업비트 점검 감지]*\n"
        f"`{now_str}`\n"
        f"──────────────────\n"
        f"코인: `{coin}`\n"
        f"거래 루프를 일시정지합니다.\n"
        f"복구 확인 주기: {_ALIVE_INTERVAL}초"
    )
    send_telegram_msg(down_msg, chat_id=_CHAT_MONITOR)
    log("WARN", f"[{coin}] 업비트 점검 감지 → 거래 루프 일시정지")

    attempt = 0
    while True:
        time.sleep(_ALIVE_INTERVAL)
        attempt += 1

        if is_upbit_alive():
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            up_msg  = (
                f"🟢 *[업비트 복구 확인]*\n"
                f"`{now_str}`\n"
                f"──────────────────\n"
                f"코인: `{coin}`\n"
                f"거래 루프를 재개합니다. (대기 {attempt}분)"
            )
            send_telegram_msg(up_msg, chat_id=_chat_id_for(coin))
            send_telegram_msg(up_msg, chat_id=_CHAT_MONITOR)
            log("INFO", f"[{coin}] 업비트 복구 → 거래 루프 재개 (대기 {attempt}분)")
            return

        log("WARN", f"[{coin}] 업비트 점검 중... ({attempt}분 경과)")


# ════════════════════════════════════════════════════════════════
#  3. 백그라운드 모니터 — daemon 스레드
# ════════════════════════════════════════════════════════════════

class UpbitHealthMonitor(threading.Thread):
    """
    1분 간격으로 API 응답 속도를 측정합니다.

    · 응답 느림(>3초)이 _SLOW_COUNT_ALERT(3회) 연속 → 사전 경보 전송
    · 응답 없음 → wait_until_alive() 호출 (점검 확정)
    · 정상 복귀 시 경보 카운터 초기화

    main.py run() 최상단:
        monitor = UpbitHealthMonitor(coin)
        monitor.start()

    daemon=True — 봇 프로세스 종료 시 자동 종료.
    """

    def __init__(self, coin: str):
        super().__init__(name=f"health-{coin}", daemon=True)
        self.coin        = coin
        self._slow_count = 0          # 연속 느림 횟수
        self._alerted    = False      # 사전 경보 중복 방지

    def run(self) -> None:
        log("INFO", f"[health] 모니터 시작 ({self.coin}, 주기={_MONITOR_INTERVAL}초)")

        while True:
            try:
                elapsed = _measure_response_time()

                if elapsed is None:
                    # 응답 없음 — 점검 확정
                    log("WARN", f"[health] API 무응답 감지 ({self.coin})")
                    self._slow_count = 0
                    self._alerted    = False
                    wait_until_alive(self.coin)

                elif elapsed > _SLOW_THRESHOLD:
                    # 응답 느림
                    self._slow_count += 1
                    log("WARN", f"[health] API 응답 느림: {elapsed:.2f}초 "
                        f"({self._slow_count}/{_SLOW_COUNT_ALERT}회 연속)")

                    if self._slow_count >= _SLOW_COUNT_ALERT and not self._alerted:
                        self._send_slow_alert(elapsed)
                        self._alerted = True

                else:
                    # 정상
                    if self._slow_count > 0:
                        log("INFO", f"[health] API 응답 정상 복귀: {elapsed:.2f}초")
                    self._slow_count = 0
                    self._alerted    = False

            except Exception as e:
                log("DG", f"[health] 모니터 예외: {e}")

            time.sleep(_MONITOR_INTERVAL)

    def _send_slow_alert(self, elapsed: float) -> None:
        """응답 느림 사전 경보 텔레그램 전송."""
        from mod_telegram import send_telegram_msg, _CHAT_MONITOR, _chat_id_for

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = (
            f"⚠️ *[업비트 API 응답 저하]*\n"
            f"`{now_str}`\n"
            f"──────────────────\n"
            f"코인: `{self.coin}`\n"
            f"응답시간: `{elapsed:.2f}초` "
            f"(기준: {_SLOW_THRESHOLD}초)\n"
            f"연속 {_SLOW_COUNT_ALERT}회 감지\n"
            f"──────────────────\n"
            f"⏳ 점검 임박 가능성이 있습니다.\n"
            f"업비트 공지를 확인해 주세요.\n"
            f"https://upbit.com/service_center/notice"
        )
        send_telegram_msg(msg, chat_id=_CHAT_MONITOR)
        send_telegram_msg(msg, chat_id=_chat_id_for(self.coin))
        log("WARN", f"[health] 응답 느림 경보 전송 ({elapsed:.2f}초)")


# ════════════════════════════════════════════════════════════════
#  테스트
# ════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=== 업비트 API 헬스체크 ===")
    alive = is_upbit_alive()
    print(f"API 상태: {'✅ 정상' if alive else '❌ 점검 중 또는 네트워크 오류'}")

    print()
    print("=== API 응답 시간 측정 ===")
    elapsed = _measure_response_time()
    if elapsed is not None:
        status = "🐢 느림 (경보 대상)" if elapsed > _SLOW_THRESHOLD else "✅ 정상"
        print(f"응답시간: {elapsed:.3f}초 — {status}")
    else:
        print("❌ 응답 없음 (점검 중 또는 네트워크 오류)")