@echo off
rem stage.cmd <USB drive letter with colon> [-NoInstall]
rem Called by autounattend.xml during the specialize pass (runs as SYSTEM,
rem before the first OOBE screen). Hands off to stage.ps1.
rem Manual test on any Windows PC:  stage.cmd E: -NoInstall
set "USB=%~1"
if "%USB%"=="" set "USB=%~d0"
if "%USB:~-1%"=="\" set "USB=%USB:~0,-1%"
if not exist "%USB%\Dell\Reports" mkdir "%USB%\Dell\Reports"
echo %DATE% %TIME% stage.cmd start usb=%USB% %2 >> "%USB%\Dell\Reports\_stage-cmd.log"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0stage.ps1" -Usb "%USB%" %2 >> "%USB%\Dell\Reports\_stage-cmd.log" 2>&1
echo %DATE% %TIME% stage.cmd end rc=%ERRORLEVEL% >> "%USB%\Dell\Reports\_stage-cmd.log"
exit /b 0
