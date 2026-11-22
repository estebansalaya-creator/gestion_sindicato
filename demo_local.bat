@echo off
rem Levanta gestion_sindicato en http://localhost:5056 con el .env (base local desde el 22/11/2026).
rem Sin el contable de Railway: la demo no sale de esta maquina.
cd /d "%~dp0"
set SIND_CONTABLE_HOST=
set SIND_CONTABLE_USER=
set SIND_PORT=5056
echo.
echo  Demo en http://localhost:5056  -  administrador@demo.local / demo2026  (Ctrl+C para cortar)
echo.
python app.py
