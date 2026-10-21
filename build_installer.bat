@echo off
REM Cree l'installeur Windows : dist\IPTVPlayer-Setup-<version>.exe (application + VLC embarque).
REM Usage : build_installer.bat
REM La version est celle de iptvplayer\__init__.py (__version__) : l'appli s'en sert pour savoir si une
REM mise a jour est disponible, elle doit donc etre augmentee avant chaque nouvel installeur.
REM Prerequis : ceux de build_windows.bat, VLC 64 bits installe (ou VLC_DIR), Inno Setup 6.
cd /d "%~dp0"
set ISCC=
for %%d in ("%LOCALAPPDATA%\Programs\Inno Setup 6" "%ProgramFiles(x86)%\Inno Setup 6" "%ProgramFiles%\Inno Setup 6") do (
  if exist "%%~d\ISCC.exe" set ISCC="%%~d\ISCC.exe"
)
if not defined ISCC (
  echo ERREUR : Inno Setup 6 introuvable. Installe-le : winget install JRSoftware.InnoSetup
  pause
  exit /b 1
)

REM Ancienne compilation supprimee : si PyInstaller echoue, l'exe absent arrete le script.
if exist dist\IPTVPlayer rmdir /s /q dist\IPTVPlayer
call "%~dp0build_windows.bat" nopause
if not exist dist\IPTVPlayer\IPTVPlayer.exe goto erreur
set VERSION=
for /f %%v in ('.venv\Scripts\python.exe -c "import iptvplayer; print(iptvplayer.__version__)"') do set VERSION=%%v
if not defined VERSION goto erreur
call "%~dp0tools\bundle_vlc.bat" dist\IPTVPlayer || goto erreur
%ISCC% /Q /DAppVersion=%VERSION% installer\IPTVPlayer.iss || goto erreur
echo.
echo Termine. Installeur : dist\IPTVPlayer-Setup-%VERSION%.exe
pause
exit /b 0

:erreur
echo.
echo ECHEC de la creation de l'installeur.
pause
exit /b 1
