import os
import sys
from dotenv import load_dotenv

def check_env():
    # 1. 현재 실행 중인 파이썬 인터프리터 경로 출력 (가상환경 확인용)
    print(f"현재 파이썬 경로: {sys.executable}")

    # 2. .env 파일 로드
    if load_dotenv():
        print("✅ .env 파일을 성공적으로 불러왔습니다.")
    else:
        print("❌ .env 파일을 찾을 수 없습니다. (파일명이 '.env'인지 확인하세요)")

    # 3. 환경 변수 읽기 테스트
    # .env 파일에 API_KEY=test_value 라고 적혀있다고 가정합니다.
    api_key = os.getenv("API_KEY")
    
    if api_key:
        print(f"✅ API_KEY 로드 성공: {api_key}")
    else:
        print("❌ API_KEY를 찾을 수 없습니다. .env 파일 내용을 확인하세요.")

if __name__ == "__main__":
    check_env()