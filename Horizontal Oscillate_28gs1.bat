@echo off
set VIRTUAL_ENV=C:\Users\%username%\.DS-MV_28
set PROMPT=$P$G
set PROMPT=(.DS-MV_28) %PROMPT%
set PATH=%VIRTUAL_ENV%\Scripts;%PATH%

set /p INTERVAL="Interval seconds between each move (default 5): "
if "%INTERVAL%"=="" set INTERVAL=5

python ..\horizontal_oscillate.py -i %INTERVAL%
pause
