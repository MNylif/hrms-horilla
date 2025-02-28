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
DEFAULT_ENABLE_BACKUPS="no"
DEFAULT_S3_PROVIDER="aws"
DEFAULT_S3_ACCESS_KEY=""
DEFAULT_S3_SECRET_KEY=""
DEFAULT_S3_REGION="us-east-1"
DEFAULT_S3_BUCKET_NAME=""
DEFAULT_BACKUP_FREQUENCY="daily"

# Check if we're running in a pipe (non-interactive)
if [ ! -t 0 ]; then
    echo "Detected non-interactive environment. Using default values:"
    echo "  Domain: $DEFAULT_DOMAIN"
    echo "  Email: $DEFAULT_EMAIL"
    echo "  Admin Username: $DEFAULT_ADMIN_USER"
    echo "  Admin Password: $DEFAULT_ADMIN_PASSWORD"
    echo "  Enable Backups: $DEFAULT_ENABLE_BACKUPS"
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
    
    if ! echo "$*" | grep -q -- "--enable-backups"; then
        DEFAULT_ARGS="$DEFAULT_ARGS --enable-backups $DEFAULT_ENABLE_BACKUPS"
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
    
    # Backup system
    echo
    echo "Backup System Configuration:"
    echo "Horilla can be configured with an automated backup system using Rclone and BorgBackup."
    echo "This will back up your database and application files to an S3-compatible storage."
    echo
    read -p "Enable automated backups? (yes/no) [${DEFAULT_ENABLE_BACKUPS}]: " ENABLE_BACKUPS
    ENABLE_BACKUPS=${ENABLE_BACKUPS:-$DEFAULT_ENABLE_BACKUPS}
    
    if [ "$ENABLE_BACKUPS" = "yes" ]; then
        # S3 provider
        echo
        echo "S3 Provider options:"
        echo "1. AWS S3"
        echo "2. Wasabi"
        echo "3. Backblaze B2"
        echo "4. DigitalOcean Spaces"
        echo "5. Other S3-compatible"
        read -p "Select S3 provider (1-5) [1]: " S3_PROVIDER_OPTION
        S3_PROVIDER_OPTION=${S3_PROVIDER_OPTION:-1}
        
        case $S3_PROVIDER_OPTION in
            1) S3_PROVIDER="aws" ;;
            2) S3_PROVIDER="wasabi" ;;
            3) S3_PROVIDER="b2" ;;
            4) S3_PROVIDER="digitalocean" ;;
            5) S3_PROVIDER="other" ;;
            *) S3_PROVIDER="aws" ;;
        esac
        
        # S3 credentials
        read -p "S3 Access Key: " S3_ACCESS_KEY
        read -p "S3 Secret Key: " S3_SECRET_KEY
        read -p "S3 Region [${DEFAULT_S3_REGION}]: " S3_REGION
        S3_REGION=${S3_REGION:-$DEFAULT_S3_REGION}
        read -p "S3 Bucket Name: " S3_BUCKET_NAME
        
        # Backup frequency
        echo
        echo "Backup Frequency options:"
        echo "1. Daily (at 2 AM)"
        echo "2. Weekly (Sundays at 2 AM)"
        echo "3. Monthly (1st day of month at 2 AM)"
        read -p "Select backup frequency (1-3) [1]: " BACKUP_FREQUENCY_OPTION
        BACKUP_FREQUENCY_OPTION=${BACKUP_FREQUENCY_OPTION:-1}
        
        case $BACKUP_FREQUENCY_OPTION in
            1) BACKUP_FREQUENCY="daily" ;;
            2) BACKUP_FREQUENCY="weekly" ;;
            3) BACKUP_FREQUENCY="monthly" ;;
            *) BACKUP_FREQUENCY="daily" ;;
        esac
        
        # Add backup parameters
        BACKUP_ARGS="--enable-backups yes --s3-provider $S3_PROVIDER --s3-access-key $S3_ACCESS_KEY --s3-secret-key $S3_SECRET_KEY --s3-region $S3_REGION --s3-bucket-name $S3_BUCKET_NAME --backup-frequency $BACKUP_FREQUENCY"
    else
        BACKUP_ARGS="--enable-backups no"
    fi
    
    echo
    echo "Thank you! The installation will now proceed automatically without further prompts."
    echo "This may take 10-20 minutes depending on your system."
    echo
    
    # Set all arguments for non-interactive mode
    DEFAULT_ARGS="--domain $DOMAIN --email $EMAIL --admin-username $ADMIN_USER --admin-password $ADMIN_PASSWORD --install-dir $INSTALL_DIR $BACKUP_ARGS --non-interactive --force-continue"
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
