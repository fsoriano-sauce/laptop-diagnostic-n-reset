@echo off
rem stage.cmd <USB drive letter with colon> [-NoInstall]
rem Called by autounattend.xml during the specialize pass (runs as SYSTEM,
rem before the first OOBE screen). Hands off to stage.ps1, which copies the
rem drivers to C:\Dell first so a USB re-enumeration mid-install cannot
rem break the run. Logs go to C:\Dell\Reports and are copied back to the
rem USB by stage.ps1 at the end.
rem Manual run from a Shift+F10 prompt at the OOBE screen:  D:\Dell\Scripts\stage.cmd D:
rem Test on any Windows PC (no install, report to the USB):   stage.cmd E: -NoInstall
set "USB=%~1"
if "%USB%"=="" set "USB=%~d0"
if "%USB:~-1%"=="\" set "USB=%USB:~0,-1%"
if /I "%~2"=="-NoInstall" (set "LOGDIR=%USB%\Dell\Reports") else (set "LOGDIR=%SystemDrive%\Dell\Reports")
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
echo %DATE% %TIME% stage.cmd start usb=%USB% %2 >> "%LOGDIR%\_stage-cmd.log"
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "%~dp0stage.ps1" -Usb "%USB%" %2 >> "%LOGDIR%\_stage-cmd.log" 2>&1
echo %DATE% %TIME% stage.cmd end rc=%ERRORLEVEL% >> "%LOGDIR%\_stage-cmd.log"
rem stage.ps1 already copied the reports to the USB; append the end line there too if the stick is reachable
for %%d in (D E F G H I J K L M N) do @if exist "%%d:\Dell\Scripts\stage.cmd" (echo %DATE% %TIME% stage.cmd end rc=%ERRORLEVEL% >> "%%d:\Dell\Reports\_stage-cmd.log" & goto :done)
:done
exit /b 0
