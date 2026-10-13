@echo off
cd /d "C:\repa\Icportal parser"
set "PY=C:\Users\v.terechshenko\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "LOG=C:\repa\Icportal parser\data\health.log"

echo ==== ICPortal health start %date% %time% ==== >> "%LOG%"
"%PY%" -u -m icportal_bot health-check >> "%LOG%" 2>&1
echo ==== ICPortal health end %date% %time% exit %errorlevel% ==== >> "%LOG%"
