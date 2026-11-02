@echo off
rem Esegue la scansione e apre la dashboard su http://localhost:8080
cd /d "%~dp0"
python scanner.py
start "" http://localhost:8080
cd docs
python -m http.server 8080
