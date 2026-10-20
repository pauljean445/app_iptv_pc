#!/usr/bin/env bash
# Crée l'application Linux/macOS : dist/IPTVPlayer/IPTVPlayer
# Mode « dossier » (--onedir) : démarrage bien plus rapide que --onefile.
set -e
cd "$(dirname "$0")/.."
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --onedir --windowed --name IPTVPlayer \
  --icon "$PWD/assets/icon.ico" --add-data "$PWD/assets/icon.ico:assets" \
  --workpath "${TMPDIR:-/tmp}/iptvplayer_build" --specpath "${TMPDIR:-/tmp}/iptvplayer_build" \
  --exclude-module tkinter --exclude-module unittest --exclude-module pydoc --exclude-module doctest \
  --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtOpenGL \
  main.py
# Fichiers Qt inutiles pour cette appli
rm -rf dist/IPTVPlayer/_internal/PySide6/translations dist/IPTVPlayer/_internal/PySide6/Qt/translations
echo
echo "Terminé. Application : dist/IPTVPlayer/IPTVPlayer"
