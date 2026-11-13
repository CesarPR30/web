@echo off
chcp 65001 >nul
cd /d "%~dp0"
python actualizar.py %*
if errorlevel 1 (
  echo.
  echo No se pudo actualizar. Revisa el mensaje de arriba.
  pause
  exit /b 1
)
start "" "dashboard\index.html"
pause
