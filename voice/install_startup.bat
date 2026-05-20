@echo off
REM ─────────────────────────────────────────────────────────────────
REM  Add the Jarvis voice tray to Windows Startup so it launches at
REM  login. Creates a shortcut in the current user's Startup folder.
REM
REM  Run this once:  voice\install_startup.bat
REM  Remove:         delete the shortcut from
REM                  shell:startup  (paste that in Explorer's address bar)
REM ─────────────────────────────────────────────────────────────────

setlocal

REM Repo root = the parent of this script's folder
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "REPO_ROOT=%%~fI"
set "PYTHON=%REPO_ROOT%\.venv\Scripts\pythonw.exe"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP%\JarvisVoice.lnk"

if not exist "%PYTHON%" (
    echo ERROR: venv python not found at %PYTHON%
    echo Create the venv first, then re-run this script.
    exit /b 1
)

REM Use PowerShell to create the .lnk shortcut.
powershell -NoProfile -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $s = $ws.CreateShortcut('%SHORTCUT%'); ^
   $s.TargetPath = '%PYTHON%'; ^
   $s.Arguments  = '-m voice.jarvis_voice'; ^
   $s.WorkingDirectory = '%REPO_ROOT%'; ^
   $s.WindowStyle = 7; ^
   $s.Description = 'Jarvis voice tray'; ^
   $s.Save()"

if exist "%SHORTCUT%" (
    echo Installed: Jarvis voice tray will start at next login.
    echo Shortcut:  %SHORTCUT%
    echo To start it now without rebooting:
    echo   "%PYTHON%" -m voice.jarvis_voice
) else (
    echo ERROR: failed to create the startup shortcut.
    exit /b 1
)

endlocal
