@echo off
cd /d "C:\repa\Icportal parser"
set "PY=C:\Users\v.terechshenko\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "LOG=C:\repa\Icportal parser\data\scheduler.log"
set "SETUP_LOG=C:\repa\Icportal parser\data\scheduler_setup.log"

echo ==== ICPortal bot start %date% %time% ==== >> "%LOG%"

"%PY%" -c "import playwright" >nul 2>&1
if errorlevel 1 (
  "%PY%" -m pip install -r requirements.txt >> "%SETUP_LOG%" 2>&1
)

"%PY%" -m playwright install chromium >> "%SETUP_LOG%" 2>&1
"%PY%" -u -m icportal_bot run >> "%LOG%" 2>&1
echo ==== ICPortal bot end %date% %time% exit %errorlevel% ==== >> "%LOG%"
