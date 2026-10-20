@echo off
REM Retire de l'application compilee les fichiers Qt inutiles (~35 Mo). Usage : slim_dist.bat dist\IPTVPlayer
set I=%~1\_internal
set Q=%I%\PySide6
REM OpenGL logiciel (20 Mo) : inutile, la video est rendue par VLC
del /q "%Q%\opengl32sw.dll" 2>nul
REM Traductions de Qt : non chargees par l'appli
rmdir /s /q "%Q%\translations" 2>nul
REM Plateformes : seule la fenetre Windows standard sert
del /q "%Q%\plugins\platforms\qdirect2d.dll" "%Q%\plugins\platforms\qminimal.dll" "%Q%\plugins\platforms\qoffscreen.dll" 2>nul
REM Formats d'image : on garde jpeg, png (integre), gif, webp, ico
del /q "%Q%\plugins\imageformats\qicns.dll" "%Q%\plugins\imageformats\qtga.dll" "%Q%\plugins\imageformats\qtiff.dll" "%Q%\plugins\imageformats\qwbmp.dll" "%Q%\plugins\imageformats\qsvg.dll" 2>nul
rmdir /s /q "%Q%\plugins\iconengines" 2>nul
rmdir /s /q "%Q%\plugins\generic" 2>nul
del /q "%Q%\Qt6Svg.dll" 2>nul
REM TLS : le backend natif Windows (schannel) suffit ; OpenSSL pour Qt n'est pas necessaire
del /q "%Q%\plugins\tls\qopensslbackend.dll" "%Q%\plugins\tls\qcertonlybackend.dll" 2>nul
del /q "%I%\libcrypto-3-x64.dll" "%I%\libssl-3-x64.dll" 2>nul
exit /b 0
