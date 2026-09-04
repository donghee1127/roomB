@echo off
REM ============================================================
REM CloudChaser 인터랙티브 세션 실행 (실험 PC용)
REM 더블클릭하거나 cmd 에서  cc  입력으로 실행.
REM
REM ※ 아래 두 경로는 본인 환경에 맞게 한 번만 수정하세요:
REM    - VENV  : 가상환경 activate.bat 경로 (.sivers)
REM    - REPO  : cloudchaser git 폴더
REM ============================================================
set "VENV=C:\Users\Dosan\.sivers\Scripts\activate.bat"
set "REPO=C:\Git_Software\Sejin\cloudchaser"

call "%VENV%"
cd /d "%REPO%"

REM IPython 진입 + 세션 명령 로드(전원은 자동 인가하지 않음 — start() 직접 호출).
ipython -i -c "from cloudchaser.session import start, help, status, restart; print(); print('>>> Run:  start(channels=[\"h1\"])   then  help()')"
