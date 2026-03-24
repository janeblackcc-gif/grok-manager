@echo off
echo Building Grok Manager...
pip install -r requirements.txt

:: Dynamically discover pywin32 DLL paths (works across Python versions)
set PYWIN32_DIR=
for /f "delims=" %%i in ('python -c "import pywintypes; import os; print(os.path.dirname(pywintypes.__file__))"') do set PYWIN32_DIR=%%i

set WIN32_DIR=
for /f "delims=" %%i in ('python -c "import win32api; import os; print(os.path.dirname(win32api.__file__))"') do set WIN32_DIR=%%i

:: Discover actual DLL filenames dynamically
set PYWINTYPES_DLL=
for /f "delims=" %%i in ('python -c "import glob,pywintypes,os; d=os.path.dirname(pywintypes.__file__); f=glob.glob(os.path.join(d,'pywintypes*.dll')); print(f[0] if f else '')"') do set PYWINTYPES_DLL=%%i

set PYTHONCOM_DLL=
for /f "delims=" %%i in ('python -c "import glob,pywintypes,os; d=os.path.dirname(pywintypes.__file__); f=glob.glob(os.path.join(d,'pythoncom*.dll')); print(f[0] if f else '')"') do set PYTHONCOM_DLL=%%i

echo pywin32_system32: %PYWIN32_DIR%
echo win32 dir: %WIN32_DIR%
echo pywintypes dll: %PYWINTYPES_DLL%
echo pythoncom dll: %PYTHONCOM_DLL%

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

pyinstaller --onefile --noconsole --name "GrokManager" ^
  --icon=assets\icon.ico ^
  --add-data "assets;assets" ^
  --runtime-hook=runtime_hook.py ^
  --hidden-import=win32api ^
  --hidden-import=win32job ^
  --hidden-import=win32process ^
  --hidden-import=pywintypes ^
  --hidden-import=win32con ^
  --add-binary "%PYWINTYPES_DLL%;." ^
  --add-binary "%PYTHONCOM_DLL%;." ^
  --add-binary "%WIN32_DIR%\win32api.pyd;." ^
  --add-binary "%WIN32_DIR%\win32job.pyd;." ^
  --add-binary "%WIN32_DIR%\win32process.pyd;." ^
  --collect-all=customtkinter ^
  main_gui.py

echo Done! Output: dist\GrokManager.exe
pause
