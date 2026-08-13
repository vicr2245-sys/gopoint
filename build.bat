@echo off
setlocal

echo ============================================
echo  GoPoint - Build Script
echo ============================================
echo.

rem Resolve Python once, then use `python -m ...` for both pip and
rem PyInstaller. Some Windows installations do not put pip.exe on PATH,
rem even though Python (and pip as a module) is installed correctly.
set "PYTHON_CMD="
where py >nul 2>nul
if not errorlevel 1 (
    py -3.9 -c "import sys" >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py -3.9"
)
if not defined PYTHON_CMD (
    where python >nul 2>nul
    if not errorlevel 1 (
        python -c "import sys" >nul 2>nul
        if not errorlevel 1 set "PYTHON_CMD=python"
    )
)
if not defined PYTHON_CMD if exist "%LocalAppData%\Programs\Python\Python39\python.exe" (
    set "PYTHON_CMD="%LocalAppData%\Programs\Python\Python39\python.exe""
)
if not defined PYTHON_CMD (
    echo Python 3.9 was not found. Install Python or add it to PATH, then run this script again.
    exit /b 1
)

echo Installing/updating dependencies...
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Dependency installation failed. Fix the error above and try again.
    exit /b 1
)

%PYTHON_CMD% -m pip install -r requirements-build.txt
if errorlevel 1 (
    echo.
    echo PyInstaller installation failed. Fix the error above and try again.
    exit /b 1
)

echo.
echo Closing any running RoutePlanner processes...
taskkill /f /im RoutePlanner.exe 2>nul

echo.
echo Removing previous build output...
if exist dist\RoutePlanner\.env (
    echo Preserving your existing .env so this rebuild doesn't wipe your API keys...
    copy /Y dist\RoutePlanner\.env "%TEMP%\route_planner_env_backup.txt" >nul
)
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo.
echo Building RoutePlanner.exe ...
%PYTHON_CMD% -m PyInstaller route_planner.spec --noconfirm

if errorlevel 1 (
    echo.
    echo Build failed. Scroll up for the PyInstaller error.
    exit /b 1
)

echo.
echo Copying env.example.txt into the build folder...
if exist env.example.txt (
    copy /Y env.example.txt dist\RoutePlanner\env.example.txt >nul
) else (
    echo env.example.txt was not found; skipping example environment file.
)

if exist "%TEMP%\route_planner_env_backup.txt" (
    echo Restoring your .env from before this rebuild...
    copy /Y "%TEMP%\route_planner_env_backup.txt" dist\RoutePlanner\.env >nul
    del "%TEMP%\route_planner_env_backup.txt" >nul
)

echo.
echo ============================================
echo  Build complete!
echo.
echo  Your app is in:  dist\RoutePlanner\RoutePlanner.exe
echo.
echo  First time only: copy env.example.txt to .env in
echo  that same folder and fill in your API keys.
echo  (Rebuilding after this won't wipe it out anymore --
echo  your .env now carries over automatically.)
echo ============================================
echo.
pause
