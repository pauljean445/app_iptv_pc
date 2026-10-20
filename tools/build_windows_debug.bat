@echo off
REM Version "diagnostic" : meme application mais avec une console qui affiche les erreurs.
cd /d "%~dp0.."
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --onedir --console --name IPTVPlayer_debug ^
  --icon "%~dp0..\assets\icon.ico" --add-data "%~dp0..\assets\icon.ico;assets" ^
  --workpath "%TEMP%\iptvplayer_build" --specpath "%TEMP%\iptvplayer_build" ^
  --exclude-module tkinter --exclude-module unittest --exclude-module pydoc --exclude-module doctest ^
  --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtOpenGL ^
  main.py
call "%~dp0slim_dist.bat" dist\IPTVPlayer_debug
echo.
echo Termine. Lance dist\IPTVPlayer_debug\IPTVPlayer_debug.exe depuis une invite de commandes pour voir les messages.
pause
