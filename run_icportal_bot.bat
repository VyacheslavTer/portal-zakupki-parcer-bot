@echo off
cd /d "C:\repa\Icportal parser"
"C:\Users\v.terechshenko\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m icportal_bot run >> "C:\repa\Icportal parser\data\scheduler.log" 2>&1
