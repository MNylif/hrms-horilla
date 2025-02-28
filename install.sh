#!/bin/bash
# Horilla HRMS One-Line Installer
# This script downloads and runs the Horilla HRMS installer

set -e

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root or with sudo"
  exit 1
fi

echo "=== Horilla HRMS One-Line Installer ==="
echo "This script will install Horilla HRMS on your system."
echo "You will be prompted for necessary information during installation."
echo "NOTE: The installation process may take 10-20 minutes depending on your system."
echo ""

# Install Python if not already installed
if ! command -v python3 &> /dev/null; then
    echo "Python 3 not found. Installing..."
    apt-get update
    apt-get install -y python3 python3-pip
fi

# Create temporary directory
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

# Download the installer script
echo "Downloading installer..."
curl -s -o install.py https://raw.githubusercontent.com/MNylif/hrms-horilla/main/install.py
chmod +x install.py

# Run the installer with all provided arguments
echo "Starting installation..."
python3 install.py "$@"

# Clean up
cd - > /dev/null
rm -rf "$TEMP_DIR"
