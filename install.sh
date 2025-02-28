#!/bin/bash

set -e

echo "=== Horilla HRMS One-Line Installer ==="
echo "This script will install Horilla HRMS on your system."
echo

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root or with sudo"
  exit 1
fi

# Install Python if not already installed
if ! command -v python3 &> /dev/null; then
    echo "Python 3 not found. Installing..."
    apt-get update
    apt-get install -y python3 python3-pip
fi

# Get server IP for default domain
SERVER_IP=$(hostname -I | awk '{print $1}')
DEFAULT_DOMAIN="horilla.${SERVER_IP}.nip.io"
DEFAULT_EMAIL="admin@example.com"
DEFAULT_ADMIN_USER="admin"
DEFAULT_ADMIN_PASSWORD="Admin@123"

# Check if we're running in a pipe (non-interactive)
if [ ! -t 0 ]; then
    echo "Detected non-interactive environment. Using default values:"
    echo "  Domain: $DEFAULT_DOMAIN"
    echo "  Email: $DEFAULT_EMAIL"
    echo "  Admin Username: $DEFAULT_ADMIN_USER"
    echo "  Admin Password: $DEFAULT_ADMIN_PASSWORD"
    echo
    echo "You can change these settings later by editing the configuration files."
    echo "For security, please change the admin password after installation."
    echo
    
    # Check if domain, email, and admin-password are already provided in arguments
    if ! echo "$*" | grep -q -- "--domain"; then
        DEFAULT_ARGS="$DEFAULT_ARGS --domain $DEFAULT_DOMAIN"
    fi
    
    if ! echo "$*" | grep -q -- "--email"; then
        DEFAULT_ARGS="$DEFAULT_ARGS --email $DEFAULT_EMAIL"
    fi
    
    if ! echo "$*" | grep -q -- "--admin-username"; then
        DEFAULT_ARGS="$DEFAULT_ARGS --admin-username $DEFAULT_ADMIN_USER"
    fi
    
    if ! echo "$*" | grep -q -- "--admin-password"; then
        DEFAULT_ARGS="$DEFAULT_ARGS --admin-password $DEFAULT_ADMIN_PASSWORD"
    fi
    
    # Always add non-interactive and force-continue flags
    if ! echo "$*" | grep -q -- "--non-interactive"; then
        DEFAULT_ARGS="$DEFAULT_ARGS --non-interactive"
    fi
    
    if ! echo "$*" | grep -q -- "--force-continue"; then
        DEFAULT_ARGS="$DEFAULT_ARGS --force-continue"
    fi
else
    # Interactive mode - collect all variables upfront
    echo "Please provide the following information for your Horilla HRMS installation:"
    echo "Press Enter to accept the default values shown in brackets."
    echo
    
    # Domain
    echo "Domain name for your Horilla HRMS instance:"
    echo "  - You can use a custom domain like 'hrms.example.com' (requires DNS setup)"
    echo "  - Or use the default .nip.io domain which works without DNS configuration"
    echo
    echo "If using a custom domain, make sure you have created an A record pointing to this server's IP ($SERVER_IP):"
    echo "  - Type: A"
    echo "  - Name/Host: hrms (for hrms.example.com)"
    echo "  - Value/Points to: $SERVER_IP"
    echo
    read -p "Domain name [${DEFAULT_DOMAIN}]: " DOMAIN
    DOMAIN=${DOMAIN:-$DEFAULT_DOMAIN}
    
    # Email
    read -p "Email address for SSL certificates [${DEFAULT_EMAIL}]: " EMAIL
    EMAIL=${EMAIL:-$DEFAULT_EMAIL}
    
    # Admin username
    read -p "Admin username [${DEFAULT_ADMIN_USER}]: " ADMIN_USER
    ADMIN_USER=${ADMIN_USER:-$DEFAULT_ADMIN_USER}
    
    # Admin password
    read -p "Admin password [${DEFAULT_ADMIN_PASSWORD}]: " ADMIN_PASSWORD
    ADMIN_PASSWORD=${ADMIN_PASSWORD:-$DEFAULT_ADMIN_PASSWORD}
    
    # Installation directory
    read -p "Installation directory [/root/horilla]: " INSTALL_DIR
    INSTALL_DIR=${INSTALL_DIR:-/root/horilla}
    
    echo
    echo "Thank you! The installation will now proceed automatically without further prompts."
    echo "This may take 10-20 minutes depending on your system."
    echo
    
    # Set all arguments for non-interactive mode
    DEFAULT_ARGS="--domain $DOMAIN --email $EMAIL --admin-username $ADMIN_USER --admin-password $ADMIN_PASSWORD --install-dir $INSTALL_DIR --non-interactive --force-continue"
fi

# Create temporary directory
TEMP_DIR=$(mktemp -d)
cd "$TEMP_DIR"

echo "Downloading installer..."
# Download the installer
curl -s https://raw.githubusercontent.com/MNylif/hrms-horilla/main/install.py -o install.py

# Run the installer with all provided arguments
echo "Starting installation..."
python3 install.py $DEFAULT_ARGS "$@"

# Clean up
cd - > /dev/null
rm -rf "$TEMP_DIR"
