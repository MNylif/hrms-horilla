# Horilla HRMS Installation Guide

## Quick Installation

For a completely hands-off installation, run:

```bash
sudo curl -s https://raw.githubusercontent.com/MNylif/hrms-horilla/main/install.sh | sudo bash
```

This will use default values for all settings. If you want to customize your installation but still have a hands-off process, run:

```bash
sudo bash -c "$(curl -s https://raw.githubusercontent.com/MNylif/hrms-horilla/main/install.sh)"
```

This will prompt you for all necessary information upfront and then proceed with the installation automatically without any further interaction.

## DNS Setup for Your Domain

If you want to use a custom domain (e.g., `hrms.example.com`) instead of the default `.nip.io` domain, you'll need to set up DNS records first:

1. Log in to your domain registrar or DNS provider's control panel
2. Create an A record for your subdomain pointing to your server's IP address:
   - **Type**: A
   - **Name/Host**: hrms (for the subdomain hrms.example.com)
   - **Value/Points to**: Your server's IP address (e.g., 203.0.113.10)
   - **TTL**: 3600 (or as recommended by your provider)

3. Wait for DNS propagation (can take up to 24-48 hours, but often happens within minutes)
4. Once propagated, you can use this domain during installation

**Note**: If you don't have a domain or don't want to set up DNS records, the installer will use a `.nip.io` domain by default, which will work without any DNS configuration.

## Advanced Installation Options

You can also provide specific parameters to the installation script:

```bash
sudo curl -s https://raw.githubusercontent.com/MNylif/hrms-horilla/main/install.sh | sudo bash -s -- --domain your-domain.com --email your-email@example.com
```

Available parameters:

- `--domain`: Domain name for your Horilla HRMS instance
- `--email`: Email address for SSL certificates
- `--admin-username`: Admin username
- `--admin-password`: Admin password
- `--install-dir`: Installation directory (default: /root/horilla)
- `--force-continue`: Continue installation even if apt is locked

### Backup System Parameters

The installer supports setting up an automated backup system using Rclone and BorgBackup:

- `--enable-backups`: Enable automated backups (yes/no, default: no)
- `--s3-provider`: S3 provider (aws, wasabi, b2, digitalocean, other, default: aws)
- `--s3-access-key`: S3 Access Key
- `--s3-secret-key`: S3 Secret Key
- `--s3-region`: S3 Region (default: us-east-1)
- `--s3-bucket-name`: S3 Bucket Name
- `--backup-frequency`: Backup frequency (daily, weekly, monthly, default: daily)

Example with backup system enabled:

```bash
sudo curl -s https://raw.githubusercontent.com/MNylif/hrms-horilla/main/install.sh | sudo bash -s -- \
  --domain hrms.example.com \
  --email admin@example.com \
  --enable-backups yes \
  --s3-provider aws \
  --s3-access-key YOUR_ACCESS_KEY \
  --s3-secret-key YOUR_SECRET_KEY \
  --s3-region us-east-1 \
  --s3-bucket-name your-backup-bucket \
  --backup-frequency daily
```

## Manual Installation with Docker and SSL

## Prerequisites

- Ubuntu server (20.04 LTS or newer)
- Domain name pointed to your server (e.g., hrms.yourdomain.com)
- Root or sudo access

## 1. System Preparation

Update your system and install required packages:

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Install Docker dependencies
sudo apt install -y apt-transport-https ca-certificates curl software-properties-common

# Add Docker repository
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker components
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Install Nginx and Certbot
sudo apt install -y nginx certbot python3-certbot-nginx
```

## 2. Clone Horilla Repository

```bash
# Create a directory for Horilla
mkdir ~/horilla && cd ~/horilla

# Clone the repository
git clone https://github.com/horilla-opensource/horilla.git .

# Make the entrypoint script executable
chmod +x entrypoint.sh
```

## 3. Configure Horilla Settings

Add CSRF and host settings to make Horilla work with your domain:

```bash
# Add CSRF and ALLOWED_HOSTS settings
cat << 'EOF' >> horilla/settings.py

# Add CSRF trusted origins for https
CSRF_TRUSTED_ORIGINS = ['https://hrms.yourdomain.com', 'http://hrms.yourdomain.com']
ALLOWED_HOSTS = ['hrms.yourdomain.com', 'localhost', '127.0.0.1', '*']
EOF
```

## 4. Create Docker Compose Configuration

Create a `docker-compose.yml` file:

```bash
cat << 'EOF' > docker-compose.yml
version: '3.8'
services:
  db:
    image: postgres:16-bullseye
    environment:
      POSTGRES_DB: horilla
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  server:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - 8000:8000
    environment:
      DATABASE_URL: "postgres://postgres:postgres@db:5432/horilla"
      CSRF_TRUSTED_ORIGINS: "https://hrms.yourdomain.com,http://hrms.yourdomain.com"
      ALLOWED_HOSTS: "hrms.yourdomain.com,localhost,127.0.0.1,*"
      DEBUG: "False"
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./:/app/
    command: bash -c "chmod +x /app/entrypoint.sh && /app/entrypoint.sh"

volumes:
  postgres_data:
EOF

# Replace yourdomain.com with your actual domain
sed -i "s/yourdomain.com/yourdomain.com/g" docker-compose.yml
```

## 5. Start Docker Containers

```bash
# Start the containers
docker compose up -d

# Check if containers are running
docker compose ps
```

## 6. Configure Nginx as a Reverse Proxy

Create an Nginx configuration file:

```bash
sudo nano /etc/nginx/sites-available/horilla
```

Add the following configuration (replace with your domain):

```nginx
server {
    listen 80;
    server_name hrms.yourdomain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable the configuration and restart Nginx:

```bash
sudo ln -s /etc/nginx/sites-available/horilla /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## 7. Set Up SSL with Let's Encrypt

```bash
# Obtain SSL certificate
sudo certbot --nginx -d hrms.yourdomain.com

# Follow the prompts from Certbot
# 1. Enter your email address
# 2. Agree to terms of service
# 3. Choose whether to redirect HTTP to HTTPS (recommended)
```

Certbot will automatically update your Nginx configuration for SSL.

## 8. Initialize Horilla

Once everything is running, create an admin user:

```bash
# Create a superuser
docker compose exec server python manage.py createsuperuser
```

## 9. Access Horilla

You can now access Horilla at `https://hrms.yourdomain.com`

The default credentials for the pre-created admin account are usually:
- Username: `admin`
- Password: Try `admin` or `horilla` (if these don't work, use the superuser you created)

## Troubleshooting

### CSRF Verification Failed

If you encounter CSRF verification errors, double-check your settings:

1. Verify the CSRF_TRUSTED_ORIGINS in settings.py
2. Make sure your domain is correctly set in the environment variables
3. Restart the containers:
   ```bash
   docker compose down
   docker compose up -d
   ```

### Permission Denied for entrypoint.sh

If you see "permission denied" for entrypoint.sh:

```bash
# Make the script executable
chmod +x ~/horilla/entrypoint.sh
docker compose down
docker compose up -d
```

### Database Connection Issues

If the application can't connect to the database:

```bash
# Check the database logs
docker compose logs db

# Verify the environment variables
docker compose exec server env | grep DATABASE_URL
```

### SSL Certificate Issues

If you have problems with SSL:

```bash
# Test SSL renewal
sudo certbot renew --dry-run

# Check Nginx logs
sudo tail -f /var/log/nginx/error.log
```

## 10. Backup System with Rclone and BorgBackup

### Installing Rclone and BorgBackup

```bash
# Install rclone
curl https://rclone.org/install.sh | sudo bash

# Install borgbackup
sudo apt install -y borgbackup
```

### Configuring Rclone with S3

```bash
# Start the rclone configuration wizard
rclone config

# Follow these steps in the interactive wizard:
# 1. Select "n" for new remote
# 2. Name: s3backup (or your preferred name)
# 3. Select "s3" from the storage types list
# 4. Select your S3-compatible provider (AWS, Wasabi, Backblaze, etc.)
# 5. Enter your AWS Access Key and Secret Key
# 6. Region: (enter your S3 bucket region)
# 7. Leave other options as default or customize as needed
# 8. Confirm the configuration
```

### Creating a Mount Point for S3

```bash
# Create mount directory
sudo mkdir -p /mnt/s3backup

# Test the connection
rclone ls s3backup:your-bucket-name

# Create a systemd service for automounting
sudo nano /etc/systemd/system/rclone-mount.service
```

Add the following content:

```ini
[Unit]
Description=RClone S3 Mount
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/rclone mount s3backup:your-bucket-name /mnt/s3backup \
  --allow-other \
  --buffer-size 32M \
  --dir-cache-time 72h \
  --log-level INFO \
  --vfs-cache-mode writes \
  --vfs-cache-max-size 1G \
  --vfs-read-chunk-size 64M

ExecStop=/bin/fusermount -uz /mnt/s3backup
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl enable rclone-mount.service
sudo systemctl start rclone-mount.service
sudo systemctl status rclone-mount.service
```

### Setting Up BorgBackup

```bash
# Initialize a borg repository in the S3 mount
borg init --encryption=repokey /mnt/s3backup/horilla-backups

# Create a backup script
nano ~/backup-horilla.sh
```

Add the following content:

```bash
#!/bin/bash
# Horilla Backup Script

# Variables
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
BACKUP_DIR="/tmp/horilla_backup_${TIMESTAMP}"
BORG_REPO="/mnt/s3backup/horilla-backups"
DB_CONTAINER="horilla_db_1"  # Update this if your container name is different
DB_USER="postgres"
DB_NAME="horilla"

# Create temporary backup directory
mkdir -p "${BACKUP_DIR}"

# Backup the database
echo "Creating database backup..."
docker compose -f ~/horilla/docker-compose.yml exec db pg_dump -U ${DB_USER} ${DB_NAME} > "${BACKUP_DIR}/horilla_db.sql"

# Backup application files (excluding .git and other unnecessary files)
echo "Creating application files backup..."
tar --exclude='~/horilla/.git' --exclude='~/horilla/node_modules' -czf "${BACKUP_DIR}/horilla_files.tar.gz" ~/horilla

# Create borg backup
echo "Creating borg backup..."
borg create --stats --progress \
    "${BORG_REPO}::horilla-${TIMESTAMP}" \
    "${BACKUP_DIR}"

# Clean up temporary files
echo "Cleaning up temporary files..."
rm -rf "${BACKUP_DIR}"

# Prune old backups (keep last 7 daily, 4 weekly, and 6 monthly backups)
echo "Pruning old backups..."
borg prune --stats --list "${BORG_REPO}" \
    --keep-daily=7 \
    --keep-weekly=4 \
    --keep-monthly=6

echo "Backup completed successfully."
```

Make the script executable:

```bash
chmod +x ~/backup-horilla.sh
```

### Automating Backups with Cron

```bash
# Edit the crontab
crontab -e
```

Add the following line to run the backup daily at 2 AM:

```
0 2 * * * /root/backup-horilla.sh > /var/log/horilla-backup.log 2>&1
```

### Testing the Backup System

```bash
# Run the backup script manually
~/backup-horilla.sh

# List backups in the borg repository
borg list /mnt/s3backup/horilla-backups

# Check the S3 mount
ls -la /mnt/s3backup/horilla-backups
```

## Maintenance

### Restoring from Backup

```bash
# Extract a specific backup
borg extract /mnt/s3backup/horilla-backups::horilla-YYYY-MM-DD_HH-MM-SS

# Restore database
docker compose -f ~/horilla/docker-compose.yml exec -T db psql -U postgres horilla < /path/to/extracted/horilla_db.sql

# Restore files if needed
tar -xzf /path/to/extracted/horilla_files.tar.gz -C /tmp/restore
# Copy necessary files to horilla directory
```

### Updating Horilla

```bash
cd ~/horilla
git pull
docker compose down
docker compose up -d
```

## Security Recommendations

1. Use strong passwords for database and admin users
2. Keep your system and Docker updated
3. Consider implementing a firewall with UFW
4. Set up regular database backups
5. Enable automated Let's Encrypt certificate renewal
6. Encrypt your Borg repository with a strong passphrase
7. Consider storing backup encryption keys separately from the backups
8. Regularly test your backup and restore procedures
9. Implement backup monitoring to ensure backups are completing successfully
