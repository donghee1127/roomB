@echo off
set VIRTUAL_ENV=C:\Users\%username%\.DS-MV_28
set PROMPT=$P$G
set PROMPT=(.DS-MV_28) %PROMPT%
set PATH=%VIRTUAL_ENV%\Scripts;%PATH%
python ..\mvcontrol.py -d 0 -m "28 GS"
