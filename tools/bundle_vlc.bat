@echo off
REM Copie libVLC (dll + plugins) dans l'application compilee, pour qu'elle n'ait plus besoin de VLC installe.
REM Usage : bundle_vlc.bat dist\IPTVPlayer
REM VLC source : variable VLC_DIR si definie, sinon C:\Program Files\VideoLAN\VLC (VLC 64 bits).
setlocal
set DEST=%~1\vlc
if "%VLC_DIR%"=="" set VLC_DIR=%ProgramFiles%\VideoLAN\VLC
if not exist "%VLC_DIR%\libvlc.dll" (
  echo ERREUR : libvlc.dll introuvable dans "%VLC_DIR%".
  echo Installe VLC 64 bits, ou indique son dossier : set VLC_DIR=C:\chemin\vers\vlc
  exit /b 1
)
echo Copie de VLC depuis "%VLC_DIR%"...
if exist "%DEST%" rmdir /s /q "%DEST%"
REM Seuls libvlc, libvlccore et les plugins servent ; plugins\gui (interface de VLC, ~19 Mo) est inutile.
REM La diffusion Chromecast utilise de nombreux plugins (transcodage, encodeurs) : on garde tout le reste.
robocopy "%VLC_DIR%" "%DEST%" libvlc.dll libvlccore.dll COPYING.txt /njh /njs /nfl /ndl >nul
if errorlevel 8 exit /b 1
robocopy "%VLC_DIR%\plugins" "%DEST%\plugins" /e /xd gui /xf plugins.dat /njh /njs /nfl /ndl >nul
if errorlevel 8 exit /b 1
REM Index des plugins (plugins.dat) recalcule pour la liste reduite : demarrage plus rapide.
REM Sans lui, VLC fonctionne quand meme mais parcourt tous les plugins a chaque lancement.
if exist "%VLC_DIR%\vlc-cache-gen.exe" "%VLC_DIR%\vlc-cache-gen.exe" "%DEST%\plugins"
exit /b 0
