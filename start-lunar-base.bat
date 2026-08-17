@echo off
setlocal enabledelayedexpansion

rem  Lunar Base - launcher for Windows.
rem
rem  Double-click this file, or from a terminal:
rem      start-lunar-base.bat
rem      start-lunar-base.bat --prefer-saved
rem      start-lunar-base.bat --yes
rem      start-lunar-base.bat --lunar-tear "D:\games\lunar-tear"
rem
rem  Unlike the Linux script this cannot install Python for you -- Windows
rem  has no package manager it can rely on -- so it checks for a suitable
rem  Python and tells you where to get one if it is missing.

set "SCRIPT_DIR=%~dp0"
set "WIZARD=%SCRIPT_DIR%start-lunar-base.py"

echo.
echo   =====================================================
echo              LUNAR BASE - setup and launcher
echo       Web manager for a Lunar Tear private server
echo   =====================================================
echo.

if not exist "%WIZARD%" (
    echo [x] Wizard not found: %WIZARD%
    echo [-] Run this from inside the lunar-base folder.
    goto :fail
)

rem  Prefer the py launcher, which is what python.org installs ship with.
set "PY_CMD="
where py >nul 2>&1
if !errorlevel! equ 0 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if !errorlevel! equ 0 set "PY_CMD=py -3"
)

if not defined PY_CMD (
    where python >nul 2>&1
    if !errorlevel! equ 0 (
        python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
        if !errorlevel! equ 0 set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    echo [x] No Python 3.10 or newer found.
    echo.
    echo [-] Install Python from https://www.python.org/downloads/
    echo [-] Tick "Add python.exe to PATH" in the installer, then run this again.
    goto :fail
)

for /f "delims=" %%v in ('%PY_CMD% -c "import platform; print(platform.python_version())"') do set "PY_VER=%%v"
echo [+] Python %PY_VER%
echo.
echo [-] Handing over to the setup wizard...
echo.

%PY_CMD% "%WIZARD%" %*
if !errorlevel! neq 0 goto :fail

endlocal
exit /b 0

:fail
echo.
echo [x] Setup did not complete.
echo.
pause
endlocal
exit /b 1
