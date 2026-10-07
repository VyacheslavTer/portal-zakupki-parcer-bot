@echo off
cd /d "C:\repa\Icportal parser"
set "PY=C:\Users\v.terechshenko\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

"%PY%" -c "import playwright" >nul 2>&1
if errorlevel 1 (
  "%PY%" -m pip install -r requirements.txt >> "C:\repa\Icportal parser\data\scheduler_setup.log" 2>&1
)

"%PY%" -m playwright install chromium >> "C:\repa\Icportal parser\data\scheduler_setup.log" 2>&1
"%PY%" -m icportal_bot run >> "C:\repa\Icportal parser\data\scheduler.log" 2>&1
