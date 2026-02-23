import requests

# ================= 설정 영역 =================
# username : mcc96_bot
# 
TELEGRAM_TOKEN = "8527006921:AAG_uJfVc6X2pQZlE5dKmkonq2xjFuSoB5o"
CHAT_ID = "8226863404"
# ============================================

def send_telegram_msg(message):
    """
    텔레그램 봇을 통해 메시지를 전송하는 함수입니다.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()  # 전송 실패 시 에러 발생
        print("텔레그램 알림 전송 성공")
    except Exception as e:
        print(f"텔레그램 알림 전송 실패: {e}")

# 테스트용 실행 코드
if __name__ == "__main__":
    send_telegram_msg("🚀 코딩 파트너: 텔레그램 봇 테스트 메시지입니다!")