#!/bin/bash
echo "Setting up Paperback Library..."

# Check if Python is installed
if ! command -v python3 &> /dev/null
then
    # Try just 'python' instead
    if ! command -v python &> /dev/null
    then
        echo "Python could not be found. Please install Python 3."
        exit 1
    else
        PYTHON_CMD="python"
    fi
else
    PYTHON_CMD="python3"
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    $PYTHON_CMD -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
if [ -f "venv/Scripts/activate" ]; then
    # Windows Git Bash
    source venv/Scripts/activate
else
    # Linux/Mac
    source venv/bin/activate
fi

# Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "=========================================="
echo "Setup complete! To run the application:"
echo ""
echo "1. Activate the virtual environment:"
if [ -f "venv/Scripts/activate" ]; then
    echo "   source venv/Scripts/activate"
else
    echo "   source venv/bin/activate"
fi
echo ""
echo "2. Run the application:"
echo "   python app.py"
echo "=========================================="
