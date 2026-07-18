@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

set "VENV_DIR=.venv-build"
set "OUT_DIR=dist"
set "PYTHON="

if defined PYTHON_BIN (
    set "PYTHON=%PYTHON_BIN%"
    goto :got_python
)

for %%V in (3.13 3.12 3.11 3.10) do (
    if not defined PYTHON (
        py -%%V --version >nul 2>&1 && set "PYTHON=py -%%V"
    )
)
if not defined PYTHON (
    python --version >nul 2>&1 && set "PYTHON=python"
)
if not defined PYTHON (
    echo error: no python interpreter found. Install Python from python.org 1>&2
    exit /b 1
)

:got_python
for /f "delims=" %%V in ('%PYTHON% --version 2^>^&1') do set "PYVER=%%V"
echo ==^> Using %PYVER% (%PYTHON%)

if exist "%VENV_DIR%" rmdir /s /q "%VENV_DIR%"
%PYTHON% -m venv "%VENV_DIR%" || exit /b 1
set "VPY=%VENV_DIR%\Scripts\python.exe"

echo ==^> Installing build dependencies...
"%VPY%" -m pip install --upgrade pip >nul || exit /b 1
"%VPY%" -m pip install ".[discord,voice]" >nul || exit /b 1
"%VPY%" -m pip install --upgrade pyinstaller >nul || exit /b 1

echo ==^> Checking the sources compile...
"%VPY%" -m compileall -q src\cutecat || (
    echo error: the sources do not compile on this Python. 1>&2
    exit /b 1
)

echo ==^> Bundling with PyInstaller (this takes a minute)...
"%VPY%" -m PyInstaller ^
    --onefile ^
    --noconfirm ^
    --noupx ^
    --name cutecat ^
    --distpath "%OUT_DIR%" ^
    --workpath build ^
    --specpath build ^
    --collect-all cutecat ^
    --collect-all textual ^
    --collect-all discord ^
    --collect-all certifi ^
    --collect-all faster_whisper ^
    --collect-all av ^
    --collect-all ctranslate2 ^
    --collect-all onnxruntime ^
    --collect-all tokenizers ^
    --collect-all huggingface_hub ^
    --collect-all tqdm ^
    --collect-all yaml ^
    entry.py || exit /b 1

echo.
echo ==^> Done. Binary at %OUT_DIR%\cutecat.exe
echo ==^> Quick check: echo /exit ^| %OUT_DIR%\cutecat.exe
endlocal
