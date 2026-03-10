@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ================================================
echo   ArknightsPassMaker - cx_Freeze + Inno Setup Build
echo ================================================
echo.

uv --version >nul 2>&1
if errorlevel 1 (
    echo [Error] uv not found! Please install uv: https://docs.astral.sh/uv/
    pause
    exit /b 1
)

echo Installing dependencies...
uv sync --group dev --no-install-project

set BUILD_ARGS=
set SHOW_HELP=0

:parse_args
if "%~1"=="" goto end_parse
if "%~1"=="--no-installer" (
    set BUILD_ARGS=%BUILD_ARGS% --no-installer
    shift
    goto parse_args
)
if "%~1"=="--clean" (
    set BUILD_ARGS=%BUILD_ARGS% --clean
    shift
    goto parse_args
)
if "%~1"=="--help" (
    set SHOW_HELP=1
    shift
    goto parse_args
)
if "%~1"=="-h" (
    set SHOW_HELP=1
    shift
    goto parse_args
)
shift
goto parse_args
:end_parse

if %SHOW_HELP%==1 (
    echo.
    echo Usage: build.bat [options]
    echo.
    echo Options:
    echo   --no-installer   Skip Inno Setup packaging
    echo   --clean          Clean build directories first
    echo   --help, -h       Show this help message
    echo.
    echo Examples:
    echo   build.bat                  Build with installer
    echo   build.bat --no-installer   Build without installer
    echo   build.bat --clean          Clean build
    echo.
    goto end
)

echo.
echo Building...
echo.

uv run python build.py%BUILD_ARGS%

:end

echo.
echo Done!
pause
