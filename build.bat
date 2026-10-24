@echo off
setlocal

REM Папка для распаковки ресурсов PyInstaller
set RUNTIME_TMPDIR=C:\DockerHubLiteTemp
REM Папка для данных (repos, history.json) — не удаляется
set DATA_DIR=%RUNTIME_TMPDIR%\Files

REM Создаём папки, если их нет
if not exist "%RUNTIME_TMPDIR%" (
    mkdir "%RUNTIME_TMPDIR%"
    echo Создана папка: %RUNTIME_TMPDIR%
)
if not exist "%DATA_DIR%" (
    mkdir "%DATA_DIR%"
    echo Создана папка данных: %DATA_DIR%
)

REM Убедитесь, что активировано виртуальное окружение
REM и установлены все зависимости + pyinstaller

pyinstaller --onefile --name DockerHubLite ^
  --runtime-tmpdir "%RUNTIME_TMPDIR%" ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  --hidden-import uvicorn.logging ^
  --hidden-import uvicorn.loops.auto ^
  --hidden-import uvicorn.protocols.http.auto ^
  --hidden-import uvicorn.protocols.websockets.auto ^
  --hidden-import fastapi.openapi.utils ^
  --hidden-import httpx ^
  --hidden-import dockerfile ^
  run.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ❌ Сборка завершилась с ошибкой (код %ERRORLEVEL%).
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ✅ Сборка завершена. Файл: dist\DockerHubLite.exe
echo 📂 Ресурсы распаковываются в: %RUNTIME_TMPDIR%
echo 💾 Данные (repos, history.json) хранятся в: %DATA_DIR%
pause
endlocal