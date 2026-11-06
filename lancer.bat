@echo off
setlocal
cd /d "%~dp0"
title CARE dashboard

REM ---- Nettoyer un ancien environnement casse ----
if exist ".venv" rmdir /s /q ".venv"

REM ---- 1. Trouver Python (Anaconda en priorite) ----
set "PY="
if exist "%USERPROFILE%\anaconda3\python.exe" set "PY=%USERPROFILE%\anaconda3\python.exe"
if not defined PY if exist "%USERPROFILE%\miniconda3\python.exe" set "PY=%USERPROFILE%\miniconda3\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\anaconda3\python.exe" set "PY=%LOCALAPPDATA%\anaconda3\python.exe"
if not defined PY (
  where python >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo [ERREUR] Python introuvable. Lance depuis l'Anaconda Prompt : python app.py --demo
  pause & exit /b 1
)
echo Python utilise : %PY%

REM ---- 2. Dependances (legeres pour la demo, YOLO en plus pour le reel) ----
"%PY%" -c "import flask, cv2, numpy" 2>nul || (
  echo Installation des dependances de base...
  "%PY%" -m pip install flask opencv-python numpy || (echo [ERREUR] installation & pause & exit /b 1)
)
echo %* | find /i "--demo" >nul
if errorlevel 1 (
  "%PY%" -c "import ultralytics" 2>nul || (
    echo Installation de YOLO ^(ultralytics + torch, plusieurs minutes^)...
    "%PY%" -m pip install ultralytics || (echo [ERREUR] installation YOLO & pause & exit /b 1)
  )
  REM pygrabber : lire le NOM des cameras, pour ecarter la webcam du PC
  "%PY%" -c "import pygrabber" 2>nul || "%PY%" -m pip install pygrabber
)

REM ---- 3. Lancement ----
echo.
"%PY%" app.py %*
echo.
echo Le serveur s'est arrete. Si une erreur est affichee au-dessus, copie-la.
pause
