#!/usr/bin/env python3
"""
Horilla HRMS Automated Installation Script

This script automates the installation of Horilla HRMS on Ubuntu using Docker Compose
with HTTPS support via Let's Encrypt.

Usage:
    sudo python3 install.py
"""

import os
import sys
import subprocess
import getpass
import re
import time
import argparse
import signal
from pathlib import Path
import traceback


class HorillaInstaller:
    def __init__(self, args):
        """Initialize the installer with configuration parameters."""
        self.domain = args.domain
        self.email = args.email
        self.admin_username = args.admin_username
        self.admin_password = args.admin_password
        self.install_dir = args.install_dir
        self.non_interactive = args.non_interactive
        self.force_continue = args.force_continue
        self.skip_upgrade = args.skip_upgrade if hasattr(args, 'skip_upgrade') else False
        
        # Backup system settings
        self.enable_backups = args.enable_backups.lower() == 'yes'
        self.s3_provider = args.s3_provider
        self.s3_access_key = args.s3_access_key
        self.s3_secret_key = args.s3_secret_key
        self.s3_region = args.s3_region
        self.s3_bucket_name = args.s3_bucket_name
        self.backup_frequency = args.backup_frequency
        
        # Determine if we're running in a TTY
        self.is_tty = sys.stdout.isatty() and not self.non_interactive
        
        # Setup signal handler for graceful exit
        signal.signal(signal.SIGINT, self._signal_handler)
        
        # Validate if running as root or with sudo
        if os.geteuid() != 0:
            print("This script must be run as root or with sudo privileges.")
            sys.exit(1)
    
    def _signal_handler(self, sig, frame):
        """Handle keyboard interrupts gracefully."""
        print("\n\nInstallation interrupted by user. Exiting...")
        sys.exit(0)

    def run_command(self, command, shell=False, cwd=None, env=None, timeout=None):
        """Run a command and return its output."""
        print(f"Running command (timeout: {timeout or 'None'}s): {command}")
        
        # Set default environment variables
        if env is None:
            env = os.environ.copy()
            
        # Set PAGER to cat to avoid interactive pagers
        env["PAGER"] = "cat"
        
        try:
            # Run the command
            result = subprocess.run(
                command,
                shell=shell,
                cwd=cwd,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            # Check the return code
            if result.returncode != 0:
                print(f"Command failed with exit code {result.returncode}")
                print(f"Error output: {result.stderr}")
                raise Exception(f"Command failed with exit code {result.returncode}")
                
            # Return the output
            return result.stdout
        except subprocess.TimeoutExpired:
            print(f"Command timed out after {timeout} seconds")
            raise Exception(f"Command timed out after {timeout} seconds")
        except Exception as e:
            print(f"Failed to run command: {str(e)}")
            raise
            
    def check_system_requirements(self):
        """Check if system meets all requirements."""
        print("\n[1/8] Checking system requirements...")
        
        # Check if running on Ubuntu
        try:
            # Using lsb_release is more reliable than checking /etc/os-release
            distribution = self.run_command(["lsb_release", "-is"], timeout=30).strip()
            if distribution.lower() != "ubuntu":
                print(f"⚠️ Warning: This installer is optimized for Ubuntu, but detected {distribution}")
                print("The installation may not work correctly on this distribution.")
                if not self.force_continue:
                    print("Use --force-continue to proceed anyway.")
                    return False
                print("Continuing anyway as --force-continue is set.")
            else:
                print(f"✓ Running on {distribution}")
        except Exception as e:
            print(f"⚠️ Warning: Failed to detect operating system: {str(e)}")
            if not self.force_continue:
                print("Use --force-continue to proceed anyway.")
                return False
            print("Continuing anyway as --force-continue is set.")
            
        # Check Docker and Docker Compose
        docker_services = ["docker.service", "docker.socket"]
        docker_running = False
        
        for service in docker_services:
            try:
                status = self.run_command(f"systemctl is-active {service}")
                if "active" in status:
                    docker_running = True
                    break
            except:
                pass
                
        if not docker_running:
            print("✓ Docker is not yet installed or running (will be installed)")
        else:
            print("✓ Docker is already running")
            
        return True
        
    def install_dependencies(self):
        """Install all required dependencies."""
        print("\n[3/8] Installing dependencies...")
        
        # Check if apt is locked
        try:
            self.run_command("lsof /var/lib/dpkg/lock-frontend", timeout=10)
            print("APT is currently locked by another process.")
            if not self.force_continue:
                print("Please wait for other package managers to finish and try again.")
                print("Use --force-continue to try to continue anyway (may cause issues).")
                return False
            print("Continuing anyway as --force-continue is set.")
        except:
            # Lock not found, which is good
            pass

        # Update package lists
        try:
            print("Updating package index...")
            self.run_command("apt-get update -y", shell=True, timeout=300)
        except Exception as e:
            print(f"Failed to update package lists: {str(e)}")
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            
        # Install system dependencies
        dependencies = [
            "apt-transport-https",
            "ca-certificates",
            "curl",
            "software-properties-common",
            "python3-pip",
            "nginx",
            "certbot",
            "python3-certbot-nginx"
        ]
        
        # Add backup tools if backups are enabled
        if self.enable_backups:
            dependencies.extend(["borgbackup", "rclone", "fuse"])
            
        try:
            print("Installing dependencies...")
            self.run_command(f"apt-get install -y {' '.join(dependencies)}", shell=True, timeout=600)
        except Exception as e:
            print(f"Failed to install dependencies: {str(e)}")
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            
        # Install Docker if not already installed
        try:
            # Check if Docker is already installed
            self.run_command("docker --version", timeout=10)
            print("Docker is already installed. Skipping Docker installation.")
        except:
            print("Installing Docker...")
            
            # Add Docker repository
            try:
                # Add Docker GPG key
                self.run_command("curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -", shell=True, timeout=30)
                
                # Get Ubuntu codename
                ubuntu_codename = self.run_command("lsb_release -cs", timeout=10).strip()
                
                # Add Docker repository
                docker_repo = f"deb [arch=amd64] https://download.docker.com/linux/ubuntu {ubuntu_codename} stable"
                self.run_command(f"add-apt-repository -y '{docker_repo}'", shell=True, timeout=30)
                
                # Update package lists again
                self.run_command("apt-get update -y", shell=True, timeout=60)
                
                # Install Docker
                self.run_command("apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose", shell=True, timeout=300)
                
                # Start Docker
                self.run_command("systemctl enable docker", shell=True, timeout=30)
                self.run_command("systemctl start docker", shell=True, timeout=30)
                
                print("Docker installed successfully.")
            except Exception as e:
                print(f"Failed to install Docker: {str(e)}")
                if not self.force_continue:
                    return False
                print("Continuing anyway as --force-continue is set.")
                
        # Install pip requirements
        try:
            print("Installing Python dependencies...")
            self.run_command("pip3 install docker-compose", shell=True, timeout=120)
        except Exception as e:
            print(f"Failed to install Python dependencies: {str(e)}")
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            
        print("✓ All dependencies installed successfully.")
        return True

    def setup_horilla(self):
        """Set up Horilla by cloning the repository and configuring it."""
        print("\n[3/8] Setting up Horilla...")
        
        # Check if the installation directory already exists
        if os.path.exists(self.install_dir) and os.listdir(self.install_dir):
            print(f"Installation directory '{self.install_dir}' already exists and is not empty.")
            
            if self.is_tty and not self.force_continue:
                print("Options:")
                print("  1. Remove existing directory and reinstall (this will delete all data)")
                print("  2. Use existing installation (may cause issues if partially installed)")
                print("  3. Abort installation")
                
                try:
                    choice = input("\nEnter your choice (1-3): ").strip()
                    
                    if choice == '1':
                        print(f"Removing existing directory: {self.install_dir}")
                        success, _ = self.run_command(f"rm -rf {self.install_dir}", shell=True)
                        if not success:
                            print(f"Failed to remove directory: {self.install_dir}")
                            return False
                    elif choice == '2':
                        print(f"Using existing installation in: {self.install_dir}")
                        # Make sure entrypoint.sh is executable
                        self.run_command(f"chmod +x {self.install_dir}/entrypoint.sh", shell=True)
                        print("✓ Made entrypoint.sh executable")
                        print("✓ Horilla setup completed")
                        return True
                    else:
                        print("Aborting installation as requested.")
                        sys.exit(0)
                except (EOFError, KeyboardInterrupt):
                    print("\nInput interrupted. Aborting installation.")
                    sys.exit(1)
            else:
                # In non-interactive or force-continue mode, remove the directory
                print(f"Removing existing directory for reinstallation: {self.install_dir}")
                success, _ = self.run_command(f"rm -rf {self.install_dir}", shell=True)
                if not success:
                    print(f"Failed to remove directory: {self.install_dir}")
                    return False
        
        # Create parent directory if it doesn't exist
        parent_dir = os.path.dirname(self.install_dir)
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
        
        # Clone the repository
        print(f"Cloning Horilla repository to {self.install_dir}...")
        success, output = self.run_command(
            f"git clone https://github.com/horilla-opensource/horilla.git {self.install_dir}",
            shell=True,
            timeout=600
        )
        
        if not success:
            print(f"Failed to clone repository: {output}")
            return False
        
        # Make entrypoint.sh executable
        self.run_command(f"chmod +x {self.install_dir}/entrypoint.sh", shell=True)
        print("✓ Made entrypoint.sh executable")
        
        print("✓ Horilla setup completed")
        return True

    def configure_settings(self):
        """Configure Horilla settings."""
        print("\n[4/8] Configuring Horilla settings...")
        
        # Get domain and email if not already provided
        if not self.domain:
            self.domain = self.get_user_input(
                "Enter your domain (e.g., hrms.example.com): ",
                validate_func=self.validate_domain
            )
        
        if not self.email:
            self.email = self.get_user_input(
                "Enter your email (for SSL certificate): ",
                validate_func=self.validate_email
            )
        
        # Create .env file
        env_path = os.path.join(self.install_dir, ".env")
        env_content = f"""DEBUG=False
SECRET_KEY=django-insecure-h-gx@tn3=o4a7z^&)sgd3pd4ov0$d2s-wj)n+_r)a=@q^7+r6n
ALLOWED_HOSTS=localhost,127.0.0.1,{self.domain}
DB_ENGINE=django.db.backends.postgresql
DB_NAME=horilla
DB_USER=horilla
DB_PASSWORD=horilla
DB_HOST=db
DB_PORT=5432
"""
        
        with open(env_path, "w") as f:
            f.write(env_content)
        
        print(f"✓ Created .env file with configuration")
        
        # Create docker-compose.yml
        compose_path = os.path.join(self.install_dir, "docker-compose.yml")
        compose_content = f"""version: '3'

services:
  db:
    image: postgres:13
    volumes:
      - postgres_data:/var/lib/postgresql/data/
    environment:
      - POSTGRES_USER=horilla
      - POSTGRES_PASSWORD=horilla
      - POSTGRES_DB=horilla
    restart: always

  web:
    build: .
    command: /bin/bash -c "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"
    volumes:
      - ./:/code
    ports:
      - "8000:8000"
    depends_on:
      - db
    restart: always
    env_file:
      - .env

volumes:
  postgres_data:
"""
        
        with open(compose_path, "w") as f:
            f.write(compose_content)
        
        print(f"✓ Created docker-compose.yml file")
        
        # Configure Nginx
        nginx_conf_path = "/etc/nginx/sites-available/horilla"
        nginx_conf_content = f"""server {{
    listen 80;
    server_name {self.domain};

    location / {{
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""
        
        with open(nginx_conf_path, "w") as f:
            f.write(nginx_conf_content)
        
        # Create symbolic link
        nginx_enabled_path = "/etc/nginx/sites-enabled/horilla"
        if os.path.exists(nginx_enabled_path):
            os.remove(nginx_enabled_path)
        
        os.symlink(nginx_conf_path, nginx_enabled_path)
        
        # Test Nginx configuration
        success, _ = self.run_command("nginx -t", shell=True)
        if not success:
            print("Warning: Nginx configuration test failed. This might cause issues later.")
        
        # Reload Nginx
        self.run_command("systemctl reload nginx", shell=True)
        
        print(f"✓ Configured Nginx for {self.domain}")
        
        # Set up SSL with Let's Encrypt if domain is not using nip.io
        if not self.domain.endswith('.nip.io'):
            print(f"Setting up SSL certificate for {self.domain}...")
            certbot_cmd = f"certbot --nginx -d {self.domain} --non-interactive --agree-tos -m {self.email}"
            success, output = self.run_command(certbot_cmd, shell=True)
            
            if success:
                print(f"✓ SSL certificate installed for {self.domain}")
            else:
                print(f"Warning: Failed to install SSL certificate. HTTPS will not be available.")
                print(f"Error: {output}")
                print(f"You can manually set up SSL later with: {certbot_cmd}")
        else:
            print(f"Skipping SSL setup for .nip.io domain. HTTPS will not be available.")
        
        print("✓ Settings configured successfully")
        return True

    def initialize_application(self):
        """Initialize the application with an admin user."""
        print("\n[5/8] Initializing application...")
        
        # Get admin username and password if not already provided
        if not self.admin_username:
            self.admin_username = self.get_user_input("Admin username: ", default="admin")
        
        if not self.admin_password:
            self.admin_password = self.get_user_input("Admin password: ", password=True, default="Admin@123")
        
        # Create a script to create a superuser
        create_admin_script = os.path.join(self.install_dir, "create_admin.py")
        script_content = f"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'horilla.settings')
django.setup()

from django.contrib.auth import get_user_model
User = get_user_model()

username = '{self.admin_username}'
password = '{self.admin_password}'
email = '{self.email}'

if User.objects.filter(username=username).exists():
    print(f"User {{username}} already exists.")
else:
    try:
        # Try to create a superuser with the standard fields
        User.objects.create_superuser(username=username, email=email, password=password)
        print(f"Superuser {{username}} created successfully.")
    except Exception as e:
        # If that fails, try with additional fields that might be required by Horilla
        try:
            User.objects.create_superuser(
                username=username, 
                email=email, 
                password=password,
                is_new_employee=False
            )
            print(f"Superuser {{username}} created successfully with custom fields.")
        except Exception as e2:
            print(f"Failed to create superuser: {{e2}}")
            # As a last resort, try using the management command
            import subprocess
            cmd = f"echo 'from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser(\\\"{username}\\\", \\\"{email}\\\", \\\"{password}\\\")' | python manage.py shell"
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"Superuser {{username}} created using management command.")
            else:
                print(f"All attempts to create superuser failed.")
                print(f"Error: {{result.stderr}}")
"""
        
        with open(create_admin_script, "w") as f:
            f.write(script_content)
        
        # Start the application with Docker Compose
        print("Starting Docker containers...")
        success, output = self.run_command("docker compose up -d", shell=True, cwd=self.install_dir)
        
        if not success:
            print(f"Failed to start Docker containers: {output}")
            return False
        
        # Wait for the database to be ready
        print("Waiting for database to be ready...")
        time.sleep(10)
        
        # Run migrations
        print("Running database migrations...")
        success, output = self.run_command("docker compose exec web python manage.py migrate", shell=True, cwd=self.install_dir)
        
        if not success:
            print(f"Failed to run migrations: {output}")
            return False
        
        # Create admin user
        print(f"Creating admin user: {self.admin_username}")
        success, output = self.run_command(
            f"docker compose exec web python create_admin.py",
            shell=True,
            cwd=self.install_dir
        )
        
        if not success:
            print(f"Failed to create admin user: {output}")
            # Try an alternative method to create the admin user
            print("Trying alternative method to create admin user...")
            
            # Create a direct Django management command to create superuser
            env_vars = f"DJANGO_SUPERUSER_USERNAME={self.admin_username} DJANGO_SUPERUSER_EMAIL={self.email} DJANGO_SUPERUSER_PASSWORD={self.admin_password}"
            success, output = self.run_command(
                f"{env_vars} docker compose exec web python manage.py createsuperuser --noinput",
                shell=True,
                cwd=self.install_dir
            )
            
            if not success:
                print(f"All attempts to create admin user failed.")
                print("You may need to create an admin user manually after installation.")
                print(f"Use: docker compose exec web python manage.py createsuperuser")
                # Continue with the installation despite this error
        
        # Collect static files
        print("Collecting static files...")
        success, output = self.run_command(
            "docker compose exec web python manage.py collectstatic --noinput",
            shell=True,
            cwd=self.install_dir
        )
        
        if not success:
            print(f"Failed to collect static files: {output}")
            print("Static files collection failed, but the application may still work.")
            # Continue with the installation despite this error
        
        print("✓ Application initialized successfully")
        return True

    def validate_inputs(self):
        """Validate all input parameters."""
        print("\n[2/8] Validating installation parameters...")
        
        # Validate domain
        if not self.domain:
            print("Domain cannot be empty.")
            return False
            
        if not self.validate_domain(self.domain):
            return False
            
        # Validate email
        if not self.email:
            print("Email address cannot be empty.")
            return False
            
        if not self.validate_email(self.email):
            return False
            
        # Validate admin username
        if not self.admin_username:
            print("Admin username cannot be empty.")
            return False
            
        # Validate admin password
        if not self.admin_password:
            print("Admin password cannot be empty.")
            return False
            
        # Validate installation directory
        if not self.install_dir:
            print("Installation directory cannot be empty.")
            return False
            
        # Validate backup settings if enabled
        if self.enable_backups:
            if not self.validate_backup_settings():
                return False
                
        print("✓ All parameters validated successfully")
        return True
        
    def validate_backup_settings(self):
        """Validate backup system settings."""
        if self.enable_backups:
            if not self.s3_access_key:
                print("S3 Access Key is required for backups.")
                return False
                
            if not self.s3_secret_key:
                print("S3 Secret Key is required for backups.")
                return False
                
            if not self.s3_bucket_name:
                print("S3 Bucket Name is required for backups.")
                return False
            
            # Validate region based on provider
            if self.s3_provider == "aws":
                # List of valid AWS regions
                valid_aws_regions = [
                    "us-east-1", "us-east-2", "us-west-1", "us-west-2", 
                    "af-south-1", "ap-east-1", "ap-south-1", "ap-northeast-1", 
                    "ap-northeast-2", "ap-northeast-3", "ap-southeast-1", 
                    "ap-southeast-2", "ca-central-1", "eu-central-1", 
                    "eu-west-1", "eu-west-2", "eu-west-3", "eu-south-1", 
                    "eu-north-1", "me-south-1", "sa-east-1"
                ]
                
                # Case-insensitive comparison
                if self.s3_region.lower() not in [r.lower() for r in valid_aws_regions]:
                    # Not a critical error, just print a warning
                    print(f"Warning: '{self.s3_region}' may not be a valid AWS region. "
                          f"Common regions include: us-east-1, us-west-2, eu-west-1, etc.")
                    print("Continuing with the provided region...")
                
            if self.backup_frequency not in ['daily', 'weekly', 'monthly']:
                print("Invalid backup frequency. Must be 'daily', 'weekly', or 'monthly'.")
                return False
                
        return True

    def setup_backup_system(self):
        """Set up the backup system with Rclone and BorgBackup."""
        print("\n📦 Setting up backup system...")
        
        try:
            # Install Rclone
            print("Installing Rclone...")
            self.run_command("curl https://rclone.org/install.sh | bash")
            
            # Install BorgBackup
            print("Installing BorgBackup...")
            self.run_command("apt-get install -y borgbackup")
            
            # Configure Rclone
            print("Configuring Rclone...")
            self.configure_rclone()
            
            # Create mount point
            print("Creating S3 mount point...")
            self.run_command("mkdir -p /mnt/s3backup")
            
            # Create Rclone mount service
            print("Creating Rclone mount service...")
            self.create_rclone_service()
            
            # Create backup script
            print("Creating backup script...")
            self.create_backup_script()
            
            # Set up cron job
            print("Setting up backup schedule...")
            self.setup_backup_schedule()
            
            print("✓ Backup system setup completed successfully!")
            return True
        except Exception as e:
            print(f"❌ Backup system setup failed: {str(e)}")
            traceback.print_exc()
            return False
            
    def configure_rclone(self):
        """Configure Rclone with S3 credentials."""
        # Create rclone config file
        config_dir = "/root/.config/rclone"
        self.run_command(f"mkdir -p {config_dir}")
        
        # Determine provider type and endpoint
        provider_type = "s3"
        provider_endpoint = ""
        
        if self.s3_provider == "wasabi":
            provider_endpoint = f"s3.{self.s3_region}.wasabisys.com"
        elif self.s3_provider == "b2":
            provider_type = "b2"
        elif self.s3_provider == "digitalocean":
            provider_endpoint = f"{self.s3_region}.digitaloceanspaces.com"
        elif self.s3_provider == "other":
            # For other providers, we'd need more info, but we'll use a generic S3 config
            pass
        
        # Create config content
        config_content = "[s3backup]\n"
        
        if provider_type == "s3":
            config_content += "type = s3\n"
            config_content += f"access_key_id = {self.s3_access_key}\n"
            config_content += f"secret_access_key = {self.s3_secret_key}\n"
            config_content += f"region = {self.s3_region}\n"
            
            if provider_endpoint:
                config_content += f"endpoint = {provider_endpoint}\n"
        elif provider_type == "b2":
            config_content += "type = b2\n"
            config_content += f"account = {self.s3_access_key}\n"
            config_content += f"key = {self.s3_secret_key}\n"
        
        # Write config file
        with open(f"{config_dir}/rclone.conf", "w") as f:
            f.write(config_content)
            
        # Ensure bucket exists by creating it if it doesn't
        try:
            self.run_command(f"rclone mkdir s3backup:{self.s3_bucket_name}/horilla-backups")
            return True
        except Exception as e:
            print(f"Error configuring rclone: {str(e)}")
            print("Please check your S3 credentials and region.")
            return False


    def create_rclone_service(self):
        """Create systemd service for Rclone mount."""
        service_content = """[Unit]
Description=RClone S3 Mount
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/rclone mount s3backup:{bucket_name} /mnt/s3backup \\
  --allow-other \\
  --buffer-size 32M \\
  --dir-cache-time 72h \\
  --log-level INFO \\
  --vfs-cache-mode writes \\
  --vfs-cache-max-size 1G \\
  --vfs-read-chunk-size 64M

ExecStop=/bin/fusermount -uz /mnt/s3backup
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
""".format(bucket_name=self.s3_bucket_name)

        # Write service file
        with open("/etc/systemd/system/rclone-mount.service", "w") as f:
            f.write(service_content)
            
        # Enable and start service
        self.run_command("systemctl daemon-reload")
        self.run_command("systemctl enable rclone-mount.service")
        self.run_command("systemctl start rclone-mount.service")
        
    def create_backup_script(self):
        """Create the backup script."""
        script_content = """#!/bin/bash
# Horilla Backup Script

# Variables
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
BACKUP_DIR="/tmp/horilla_backup_${TIMESTAMP}"
BORG_REPO="/mnt/s3backup/{bucket_name}/horilla-backups"
DB_CONTAINER="horilla_db_1"  # Update this if your container name is different
DB_USER="postgres"
DB_NAME="horilla"

# Create temporary backup directory
mkdir -p "${BACKUP_DIR}"

# Backup the database
echo "Creating database backup..."
docker compose -f {install_dir}/docker-compose.yml exec db pg_dump -U ${DB_USER} ${DB_NAME} > "${BACKUP_DIR}/horilla_db.sql"

# Backup application files (excluding .git and other unnecessary files)
echo "Creating application files backup..."
tar --exclude='{install_dir}/.git' --exclude='{install_dir}/node_modules' -czf "${BACKUP_DIR}/horilla_files.tar.gz" {install_dir}

# Create borg backup
echo "Creating borg backup..."
borg create --stats --progress \\
    "${BORG_REPO}::horilla-${TIMESTAMP}" \\
    "${BACKUP_DIR}"

# Clean up temporary files
echo "Cleaning up temporary files..."
rm -rf "${BACKUP_DIR}"

# Prune old backups (keep last 7 daily, 4 weekly, and 6 monthly backups)
echo "Pruning old backups..."
borg prune --stats --list "${BORG_REPO}" \\
    --keep-daily=7 \\
    --keep-weekly=4 \\
    --keep-monthly=6

echo "Backup completed successfully."
""".format(bucket_name=self.s3_bucket_name, install_dir=self.install_dir)

        # Write script file
        with open("/root/backup-horilla.sh", "w") as f:
            f.write(script_content)
            
        # Make script executable
        self.run_command("chmod +x /root/backup-horilla.sh")
        
    def setup_backup_schedule(self):
        """Set up cron job for backups."""
        cron_schedule = ""
        
        if self.backup_frequency == "daily":
            cron_schedule = "0 2 * * *"
        elif self.backup_frequency == "weekly":
            cron_schedule = "0 2 * * 0"  # Sundays at 2 AM
        elif self.backup_frequency == "monthly":
            cron_schedule = "0 2 1 * *"  # 1st day of month at 2 AM
            
        # Add cron job
        cron_job = f"{cron_schedule} /root/backup-horilla.sh > /var/log/horilla-backup.log 2>&1\n"
        
        # Write to crontab
        with open("/tmp/horilla-crontab", "w") as f:
            f.write(cron_job)
            
        self.run_command("crontab -u root /tmp/horilla-crontab")
        self.run_command("rm /tmp/horilla-crontab")

    def install(self):
        """Main installation method."""
        try:
            print("Starting Horilla HRMS installation...")
            
            # Check system requirements
            if not self.check_system_requirements():
                return False
            
            # Validate inputs
            if not self.validate_inputs():
                return False
                
            # Install dependencies
            if not self.install_dependencies():
                return False
                
            # Clone repository
            if not self.setup_horilla():
                return False
                
            # Configure settings
            if not self.configure_settings():
                return False
                
            # Set up Docker
            if not self.initialize_application():
                return False
                
            # Set up backup system if enabled
            if self.enable_backups:
                if not self.setup_backup_system():
                    print("Warning: Backup system setup failed, but installation will continue.")
                    # Don't return False here, as we want the installation to continue even if backup setup fails
            
            print("\n✅ Horilla HRMS installation completed successfully!")
            print(f"You can access your Horilla HRMS instance at: https://{self.domain}")
            print(f"Admin username: {self.admin_username}")
            print(f"Admin password: {self.admin_password}")
            
            return True
        except Exception as e:
            print(f"❌ Installation failed: {str(e)}")
            traceback.print_exc()
            return False

    def run(self):
        """Run the complete installation process."""
        print("=" * 60)
        print("Horilla HRMS Automated Installation")
        print("=" * 60)
        
        # Now using install() method which handles the entire process
        success = self.install()
        
        if success:
            print("\n" + "=" * 60)
            print("✅ Installation completed successfully!")
            print(f"You can now access Horilla HRMS at: https://{self.domain}")
            print(f"Admin username: {self.admin_username}")
            print(f"Admin password: {self.admin_password}")
            print("=" * 60)
        
        return success

    def validate_backup_settings(self):
        """Validate backup system settings."""
        if self.enable_backups:
            if not self.s3_access_key:
                print("S3 Access Key is required for backups.")
                return False
                
            if not self.s3_secret_key:
                print("S3 Secret Key is required for backups.")
                return False
                
            if not self.s3_bucket_name:
                print("S3 Bucket Name is required for backups.")
                return False
            
            # Validate region based on provider
            if self.s3_provider == "aws":
                # List of valid AWS regions
                valid_aws_regions = [
                    "us-east-1", "us-east-2", "us-west-1", "us-west-2", 
                    "af-south-1", "ap-east-1", "ap-south-1", "ap-northeast-1", 
                    "ap-northeast-2", "ap-northeast-3", "ap-southeast-1", 
                    "ap-southeast-2", "ca-central-1", "eu-central-1", 
                    "eu-west-1", "eu-west-2", "eu-west-3", "eu-south-1", 
                    "eu-north-1", "me-south-1", "sa-east-1"
                ]
                
                # Case-insensitive comparison
                if self.s3_region.lower() not in [r.lower() for r in valid_aws_regions]:
                    # Not a critical error, just print a warning
                    print(f"Warning: '{self.s3_region}' may not be a valid AWS region. "
                          f"Common regions include: us-east-1, us-west-2, eu-west-1, etc.")
                    print("Continuing with the provided region...")
                
            if self.backup_frequency not in ['daily', 'weekly', 'monthly']:
                print("Invalid backup frequency. Must be 'daily', 'weekly', or 'monthly'.")
                return False
                
        return True

    def configure_rclone(self):
        """Configure Rclone with S3 credentials."""
        # Create rclone config file
        config_dir = "/root/.config/rclone"
        self.run_command(f"mkdir -p {config_dir}")
        
        # Determine provider type and endpoint
        provider_type = "s3"
        provider_endpoint = ""
        
        if self.s3_provider == "wasabi":
            provider_endpoint = f"s3.{self.s3_region}.wasabisys.com"
        elif self.s3_provider == "b2":
            provider_type = "b2"
        elif self.s3_provider == "digitalocean":
            provider_endpoint = f"{self.s3_region}.digitaloceanspaces.com"
        elif self.s3_provider == "other":
            # For other providers, we'd need more info, but we'll use a generic S3 config
            pass
        
        # Create config content
        config_content = "[s3backup]\n"
        
        if provider_type == "s3":
            config_content += "type = s3\n"
            config_content += f"access_key_id = {self.s3_access_key}\n"
            config_content += f"secret_access_key = {self.s3_secret_key}\n"
            config_content += f"region = {self.s3_region}\n"
            
            if provider_endpoint:
                config_content += f"endpoint = {provider_endpoint}\n"
        elif provider_type == "b2":
            config_content += "type = b2\n"
            config_content += f"account = {self.s3_access_key}\n"
            config_content += f"key = {self.s3_secret_key}\n"
        
        # Write config file
        with open(f"{config_dir}/rclone.conf", "w") as f:
            f.write(config_content)
            
        # Ensure bucket exists by creating it if it doesn't
        try:
            self.run_command(f"rclone mkdir s3backup:{self.s3_bucket_name}/horilla-backups")
            return True
        except Exception as e:
            print(f"Error configuring rclone: {str(e)}")
            print("Please check your S3 credentials and region.")
            return False


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Horilla HRMS Installer')
    parser.add_argument('--domain', help='Domain name for Horilla HRMS')
    parser.add_argument('--email', help='Email address for SSL certificates')
    parser.add_argument('--admin-username', help='Admin username')
    parser.add_argument('--admin-password', help='Admin password')
    parser.add_argument('--install-dir', help='Installation directory', default='/root/horilla')
    parser.add_argument('--non-interactive', action='store_true', help='Run in non-interactive mode')
    parser.add_argument('--force-continue', action='store_true', help='Continue installation even if apt is locked')
    parser.add_argument('--skip-upgrade', action='store_true', help='Skip system upgrade')
    
    # Backup system arguments
    parser.add_argument('--enable-backups', help='Enable automated backups (yes/no)', default='no')
    parser.add_argument('--s3-provider', help='S3 provider (aws, wasabi, b2, digitalocean, other)', default='aws')
    parser.add_argument('--s3-access-key', help='S3 Access Key')
    parser.add_argument('--s3-secret-key', help='S3 Secret Key')
    parser.add_argument('--s3-region', help='S3 Region', default='us-east-1')
    parser.add_argument('--s3-bucket-name', help='S3 Bucket Name')
    parser.add_argument('--backup-frequency', help='Backup frequency (daily, weekly, monthly)', default='daily')
    
    return parser.parse_args()


def main():
    """Main entry point for the installer."""
    args = parse_args()
    
    # Check if running in non-interactive mode
    if not sys.stdin.isatty():
        print("Detected non-interactive environment.")
        args.non_interactive = True
        args.force_continue = True
    
    # Create and run the installer
    installer = HorillaInstaller(args)
    
    success = installer.run()
    
    # Return status code
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
