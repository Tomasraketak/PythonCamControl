@echo off
rem Spuštění aplikace BMS Cam Control ve Windows.
rem Při prvním spuštění vytvoří virtuální prostředí a doinstaluje závislosti.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Vytvarim virtualni prostredi...
    py -3 -m venv .venv || python -m venv .venv || goto :err
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :err
)
".venv\Scripts\python.exe" main.py %*
if errorlevel 2 (
    echo.
    echo Diagnostika Qt:
    ".venv\Scripts\python.exe" main.py --doctor
    pause
)
goto :eof
:err
echo.
echo Neco se nepovedlo. Zkontrolujte, ze je nainstalovan Python 3.8 nebo novejsi.
pause
