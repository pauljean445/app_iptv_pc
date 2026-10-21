@echo off
REM Lance l'appli depuis les sources sur une COPIE des donnees (%LOCALAPPDATA%\IPTVPlayer-dev),
REM pour essayer une version en cours sans toucher aux donnees de l'appli installee.
REM Premiere fois : copie reglages et profils de %APPDATA%\IPTVPlayer. Supprimer le dossier pour repartir de la.
cd /d "%~dp0"
set "IPTVPLAYER_DATA=%LOCALAPPDATA%\IPTVPlayer-dev"
if not exist "%IPTVPLAYER_DATA%" (
  if exist "%APPDATA%\IPTVPlayer" (
    robocopy "%APPDATA%\IPTVPlayer" "%IPTVPLAYER_DATA%" settings.json /NJH /NJS /NFL /NDL >nul
    robocopy "%APPDATA%\IPTVPlayer\profiles" "%IPTVPLAYER_DATA%\profiles" /E /NJH /NJS /NFL /NDL >nul
  )
)
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe main.py
