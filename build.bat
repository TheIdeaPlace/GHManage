@echo off
REM ── GHManage build script ─────────────────────────────────────────────
REM Run from the repo root.
REM
REM Usage:
REM   build.bat              — build dist\ghmanage\ (app folder)
REM   build.bat installer    — also pack the Velopack installer + update feed
REM   build.bat clean        — remove build artifacts first, then build
REM
REM The build is --onedir, not --onefile: Velopack replaces an app folder in
REM place, and a onefile exe both blows past Velopack's 15s hook timeout
REM (it re-extracts ~17MB on every launch, including update hooks) and makes
REM deltas useless, since the whole app is a single opaque blob.
REM ─────────────────────────────────────────────────────────────────────

setlocal

where python >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found on PATH. Install Python 3.9+ and retry.
    exit /b 1
)

if /i "%1"=="clean" (
    echo Cleaning build artifacts...
    if exist dist rmdir /s /q dist
    if exist build rmdir /s /q build
    if exist ghmanage.spec del /q ghmanage.spec
    echo Done.
)

if not exist .venv (
    echo Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo Error: Failed to create virtual environment.
        exit /b 1
    )
)

if not exist .venv\Scripts\activate.bat (
    echo Error: .venv\Scripts\activate.bat not found. The venv is broken.
    exit /b 1
)
call .venv\Scripts\activate.bat
if errorlevel 1 (
    echo Error: Failed to activate virtual environment.
    exit /b 1
)
if not defined VIRTUAL_ENV (
    echo Error: Virtual environment activation did not take effect.
    exit /b 1
)
echo Using venv: %VIRTUAL_ENV%

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Error: Failed to install project dependencies.
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 (
    echo Error: Failed to install PyInstaller.
    exit /b 1
)

REM Read the version from version.py so there is one source of truth.
REM The venv is active, so plain `python` is the venv interpreter. Quoting the
REM full exe path here breaks cmd's for/f parsing.
for /f "usebackq delims=" %%v in (`python -c "from version import __version__; print(__version__)"`) do set APP_VERSION=%%v
if not defined APP_VERSION (
    echo Error: Could not read version from version.py.
    exit /b 1
)
echo Building GHManage %APP_VERSION%...

REM Product name, version and publisher for the .exe's Properties > Details.
python assets\make_version_info.py
if errorlevel 1 (
    echo Error: Failed to write the version resource.
    exit /b 1
)

REM --hidden-import velopack: updater.py imports it lazily inside functions so
REM the app still runs from source without it, which hides it from PyInstaller.
REM --hidden-import yaml: same reason — gh_data imports it inside
REM _parse_dispatch_spec, so it is only needed when setting up a manual run.
".venv\Scripts\python.exe" -m PyInstaller --noconsole --onedir --name ghmanage ^
    --icon assets\ghmanage.ico ^
    --version-file build\version_info.txt ^
    --hidden-import velopack --hidden-import yaml launch.py -y
if errorlevel 1 (
    echo Error: PyInstaller build failed.
    exit /b 1
)

if /i not "%1"=="installer" (
    echo.
    echo Build complete: dist\ghmanage\ghmanage.exe
    echo Run "build.bat installer" to also pack the installer.
    goto :eof
)

REM ── Velopack packaging ────────────────────────────────────────────────
REM vpk is a .NET global tool, not a Python package.
where vpk >nul 2>&1
if errorlevel 1 (
    echo Error: vpk not found. Install it with: dotnet tool install -g vpk
    exit /b 1
)

echo Packing Velopack installer and update feed...
vpk pack --packId GHManage --packVersion %APP_VERSION% ^
    --packDir dist\ghmanage --mainExe ghmanage.exe ^
    --packTitle "GHManage" --packAuthors "Kelly Ford" ^
    --icon assets\ghmanage.ico ^
    --outputDir installer\Releases ^
    --instLocation PerUser --shortcuts StartMenuRoot
if errorlevel 1 (
    echo Error: Velopack packaging failed.
    exit /b 1
)

echo.
echo Build complete: dist\ghmanage\ghmanage.exe
echo Installer and update feed: installer\Releases
echo.
echo Note: vpk overwrites GHManage-win-Setup.exe on each pack. To test an
echo upgrade, copy the old Setup.exe aside before packing the new version.
endlocal
