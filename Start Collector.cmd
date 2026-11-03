@echo off
if not defined VOICE_INTERVIEWER_PYTHON (
  echo Set VOICE_INTERVIEWER_PYTHON to an existing compatible Python executable.
  exit /b 1
)
if not exist "%VOICE_INTERVIEWER_PYTHON%" (
  echo The configured Python executable does not exist.
  exit /b 1
)
"%VOICE_INTERVIEWER_PYTHON%" -I -B "%~dp0launcher.py" %*
if errorlevel 1 pause
