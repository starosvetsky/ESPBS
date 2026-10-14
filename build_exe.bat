@echo off
setlocal
cd /d "%~dp0"
if not exist .venv py -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

pyinstaller --noconfirm --clean --onefile --windowed ^
  --name "EnergoStorParser_v0.5" ^
  --collect-all bs4 ^
  --collect-all lxml ^
  --add-data "config;sources_config" ^
  app.py

echo.
echo READY:
echo %CD%\dist\EnergoStorParser_v0.5.exe
pause
