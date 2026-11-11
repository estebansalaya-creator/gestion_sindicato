@echo off
REM ============================================================================
REM subir_github.bat - commit y push de gestion_sindicato a GitHub
REM   github.com/estebansalaya-creator/gestion_sindicato
REM
REM Sube TODO lo modificado y lo nuevo de esta carpeta (lo que no esta en
REM .gitignore: el .env, web.config, logs y adjuntos nunca suben).
REM El mensaje sale de mensaje_commit.txt si existe (y despues se borra);
REM si no, lo pide en una linea. Antes de commitear muestra todo y pregunta.
REM ============================================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".git" ( echo Esta carpeta no es un repositorio: correr antes C:\web\separar_sindicato.bat & goto :error )

git add -A
if errorlevel 1 goto :error
git diff --cached --quiet
if not errorlevel 1 (
  echo No hay nada para subir: esta todo commiteado.
  git push -q 2>nul
  goto :fin
)

echo.
echo === Lo que va a subir:
git status --short
echo.

if exist "mensaje_commit.txt" (
  echo === Mensaje ^(mensaje_commit.txt^):
  type mensaje_commit.txt | more
) else (
  set /p "MSG=Mensaje del commit: "
)
echo.
choice /c SN /m "Hacer el commit y subirlo a GitHub"
if errorlevel 2 (
  git reset -q
  echo Cancelado: no se subio nada y los archivos quedaron como estaban.
  goto :fin
)

if exist "mensaje_commit.txt" (
  git commit -q -F mensaje_commit.txt
) else (
  if not defined MSG set "MSG=Cambios en gestion_sindicato"
  call git commit -q -m "%%MSG%%"
)
if errorlevel 1 goto :error

git pull --rebase --autostash
if errorlevel 1 (
  echo *** El commit quedo hecho en esta maquina pero no se pudo combinar con GitHub.
  echo     Resolver ^(git status^), git rebase --continue y volver a correr esto.
  goto :error
)
git push
if errorlevel 1 goto :error

if exist "mensaje_commit.txt" del /q mensaje_commit.txt
echo.
echo Listo: subido a GitHub.
git log -1 --format="%%h  %%s"
goto :fin

:error
echo.
echo *** Algo fallo: revisar el mensaje de arriba.

:fin
echo.
pause
endlocal
