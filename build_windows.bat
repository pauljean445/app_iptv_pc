@echo off
REM Cree l'application Windows : dist\IPTVPlayer\IPTVPlayer.exe
REM Mode "dossier" (--onedir) : demarrage bien plus rapide que --onefile, qui decompresse
REM tout dans un dossier temporaire a chaque lancement.
REM Prerequis : Python 3.10+ (64 bits) installe et ajoute au PATH.
cd /d "%~dp0"
if not exist .venv python -m venv .venv
REM "python -m" plutot que pip.exe / pyinstaller.exe : ces lanceurs gardent en dur le chemin
REM du venv et ne marchent plus si le dossier du projet a ete deplace.
set PY=.venv\Scripts\python.exe
%PY% -m pip install -r requirements.txt pyinstaller
%PY% -m PyInstaller --noconfirm --clean --onedir --windowed --name IPTVPlayer ^
  --icon "%~dp0assets\icon.ico" --add-data "%~dp0assets\icon.ico;assets" ^
  --workpath "%TEMP%\iptvplayer_build" --specpath "%TEMP%\iptvplayer_build" ^
  --exclude-module tkinter --exclude-module unittest --exclude-module pydoc --exclude-module doctest ^
  --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtOpenGL ^
  main.py
call "%~dp0tools\slim_dist.bat" dist\IPTVPlayer
echo.
echo Termine. Application : dist\IPTVPlayer\IPTVPlayer.exe
echo (copie le dossier dist\IPTVPlayer ou tu veux ; .venv peut ensuite etre supprime)
if /i not "%~1"=="nopause" pause
