#!/bin/bash

echo "Setting up Yazilign Bot..."

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Python3 is not installed. Please install Python3 first."
    exit 1
fi

# Check if pip is installed
if ! command -v pip &> /dev/null; then
    echo "pip is not installed. Installing pip..."
    python3 -m ensurepip --upgrade
fi

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements_complete.txt

# Check if .env file exists, if not create from example
if [ ! -f ".env" ]; then
    echo "Creating .env file from example..."
    cp .env.example .env
    echo "Please edit .env file with your configuration before running the bot."
fi

echo "Setup complete!"
echo "Before running the bot, please:"
echo "1. Edit the .env file with your configuration"
echo "2. Place your credentials.json file in this directory"
echo "3. Run the bot with: python yazilign_bot_complete.py"