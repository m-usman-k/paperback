@echo off
echo Setting up Paperback Library...

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Python could not be found. Please install Python 3.
    exit /b 1
)

:: Create virtual environment if it doesn't exist
if not exist "venv\" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

:: Install dependencies
echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo ==========================================
echo Setup complete! To run the application:
echo.
echo 1. Activate the virtual environment:
echo    venv\Scripts\activate
echo.
echo 2. Run the application:
echo    python app.py
echo ==========================================
