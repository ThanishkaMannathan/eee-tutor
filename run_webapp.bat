@echo off
echo.
echo  =============================================
echo   EEE Tutor Web App - Starting...
echo  =============================================
echo.

:: Check if .env exists
if not exist ".env" (
    echo  ERROR: .env file not found!
    echo  Please copy .env.example to .env and fill in your API keys.
    echo.
    pause
    exit /b 1
)

:: Install dependencies if needed
echo  Checking dependencies...
pip install -r requirements.txt -q
pip install flask flask-cors -q

echo  Starting web app server...
echo.
cd webapp
python app.py

pause
