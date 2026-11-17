# VS Code에서 바로 시작하기 (Windows)

## 1. 준비
Python 3.11 이상, VS Code, VS Code Python 확장 설치. 이 폴더를 VS Code에서 **폴더 열기**로 엽니다.

## 2. 설치 (PowerShell 터미널)
```powershell
.\scripts\setup_windows.ps1
```
스크립트 실행이 차단되면 아래 명령을 직접 입력합니다.
```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## 3. 실행
```powershell
.\scripts\run_windows.ps1
```
또는
```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```
브라우저: http://127.0.0.1:8000/nationwide (전국 법규 검토), http://127.0.0.1:8000/dashboard (현금흐름), http://127.0.0.1:8000/docs (API).

## 4. 개발 순서
1. `docs/01_시스템_체계도.md` 확인
2. `app/nationwide.py` 조례 검토 규칙, `app/engine.py` PF 계산 엔진 확인
3. `samples/general.json` 및 `samples/renewal.json`에서 **가상 데이터** 수정
4. `tests/`에서 테스트 추가 후 실행
5. 날짜별 거래 원장·PF waterfall·법규 검증 승인 워크플로 구현

## 주의
실제 사업지의 조례·고시 및 인허가 조건은 전문가 검증이 필요합니다. 등록 API에 인증이 없어 외부 서버 공개 금지. 현재는 사업수지 확정용이 아닌 개발용 프로토타입입니다.
