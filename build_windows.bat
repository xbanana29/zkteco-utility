@echo off
title ZKTeco Utility — Windows Build
echo ============================================
echo  ZKTeco eFace10 Utility — Windows Build
echo ============================================
echo.

echo [1/3] Install dependencies...
pip install pyzk openpyxl pyinstaller --quiet

echo.
echo [2/3] Build exe...
pyinstaller --onefile --windowed ^
  --name "ZKTeco_Utility" ^
  --collect-all openpyxl ^
  --collect-all zk ^
  --hidden-import openpyxl ^
  --hidden-import openpyxl.styles ^
  --hidden-import openpyxl.styles.fills ^
  --hidden-import openpyxl.styles.fonts ^
  --hidden-import openpyxl.styles.borders ^
  --hidden-import openpyxl.styles.alignment ^
  --hidden-import openpyxl.utils ^
  --hidden-import openpyxl.worksheet ^
  --hidden-import openpyxl.formatting ^
  --hidden-import zk ^
  --hidden-import zk.base ^
  --hidden-import zk.exception ^
  --hidden-import zk.user ^
  --hidden-import zk.attendance ^
  --exclude-module pandas ^
  --exclude-module numpy ^
  --exclude-module scipy ^
  --exclude-module matplotlib ^
  --exclude-module PIL ^
  --exclude-module sklearn ^
  --exclude-module IPython ^
  --exclude-module pytest ^
  --exclude-module unittest ^
  --exclude-module turtle ^
  zkteco_app.py

if %errorlevel% neq 0 (
    echo ERROR: Build gagal.
    pause & exit /b 1
)

echo.
echo [3/3] Selesai!
echo.
echo ============================================
echo  EXE: dist\ZKTeco_Utility.exe
echo  Taruh EXE di folder tersendiri agar
echo  config.json dan absensi.db tersimpan rapi.
echo ============================================
pause
