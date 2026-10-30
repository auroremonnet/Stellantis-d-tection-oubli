@echo off
setlocal
cd /d "%~dp0"
title CARE dashboard

REM ---- 1. Trouver Python (Anaconda en priorite) ----
set "PY="
if exist "%USERPROFILE%\anaconda3\python.exe" set "PY=%USERPROFILE%\anaconda3\python.exe"
if not defined PY if exist "%USERPROFILE%\miniconda3\python.exe" set "PY=%USERPROFILE%\miniconda3\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\anaconda3\python.exe" set "PY=%LOCALAPPDATA%\anaconda3\python.exe"
for %%V in (314 313 312 311 310) do (
  if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
)
if not defined PY (
  python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [ERREUR] Python introuvable. Installe Python ou ajoute-le au PATH.
  pause & exit /b 1
)
echo Python utilise : %PY%

REM ---- 2. Dependances (legeres pour la demo, YOLO en plus pour le reel) ----
"%PY%" -c "import flask, cv2, numpy" 2>nul || (
  echo Installation des dependances de base...
  "%PY%" -m pip install flask opencv-python numpy || (echo [ERREUR] installation & pause & exit /b 1)
)
set "DEMO="
for %%A in (%*) do if /I "%%~A"=="--demo" set "DEMO=1"
if not defined DEMO (
  "%PY%" -c "import ultralytics" 2>nul || (
    echo Installation de YOLO ^(ultralytics + torch, plusieurs minutes^)...
    "%PY%" -m pip install ultralytics || (echo [ERREUR] installation YOLO & pause & exit /b 1)
  )
)

REM ---- 3. Lancement ----
echo.
"%PY%" app.py %*
echo.
echo Le serveur s'est arrete. Si une erreur est affichee au-dessus, copie-la.
pause
