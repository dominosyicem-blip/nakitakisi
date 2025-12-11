@echo off
REM recreate_venv_py311_and_build.bat -- Python 3.11 ile temiz venv oluşturup PyInstaller onefile build yapar
cd /d "%~dp0"

echo Checking for Python 3.11 (py -3.11)...
py -3.11 --version >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python 3.11 bulunamadi. Lutfen Python 3.11'in PATH'e eklendiginden veya py launcher'in kurulu oldugundan emin olun.
  echo Python 3.11'i kurduysan yeni bir CMD penceresi açıp tekrar deneyin.
  pause
  exit /b 1
)

echo Removing old .venv311 if exists...
if exist .venv311 rmdir /s /q .venv311

echo Creating venv with Python 3.11...
py -3.11 -m venv .venv311
if errorlevel 1 (
  echo venv olusturma basarisiz.
  pause
  exit /b 1
)

echo Upgrading pip/setuptools/wheel...
.venv311\Scripts\python -m pip install --upgrade pip setuptools wheel > pip_install_log.txt 2>&1

echo Installing numpy, pandas, matplotlib, pyinstaller...
.venv311\Scripts\python -m pip install --upgrade numpy pandas matplotlib pyinstaller >> pip_install_log.txt 2>&1

echo Cleaning old build artifacts...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist app.spec del /f /q app.spec

echo Building with PyInstaller (onefile)...
set "ADDFLAGS="
if exist "autosave.csv" set "ADDFLAGS=%ADDFLAGS% --add-data \"autosave.csv;.\""
if exist "data.db" set "ADDFLAGS=%ADDFLAGS% --add-data \"data.db;.\""

.venv311\Scripts\python -m PyInstaller --clean --onefile --noconsole %ADDFLAGS% app.py > build_log.txt 2>&1

if exist "dist\app.exe" (
  echo.
  echo BUILD SUCCESS: dist\app.exe oluşturuldu.
  echo Eğer exe'yi test etmek isterseniz: dist\app.exe
  pause
  exit /b 0
)

echo.
echo Onefile build basarisiz. Onedir fallback deneniyor...
.venv311\Scripts\python -m PyInstaller --clean --onedir --noconsole %ADDFLAGS% app.py >> build_log.txt 2>&1

if exist "dist\app\app.exe" (
  echo.
  echo FALLBACK SUCCESS: dist\app\app.exe oluşturuldu (onedir).
  pause
  exit /b 0
)

echo.
echo BUILD FAILED. Lütfen build_log.txt ve pip_install_log.txt dosyalarını buraya yapıştırın.
echo - build_log.txt
echo - pip_install_log.txt
pause