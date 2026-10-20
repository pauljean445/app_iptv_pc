@echo off
REM Lance l'appli depuis les sources, sans fenetre console.
REM Premier lancement : cree l'environnement Python et installe les dependances.
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe main.py
