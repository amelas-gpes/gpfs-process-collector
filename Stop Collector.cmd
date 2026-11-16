@echo off
setlocal EnableExtensions DisableDelayedExpansion
if not defined VOICE_INTERVIEWER_PYTHON goto missing
set "collector_python=%VOICE_INTERVIEWER_PYTHON:"=%"
if not exist "%collector_python%" goto missing
if exist "%collector_python%\NUL" goto missing
for %%I in ("%collector_python%") do if /i not "%%~xI"==".exe" goto missing
"%collector_python%" -I -B "%~dp0launcher.py" --stop %*
set "collector_exit=%errorlevel%"
if /i not "%COLLECTOR_NONINTERACTIVE%"=="1" pause
exit /b %collector_exit%
:missing
echo Set VOICE_INTERVIEWER_PYTHON to the path of an existing compatible Python executable.
if /i not "%COLLECTOR_NONINTERACTIVE%"=="1" pause
exit /b 1
