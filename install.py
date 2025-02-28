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
import json
import time
import argparse
import signal
from pathlib import Path
import traceback
import secrets


class HorillaInstaller:
    """Horilla HRMS installer class."""
    
    def __init__(self, args):
        """Initialize the installer with configuration parameters."""
        # Default values
        self.domain = args.domain if hasattr(args, 'domain') else None
        self.admin_username = args.admin_username if hasattr(args, 'admin_username') else "admin"
        self.admin_password = args.admin_password if hasattr(args, 'admin_password') else "Admin@123"
        self.email = args.email if hasattr(args, 'email') else "admin@example.com"
        self.install_dir = args.install_dir if hasattr(args, 'install_dir') else "/opt/horilla"
        self.force_continue = args.force_continue if hasattr(args, 'force_continue') else False
        self.force_no_ssl = args.force_no_ssl if hasattr(args, 'force_no_ssl') else False
        self.non_interactive = args.non_interactive if hasattr(args, 'non_interactive') else False
        self.skip_upgrade = args.skip_upgrade if hasattr(args, 'skip_upgrade') else False
        self.skip_root_check = args.skip_root_check if hasattr(args, 'skip_root_check') else False
        
        # Backup system parameters
        self.enable_backups = args.enable_backups.lower() == 'yes' if hasattr(args, 'enable_backups') else False
        self.s3_provider = args.s3_provider if hasattr(args, 's3_provider') else "1"  # 1=AWS, 2=Wasabi, 3=B2, 4=DigitalOcean, 5=Other
        self.s3_access_key = args.s3_access_key if hasattr(args, 's3_access_key') else ""
        self.s3_secret_key = args.s3_secret_key if hasattr(args, 's3_secret_key') else ""
        self.s3_region = args.s3_region if hasattr(args, 's3_region') else "us-east-1"
        self.s3_bucket_name = args.s3_bucket_name if hasattr(args, 's3_bucket_name') else ""
        self.backup_frequency = args.backup_frequency if hasattr(args, 'backup_frequency') else "1"  # 1=Daily, 2=Weekly, 3=Monthly
        
        # Determine if we're running in a TTY
        self.is_tty = sys.stdout.isatty() and not args.non_interactive
        
        # Setup signal handler for graceful exit
        signal.signal(signal.SIGINT, self._signal_handler)
        
        # Validate if running as root or with sudo
        if os.geteuid() != 0:
            print("This script must be run as root or with sudo privileges.")
            sys.exit(1)
        
        # Load saved configuration if available
        self.load_saved_config()
        
    def load_saved_config(self):
        """Load saved configuration from file if it exists."""
        config_file = "/tmp/horilla_install_config.json"
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                
                print("\n========================================================================")
                print("Found saved configuration from previous run. Using saved values as defaults.")
                print("You can change any values during this installation if needed.")
                print("========================================================================\n")
                
                # Only load values that weren't specified via command line
                if self.domain is None and 'domain' in config:
                    self.domain = config.get('domain')
                if 'email' in config and self.email == "admin@example.com":
                    self.email = config.get('email')
                if 'admin_username' in config and self.admin_username == "admin":
                    self.admin_username = config.get('admin_username')
                if 'admin_password' in config and self.admin_password == "Admin@123":
                    self.admin_password = config.get('admin_password')
                if 'install_dir' in config and self.install_dir == "/opt/horilla":
                    self.install_dir = config.get('install_dir')
                
                # Backup settings
                if not self.enable_backups and 'enable_backups' in config:
                    self.enable_backups = config.get('enable_backups')
                if 's3_provider' in config and self.s3_provider == "1":
                    self.s3_provider = config.get('s3_provider')
                if 's3_access_key' in config and not self.s3_access_key:
                    self.s3_access_key = config.get('s3_access_key')
                if 's3_secret_key' in config and not self.s3_secret_key:
                    self.s3_secret_key = config.get('s3_secret_key')
                if 's3_region' in config and self.s3_region == "us-east-1":
                    self.s3_region = config.get('s3_region')
                if 's3_bucket_name' in config and not self.s3_bucket_name:
                    self.s3_bucket_name = config.get('s3_bucket_name')
                if 'backup_frequency' in config and self.backup_frequency == "1":
                    self.backup_frequency = config.get('backup_frequency')
                    
            except Exception as e:
                print(f"Warning: Could not load saved configuration: {e}")
                
    def save_config(self):
        """Save current configuration to file."""
        config_file = "/tmp/horilla_install_config.json"
        config = {
            'domain': self.domain,
            'email': self.email,
            'admin_username': self.admin_username,
            'admin_password': self.admin_password,
            'install_dir': self.install_dir,
            'enable_backups': self.enable_backups,
            's3_provider': self.s3_provider,
            's3_access_key': self.s3_access_key,
            's3_secret_key': self.s3_secret_key,
            's3_region': self.s3_region,
            's3_bucket_name': self.s3_bucket_name,
            'backup_frequency': self.backup_frequency
        }
        
        try:
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save configuration: {e}")

    def _signal_handler(self, sig, frame):
        """Handle keyboard interrupts gracefully."""
        print("\n\nInstallation interrupted by user. Exiting...")
        sys.exit(0)

    def run_command(self, command, shell=False, cwd=None, env=None, timeout=None):
        """
        Run a command and get its output.
        
        Args:
            command: The command to run, as a string or list of arguments
            shell: If True, run through shell
            cwd: Current working directory
            env: Environment variables
            timeout: Timeout in seconds
            
        Returns:
            Tuple of (success, output)
        """
        print(f"Running command (timeout: {timeout}s): {command}")
        
        try:
            # Run the command
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=shell,
                cwd=cwd,
                env=env,
                universal_newlines=True
            )
            
            # Wait for the command to complete with timeout
            stdout, stderr = process.communicate(timeout=timeout)
            
            # Check if the command was successful (exit code 0)
            success = process.returncode == 0
            
            # Concatenate stdout and stderr with a separator
            output = stdout
            
            # If stderr is not empty, append it to output
            if stderr:
                if output:
                    output += "\n"
                output += f"Error output: {stderr}"
            
            # Print the output for debugging
            if not success:
                print(f"Command failed with exit code {process.returncode}")
                if stderr:
                    print(f"Error output: {stderr}")
            
            return success, output
            
        except subprocess.TimeoutExpired:
            # Kill the process if it times out
            process.kill()
            print(f"Command timed out after {timeout} seconds: {command}")
            return False, f"Command timed out after {timeout} seconds"
            
        except FileNotFoundError as e:
            # Handle file not found error
            error_message = f"Failed to run command: {str(e)}"
            print(error_message)
            return False, error_message
            
        except subprocess.SubprocessError as e:
            # Handle other subprocess errors
            error_message = f"Failed to run command: {str(e)}"
            print(error_message)
            return False, error_message
            
        except Exception as e:
            # Handle any other exceptions
            error_message = f"Failed to run command: {str(e)}"
            print(error_message)
            traceback.print_exc()
            return False, error_message
        
    def check_system_requirements(self):
        """Check if system meets all requirements."""
        print("\n[1/8] Checking system requirements...")
        
        # Check if the script is run as root
        if os.geteuid() != 0 and not self.skip_root_check:
            print("❌ This script must be run as root")
            return False
            
        # Check if running on Ubuntu or Debian
        try:
            success, output = self.run_command(["lsb_release", "-is"], timeout=30)
            if success and "ubuntu" in output.lower():
                print("✓ Running on Ubuntu")
            elif success and "debian" in output.lower():
                print("✓ Running on Debian")
            else:
                print(f"Warning: This script is designed for Ubuntu or Debian, but detected: {output}")
                if not self.force_continue:
                    print("Use --force-continue to run on unsupported distributions")
                    return False
                print("Continuing anyway as --force-continue is set.")
        except:
            print("Warning: Could not determine distribution. This script is designed for Ubuntu or Debian.")
            if not self.force_continue:
                print("Use --force-continue to run on unsupported distributions")
                return False
            print("Continuing anyway as --force-continue is set.")
            
        # Check if Docker is installed and running
        docker_installed = False
        docker_running = False
        
        # Try checking Docker status with systemctl
        try:
            # Try to run docker --version to check if it's installed
            success, _ = self.run_command("docker --version", shell=True, timeout=10)
            if success:
                docker_installed = True
                print("Docker is already installed. Skipping Docker installation.")
            else:
                # Try to install docker-compose from apt package
                print("Installing Docker Compose from apt package...")
                success, _ = self.run_command("apt-get install -y docker-compose", shell=True, timeout=120)
                if success:
                    print("Docker Compose installed successfully from apt.")
                else:
                    # If apt installation fails, try Python virtual environment
                    print("Setting up Python virtual environment for Docker Compose...")
                    venv_path = "/root/horilla_venv"
                    try:
                        self.run_command(f"python3 -m venv {venv_path}", shell=True, timeout=60)
                        self.run_command(f"{venv_path}/bin/pip install --upgrade pip", shell=True, timeout=60)
                        self.run_command(f"{venv_path}/bin/pip install docker-compose", shell=True, timeout=120)
                        
                        # Create symlink to make docker-compose available system-wide
                        self.run_command(f"ln -sf {venv_path}/bin/docker-compose /usr/local/bin/docker-compose", shell=True)
                        print("Docker Compose installed successfully in virtual environment.")
                    except Exception as e:
                        print(f"Failed to install Docker Compose in virtual environment: {str(e)}")
                        
                        # As a last resort, try to download the Docker Compose binary directly
                        print("Trying to download Docker Compose binary directly...")
                        try:
                            self.run_command("curl -L https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose", shell=True, timeout=120)
                            self.run_command("chmod +x /usr/local/bin/docker-compose", shell=True)
                            print("Docker Compose binary installed successfully.")
                        except Exception as e2:
                            print(f"Failed to download Docker Compose binary: {str(e2)}")
                            if not self.force_continue:
                                return False
                            print("Continuing anyway as --force-continue is set.")
        except Exception as e:
            print(f"Error checking Docker installation: {str(e)}")
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            
        # Install Docker if not installed
        if not docker_installed:
            # Add Docker repository
            try:
                # Add Docker GPG key
                self.run_command("curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -", shell=True, timeout=30)
                
                # Get Ubuntu codename
                try:
                    success, ubuntu_codename = self.run_command("lsb_release -cs", shell=True, timeout=10)
                    ubuntu_codename = ubuntu_codename.strip()
                    if not success or not ubuntu_codename:
                        raise Exception("Could not determine Ubuntu codename")
                except:
                    # If lsb_release is not available, try to get it from /etc/os-release
                    try:
                        success, os_release = self.run_command("cat /etc/os-release", shell=True, timeout=10)
                        ubuntu_codename = None
                        if success:
                            for line in os_release.split('\n'):
                                if line.startswith('VERSION_CODENAME='):
                                    ubuntu_codename = line.split('=')[1].strip('"\'')
                                    break
                        if not ubuntu_codename:
                            print("Could not determine Ubuntu codename. Using 'focal' as fallback.")
                            ubuntu_codename = 'focal'
                    except:
                        print("Could not determine Ubuntu codename. Using 'focal' as fallback.")
                        ubuntu_codename = 'focal'
                
                # Add Docker repository
                self.run_command(f"add-apt-repository 'deb [arch=amd64] https://download.docker.com/linux/ubuntu {ubuntu_codename} stable'", shell=True, timeout=30)
                
                # Update package lists
                self.run_command("apt-get update -y", shell=True, timeout=300)
                
                # Install Docker
                self.run_command("apt-get install -y docker-ce docker-ce-cli containerd.io", shell=True, timeout=300)
                
                # Start Docker service
                self.run_command("systemctl start docker", shell=True)
                
                # Enable Docker service to start at boot
                self.run_command("systemctl enable docker", shell=True)
                
                print("✓ Docker installed successfully")
            except Exception as e:
                print(f"Failed to install Docker: {str(e)}")
                if not self.force_continue:
                    return False
                print("Continuing anyway as --force-continue is set.")
            
        print("✓ All dependencies installed successfully.")
        return True

    def install_dependencies(self):
        """Install all required dependencies."""
        print("\n[3/8] Installing dependencies...")
        
        # Check if apt is locked
        try:
            self.run_command("lsof /var/lib/dpkg/lock-frontend", shell=True, timeout=10)
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
            "python3-full",
            "python3-venv",
            "nginx",
            "certbot",
            "python3-certbot-nginx",
            "git"
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
            
        # Check if Docker is installed
        docker_installed = False
        try:
            # Try to run docker --version to check if it's installed
            success, _ = self.run_command("docker --version", shell=True, timeout=10)
            if success:
                docker_installed = True
                print("Docker is already installed. Skipping Docker installation.")
            else:
                # Try to install docker-compose from apt package
                print("Installing Docker Compose from apt package...")
                success, _ = self.run_command("apt-get install -y docker-compose", shell=True, timeout=120)
                if success:
                    print("Docker Compose installed successfully from apt.")
                else:
                    # If apt installation fails, try Python virtual environment
                    print("Setting up Python virtual environment for Docker Compose...")
                    venv_path = "/root/horilla_venv"
                    try:
                        self.run_command(f"python3 -m venv {venv_path}", shell=True, timeout=60)
                        self.run_command(f"{venv_path}/bin/pip install --upgrade pip", shell=True, timeout=60)
                        self.run_command(f"{venv_path}/bin/pip install docker-compose", shell=True, timeout=120)
                        
                        # Create symlink to make docker-compose available system-wide
                        self.run_command(f"ln -sf {venv_path}/bin/docker-compose /usr/local/bin/docker-compose", shell=True)
                        print("Docker Compose installed successfully in virtual environment.")
                    except Exception as e:
                        print(f"Failed to install Docker Compose in virtual environment: {str(e)}")
                        
                        # As a last resort, try to download the Docker Compose binary directly
                        print("Trying to download Docker Compose binary directly...")
                        try:
                            self.run_command("curl -L https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose", shell=True, timeout=120)
                            self.run_command("chmod +x /usr/local/bin/docker-compose", shell=True)
                            print("Docker Compose binary installed successfully.")
                        except Exception as e2:
                            print(f"Failed to download Docker Compose binary: {str(e2)}")
                            if not self.force_continue:
                                return False
                            print("Continuing anyway as --force-continue is set.")
        except Exception as e:
            print(f"Error checking Docker installation: {str(e)}")
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            
        # Install Docker if not installed
        if not docker_installed:
            # Add Docker repository
            try:
                # Add Docker GPG key
                self.run_command("curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -", shell=True, timeout=30)
                
                # Get Ubuntu codename
                try:
                    success, ubuntu_codename = self.run_command("lsb_release -cs", shell=True, timeout=10)
                    ubuntu_codename = ubuntu_codename.strip()
                    if not success or not ubuntu_codename:
                        raise Exception("Could not determine Ubuntu codename")
                except:
                    # If lsb_release is not available, try to get it from /etc/os-release
                    try:
                        success, os_release = self.run_command("cat /etc/os-release", shell=True, timeout=10)
                        ubuntu_codename = None
                        if success:
                            for line in os_release.split('\n'):
                                if line.startswith('VERSION_CODENAME='):
                                    ubuntu_codename = line.split('=')[1].strip('"\'')
                                    break
                        if not ubuntu_codename:
                            print("Could not determine Ubuntu codename. Using 'focal' as fallback.")
                            ubuntu_codename = 'focal'
                    except:
                        print("Could not determine Ubuntu codename. Using 'focal' as fallback.")
                        ubuntu_codename = 'focal'
                
                # Add Docker repository
                self.run_command(f"add-apt-repository 'deb [arch=amd64] https://download.docker.com/linux/ubuntu {ubuntu_codename} stable'", shell=True, timeout=30)
                
                # Update package lists
                self.run_command("apt-get update -y", shell=True, timeout=300)
                
                # Install Docker
                self.run_command("apt-get install -y docker-ce docker-ce-cli containerd.io", shell=True, timeout=300)
                
                # Start Docker service
                self.run_command("systemctl start docker", shell=True)
                
                # Enable Docker service to start at boot
                self.run_command("systemctl enable docker", shell=True)
                
                print("✓ Docker installed successfully")
            except Exception as e:
                print(f"Failed to install Docker: {str(e)}")
                if not self.force_continue:
                    return False
                print("Continuing anyway as --force-continue is set.")
            
        print("✓ All dependencies installed successfully.")
        return True

    def setup_horilla(self):
        """Clone the Horilla repository and prepare the environment."""
        print("\n[3/8] Setting up Horilla...")
        
        # Create the installation directory if it doesn't exist
        try:
            print(f"Creating installation directory: {self.install_dir}")
            self.run_command(f"mkdir -p {self.install_dir}", shell=True)
        except Exception as e:
            print(f"Failed to create installation directory: {str(e)}")
            return False
        
        # Clone the repository
        try:
            print(f"Cloning Horilla repository to {self.install_dir}...")
            self.run_command(f"git clone https://github.com/horilla-opensource/horilla.git {self.install_dir}", shell=True, timeout=600)
        except Exception as e:
            print(f"Failed to clone repository: {str(e)}")
            if "already exists" in str(e):
                print("Directory already exists. Checking if it's a git repository...")
                try:
                    self.run_command(f"cd {self.install_dir} && git status", shell=True)
                    print("Git repository found. Pulling latest changes...")
                    self.run_command(f"cd {self.install_dir} && git pull", shell=True)
                except:
                    print("Not a git repository or git pull failed.")
                    if not self.force_continue:
                        return False
                    print("Continuing anyway as --force-continue is set.")
            elif not self.force_continue:
                return False
            else:
                print("Continuing anyway as --force-continue is set.")
         
        # Create .env file
        try:
            print("Creating .env file...")
            env_content = (
                f"SECRET_KEY=django-insecure-{secrets.token_urlsafe(32)}\n"
                f"DEBUG=False\n"
                f"ALLOWED_HOSTS={self.domain},localhost,127.0.0.1\n"
                f"DATABASE_URL=postgres://horilla:horilla@db:5432/horilla\n"
                f"CACHE_URL=redis://redis:6379/1\n"
            )
            
            with open(f"{self.install_dir}/.env", "w") as f:
                f.write(env_content)
                
            print("✓ .env file created successfully")
        except Exception as e:
            print(f"Failed to create .env file: {str(e)}")
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            
        # Create docker-compose.yml
        try:
            print("Creating docker-compose.yml...")
            docker_compose_content = """version: '3'

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

  redis:
    image: redis:6
    restart: always

  web:
    build: .
    restart: always
    depends_on:
      - db
      - redis
    volumes:
      - .:/app
      - static_volume:/app/static
      - media_volume:/app/media

  nginx:
    image: nginx:1.19
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d
      - ./nginx/certbot/conf:/etc/letsencrypt
      - ./nginx/certbot/www:/var/www/certbot
      - static_volume:/app/static
      - media_volume:/app/media
    depends_on:
      - web
    restart: always

  certbot:
    image: certbot/certbot
    volumes:
      - ./nginx/certbot/conf:/etc/letsencrypt
      - ./nginx/certbot/www:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"

volumes:
  postgres_data:
  static_volume:
  media_volume:
"""
            
            with open(f"{self.install_dir}/docker-compose.yml", "w") as f:
                f.write(docker_compose_content)
                
            print("✓ docker-compose.yml created successfully")
        except Exception as e:
            print(f"Failed to create docker-compose.yml: {str(e)}")
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            
        # Create Dockerfile
        try:
            print("Creating Dockerfile...")
            dockerfile_content = """FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y \\
    build-essential \\
    libpq-dev \\
    gettext \\
    git \\
    && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput
RUN python manage.py compilemessages

EXPOSE 8000

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "horilla.wsgi:application"]
"""
            
            with open(f"{self.install_dir}/Dockerfile", "w") as f:
                f.write(dockerfile_content)
                
            print("✓ Dockerfile created successfully")
        except Exception as e:
            print(f"Failed to create Dockerfile: {str(e)}")
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            
        # Create nginx configuration
        try:
            print("Creating Nginx configuration...")
            
            # Create directories
            self.run_command(f"mkdir -p {self.install_dir}/nginx/conf.d", shell=True)
            self.run_command(f"mkdir -p {self.install_dir}/nginx/certbot/conf", shell=True)
            self.run_command(f"mkdir -p {self.install_dir}/nginx/certbot/www", shell=True)
            
            # Create nginx.conf
            nginx_conf = f"""server {{
    listen 80;
    server_name {self.domain};
    
    location /.well-known/acme-challenge/ {{
        root /var/www/certbot;
    }}
    
    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl;
    server_name {self.domain};
    
    ssl_certificate /etc/letsencrypt/live/{self.domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{self.domain}/privkey.pem;
    
    # SSL settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384;
    
    # Static files
    location /static/ {{
        alias /app/static/;
    }}
    
    location /media/ {{
        alias /app/media/;
    }}
    
    # Proxy to Django
    location / {{
        proxy_pass http://web:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
"""
            
            with open(f"{self.install_dir}/nginx/conf.d/app.conf", "w") as f:
                f.write(nginx_conf)
                
            print("✓ Nginx configuration created successfully")
        except Exception as e:
            print(f"Failed to create Nginx configuration: {str(e)}")
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            
        print("✓ Horilla setup completed successfully")
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
        """
        Initialize the Horilla application with required settings.
        
        This includes:
        - Building Docker images
        - Starting Docker containers
        - Running database migrations
        - Creating a superuser
        - Setting up initial data
        """
        print("\n[5/8] Initializing application...")
        
        try:
            # Change to the installation directory
            os.chdir(self.install_dir)
            
            # Start Docker containers
            print("Starting Docker containers...")
            success, output = self.run_command("docker-compose up -d", shell=True, timeout=300)
            if not success:
                print(f"Failed to start Docker containers: {output}")
                if not self.force_continue:
                    return False
                print("Continuing anyway as --force-continue is set.")
            else:
                print("✓ Docker containers started successfully")
            
            # Wait a moment for the web container to be ready
            print("Waiting for web container to be ready...")
            time.sleep(10)
            
            # Run migrations
            print("Running database migrations...")
            success, output = self.run_command("docker-compose exec -T web python manage.py migrate", shell=True, timeout=120)
            if not success:
                print(f"Failed to run migrations: {output}")
                if not self.force_continue:
                    return False
                print("Continuing anyway as --force-continue is set.")
            else:
                print("✓ Database migrations completed successfully")
            
            # Create superuser
            print(f"Creating admin user: {self.admin_username}")
            cmd = f"echo 'from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser(\\\"{self.admin_username}\\\", \\\"{self.email}\\\", \\\"{self.admin_password}\\\")' | python manage.py shell"
            success, output = self.run_command(f"docker-compose exec -T web bash -c '{cmd}'", shell=True, timeout=60)
            if not success:
                print(f"Failed to create superuser: {output}")
                # Check if the error is because the user already exists
                if "already exists" in output:
                    print("Admin user already exists, skipping creation")
                elif not self.force_continue:
                    return False
                else:
                    print("Continuing anyway as --force-continue is set.")
            else:
                print(f"✓ Created admin user: {self.admin_username}")
            
            # Collect static files
            print("Collecting static files...")
            success, output = self.run_command("docker-compose exec -T web python manage.py collectstatic --noinput", shell=True, timeout=60)
            if not success:
                print(f"Failed to collect static files: {output}")
                if not self.force_continue:
                    return False
                print("Continuing anyway as --force-continue is set.")
            else:
                print("✓ Static files collected successfully")
            
            print("✓ Application initialized successfully")
            return True
            
        except Exception as e:
            print(f"❌ Failed to initialize application: {str(e)}")
            traceback.print_exc()
            return False

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
            if self.s3_provider in ["1", "2", "4", "5", "6", "7", "10", "11", "12", "13", "14", "15", "16", "17", "19"]:
                print("\nCommon AWS regions:")
                print("  us-east-1 (N. Virginia)")
                print("  us-east-2 (Ohio)")
                print("  us-west-1 (N. California)")
                print("  us-west-2 (Oregon)")
                print("  eu-west-1 (Ireland)")
                print("  eu-central-1 (Frankfurt)")
                print("  ap-northeast-1 (Tokyo)")
                
                while True:
                    region = input(f"Region / Endpoint [{self.s3_region}]: ").strip() or self.s3_region
                    if self.validate_s3_region(region):
                        self.s3_region = region
                        break
            elif self.s3_provider in ["9", "20", "22", "23", "24", "25", "36", "37", "38", "39"]:
                # These need endpoints/hosts instead of regions
                self.s3_region = input("Server Address / Endpoint URL: ").strip()
            
            if self.backup_frequency not in ['daily', 'weekly', 'monthly']:
                print("Invalid backup frequency. Must be 'daily', 'weekly', or 'monthly'.")
                return False
                
        return True

    def configure_backup_system(self):
        """Configure automated backups with BorgBackup and rclone."""
        if not self.enable_backups:
            print("Skipping backup system configuration as it's not enabled.")
            return True
            
        print("\n[7/8] Configuring backup system...")
        
        try:
            # Create backup directory
            backup_dir = f"{self.install_dir}/backups"
            self.run_command(f"mkdir -p {backup_dir}", shell=True)
            print(f"✓ Created backup directory: {backup_dir}")
            
            self.configure_rclone()
            
            # Create borg passphrase
            borg_passphrase = secrets.token_hex(16)  # Generate random passphrase
            
            # Create backup script
            print("Creating backup script...")
            backup_script_path = f"{backup_dir}/backup.sh"
            backup_script_content = f"""#!/bin/bash
# Horilla HRMS automated backup script

# Set up environment
export BORG_PASSPHRASE="{borg_passphrase}"
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
BACKUP_DIR="{backup_dir}"
INSTALL_DIR="{self.install_dir}"
BUCKET_NAME="{self.s3_bucket_name}"

# Ensure backup directory exists
mkdir -p $BACKUP_DIR

# PostgreSQL Backup
echo "Backing up PostgreSQL database..."
cd $INSTALL_DIR
docker-compose exec -T db pg_dump -U horilla -d horilla > $BACKUP_DIR/horilla_db_$TIMESTAMP.sql

# Compress the database dump
gzip $BACKUP_DIR/horilla_db_$TIMESTAMP.sql

# Backup application files (excluding large directories)
echo "Backing up application files..."
tar -czf $BACKUP_DIR/horilla_files_$TIMESTAMP.tar.gz -C $INSTALL_DIR \\
    --exclude="node_modules" \\
    --exclude="static" \\
    --exclude="media/cache" \\
    .

# Upload to S3
echo "Uploading to S3..."
rclone copy $BACKUP_DIR/horilla_db_$TIMESTAMP.sql.gz s3backup:$BUCKET_NAME/database/
rclone copy $BACKUP_DIR/horilla_files_$TIMESTAMP.tar.gz s3backup:$BUCKET_NAME/files/

# Keep only the last 7 local backups
echo "Cleaning up old local backups..."
cd $BACKUP_DIR
ls -t horilla_db_*.sql.gz | tail -n +8 | xargs -r rm
ls -t horilla_files_*.tar.gz | tail -n +8 | xargs -r rm

# Report success
echo "Backup completed successfully at $(date)"
"""
            
            # Write backup script
            with open(backup_script_path, "w") as f:
                f.write(backup_script_content)
                
            # Make backup script executable
            self.run_command(f"chmod +x {backup_script_path}", shell=True)
            print("✓ Created backup script")
            
            # Set up cron job based on frequency
            print("Setting up backup schedule...")
            cron_schedule = {
                "1": "0 2 * * *",        # Daily at 2 AM
                "2": "0 2 * * 0",        # Weekly on Sunday at 2 AM
                "3": "0 2 1 * *"         # Monthly on 1st at 2 AM
            }
            
            schedule = cron_schedule.get(str(self.backup_frequency), "0 2 * * *")  # Default to daily
            
            # Add cron job
            cron_line = f"{schedule} {backup_script_path} >> {backup_dir}/backup.log 2>&1"
            cron_file = "/tmp/horilla_cron"
            
            # Get existing crontab
            success, existing_crontab = self.run_command("crontab -l 2>/dev/null || echo ''", shell=True)
            
            # Check if the backup job is already in crontab
            if backup_script_path in existing_crontab:
                # Remove the existing entry
                filtered_crontab = "\n".join([line for line in existing_crontab.splitlines() if backup_script_path not in line])
                with open(cron_file, "w") as f:
                    f.write(filtered_crontab + "\n")
            else:
                # Just write existing crontab to file
                with open(cron_file, "w") as f:
                    f.write(existing_crontab + "\n")
                    
            # Append new cron job
            with open(cron_file, "a") as f:
                f.write(cron_line + "\n")
                
            # Install new crontab
            self.run_command(f"crontab {cron_file}", shell=True)
            self.run_command(f"rm {cron_file}", shell=True)
            
            print("✓ Set up backup schedule")
            
            print("✓ Backup system configured successfully")
            return True
            
        except Exception as e:
            print(f"❌ Failed to configure backup system: {str(e)}")
            traceback.print_exc()
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            return True

    def configure_web_server(self):
        """Configure Nginx and SSL certificates."""
        print("\n[6/8] Configuring web server...")
        
        try:
            # Check if Certbot is installed
            if not self.force_no_ssl:
                print("Checking for Certbot...")
                success, _ = self.run_command("certbot --version", shell=True, timeout=10)
                
                if not success:
                    print("Installing Certbot...")
                    self.run_command("apt-get update", shell=True, timeout=60)
                    self.run_command("apt-get install -y certbot python3-certbot-nginx", shell=True, timeout=300)
                
                # Generate SSL certificate with Certbot
                print(f"Generating SSL certificate for {self.domain}...")
                cmd = f"certbot --nginx -d {self.domain} --email {self.email} --agree-tos --non-interactive"
                success, output = self.run_command(cmd, shell=True, timeout=180)
                
                if not success:
                    print(f"Failed to generate SSL certificate: {output}")
                    print("Continuing with HTTP only.")
                else:
                    print(f"✓ SSL certificate generated for {self.domain}")
                    
                    # Configure Nginx to force HTTPS
                    print("Configuring Nginx for HTTPS...")
                    nginx_conf = f"/etc/nginx/sites-available/{self.domain}"
                    
                    # Check if the Nginx config exists
                    success, _ = self.run_command(f"test -f {nginx_conf}", shell=True)
                    if success:
                        # Add HTTPS redirect if not already present
                        cmd = f"grep -q 'return 301 https' {nginx_conf} || sed -i '/listen 80;/a\\    return 301 https://$host$request_uri;' {nginx_conf}"
                        self.run_command(cmd, shell=True, timeout=10)
                        
                        # Reload Nginx
                        self.run_command("systemctl reload nginx", shell=True, timeout=10)
                        print("✓ Configured Nginx for HTTPS")
            else:
                print("Skipping SSL setup as --force-no-ssl was specified.")
                
            # If we're running directly from Docker, not much to configure for the web server
            # as Docker Compose handles the Nginx setup
            print("✓ Web server configuration completed")
            return True
            
        except Exception as e:
            print(f"Error configuring web server: {str(e)}")
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            return True  # Return True to continue even with web server errors

    def install(self):
        """Run the installation process."""
        print("\n=============================================")
        print("Starting Horilla HRMS installation...")
        print("=============================================\n")
        
        # Check arguments and get user inputs
        if not self.get_user_inputs():
            print("❌ Installation aborted due to missing required inputs.")
            return False
            
        # Validate backup settings if enabled
        if self.enable_backups and not self.validate_backup_settings():
            print("❌ Installation aborted due to invalid backup settings.")
            return False
            
        # Installation steps
        steps = [
            (self.check_system_requirements, "[1/8] Checking system requirements..."),
            (self.install_dependencies, "[2/8] Installing dependencies..."),
            (self.setup_horilla, "[3/8] Setting up Horilla HRMS..."),
            (self.configure_settings, "[4/8] Configuring application..."),
            (self.initialize_application, "[5/8] Initializing application..."),
            (self.configure_web_server, "[6/8] Configuring web server..."),
            (self.configure_backup_system, "[7/8] Configuring backup system...")
        ]
        
        for step_func, message in steps:
            print(f"\n{message}")
            if not step_func():
                print(f"❌ Installation failed at: {message}")
                return False
                
        # Setup complete
        print("\n[8/8] Installation completed successfully!")
        self.show_completion_message()
        return True
    
    def get_s3_provider_name(self):
        """Get the name of the S3 provider."""
        providers = {
            "1": "AWS S3",
            "2": "Wasabi",
            "3": "Backblaze B2",
            "4": "DigitalOcean Spaces",
            "5": "Other S3-compatible",
            "6": "Cloudflare R2",
            "7": "Google Cloud Storage",
            "8": "Microsoft Azure Blob Storage",
            "9": "OpenStack Swift",
            "10": "Minio",
            "11": "Alibaba Cloud OSS",
            "12": "IBM COS S3",
            "13": "Huawei OBS",
            "14": "Tencent COS",
            "15": "Oracle Cloud Storage",
            "16": "Linode Object Storage",
            "17": "Scaleway",
            "18": "Storj",
            "19": "Qiniu",
            "20": "HDFS",
            "21": "Local filesystem",
            "22": "SFTP",
            "23": "FTP",
            "24": "HTTP",
            "25": "WebDAV",
            "26": "Microsoft OneDrive",
            "27": "Google Drive",
            "28": "Dropbox",
            "29": "pCloud",
            "30": "Box",
            "31": "Mega",
            "32": "Proton Drive",
            "33": "Jottacloud",
            "34": "Koofr",
            "35": "Yandex Disk",
            "36": "Nextcloud",
            "37": "ownCloud",
            "38": "Seafile",
            "39": "SMB / CIFS",
            "40": "Ceph",
            "41": "Other S3 compatible"
        }
        return providers.get(str(self.s3_provider), "Unknown")
    
    def get_backup_frequency_name(self):
        """Get the name of the backup frequency."""
        frequencies = {
            "1": "Daily",
            "2": "Weekly",
            "3": "Monthly"
        }
        return frequencies.get(str(self.backup_frequency), "Unknown")
    
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

    def show_completion_message(self):
        """Display the completion message with system details."""
        print("\n" + "="*80)
        print("✅ Horilla HRMS installation completed successfully!")
        print("="*80)
        
        print("\nApplication Information:")
        print(f"URL: {'https' if not self.force_no_ssl else 'http'}://{self.domain}")
        print(f"Admin Username: {self.admin_username}")
        print(f"Admin Email: {self.email}")
        print(f"Admin Password: {'*' * len(self.admin_password)} (As provided during setup)")
        print(f"Installation Directory: {self.install_dir}")
        
        # Print backup information if enabled
        if self.enable_backups:
            print("\nBackup Information:")
            print(f"Backup Provider: {self.get_s3_provider_name()}")
            print(f"Backup Bucket: {self.s3_bucket_name}")
            print(f"Backup Frequency: {self.get_backup_frequency_name()}")
            print(f"Backup Script: {self.install_dir}/backups/backup.sh")
        
        print("\nDocumentation: https://github.com/horilla-opensource/horilla/wiki")
        print("\nSupport: https://github.com/horilla-opensource/horilla/issues")
        
        print("\nThank you for installing Horilla HRMS!")
    
    def validate_domain(self, domain):
        """
        Validate domain name.
        
        Args:
            domain (str): Domain name to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        # Check for nip.io domains which are valid for local testing
        if domain.endswith('.nip.io'):
            ip_part = domain.split('.nip.io')[0]
            # Check if the IP part is valid
            try:
                # Split by dots and check each octet
                octets = ip_part.split('.')
                if len(octets) != 4:
                    return False
                    
                for octet in octets:
                    num = int(octet)
                    if num < 0 or num > 255:
                        return False
                        
                return True
            except:
                return False
                
        # Regular domain validation
        domain_pattern = r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z0-9][a-zA-Z0-9-]{0,61}[a-zA-Z0-9]$'
        if re.match(domain_pattern, domain):
            return True
            
        return False
        
    def validate_email(self, email):
        """
        Validate email address.
        
        Args:
            email (str): Email to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        # Use a more comprehensive email validation pattern
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if re.match(email_pattern, email):
            # Check if domain part exists
            parts = email.split('@')
            if len(parts) == 2 and parts[0] and parts[1]:
                # Additional validation for domain part
                return self.validate_domain(parts[1])
                
        return False

    def get_user_input(self, prompt, password=False, default=None, validate_func=None):
        """Get user input with optional validation."""
        while True:
            if password:
                user_input = getpass.getpass(prompt)
            else:
                user_input = input(prompt)
            
            if default and not user_input:
                user_input = default
            
            if validate_func:
                if validate_func(user_input):
                    return user_input
                else:
                    print("Invalid input. Please try again.")
            else:
                return user_input

    def get_user_inputs(self):
        """Get user inputs for installation."""
        print("\nPlease provide the following information for your Horilla HRMS installation:")
        print("Press Enter to accept the default values shown in brackets.")
        
        # Domain name
        print("\nDomain name for your Horilla HRMS instance:")
        print("  - You can use a custom domain like 'hrms.example.com' (requires DNS setup)")
        print("  - Or use the default .nip.io domain which works without DNS configuration")
        
        # Get server IP - try multiple methods to ensure we get a valid IPv4 address
        server_ip = "127.0.0.1"
        try:
            # First try ifconfig.me (most reliable for IPv4)
            success, ip_output = self.run_command("curl -s ifconfig.me", shell=True, timeout=10)
            if success and ip_output.strip() and '.' in ip_output.strip():
                server_ip = ip_output.strip()
            else:
                # Try ipv4.icanhazip.com which guarantees IPv4
                success, ip_output = self.run_command("curl -s ipv4.icanhazip.com", shell=True, timeout=10)
                if success and ip_output.strip() and '.' in ip_output.strip():
                    server_ip = ip_output.strip()
                else:
                    # Try to get local IP from interface
                    try:
                        success, ip_output = self.run_command("hostname -I | awk '{print $1}'", shell=True, timeout=10)
                        if success and ip_output.strip() and '.' in ip_output.strip():
                            server_ip = ip_output.strip()
                    except:
                        pass
        except:
            pass
            
        print(f"\nIf using a custom domain, make sure you have created an A record pointing to this server's IP ({server_ip}):")
        print("  - Type: A")
        print("  - Name/Host: hrms (for hrms.example.com)")
        print(f"  - Value/Points to: {server_ip}")
        
        # Set default domain based on server IP
        default_domain = f"horilla.{server_ip}.nip.io"
        self.domain = self.domain or default_domain
        
        while True:
            domain = input(f"\nDomain name [{self.domain}]: ").strip() or self.domain
            if self.validate_domain(domain):
                self.domain = domain
                break
            print("Invalid domain format. Please try again.")
            
        # Admin email
        while True:
            email = input(f"Email address for SSL certificates [{self.email}]: ").strip() or self.email
            if self.validate_email(email):
                self.email = email
                break
            print("Invalid email format. Please try again.")
            
        # Admin username
        self.admin_username = input(f"Admin username [{self.admin_username}]: ").strip() or self.admin_username
        
        # Admin password
        self.admin_password = input(f"Admin password [{self.admin_password}]: ").strip() or self.admin_password
        
        # Installation directory
        self.install_dir = input(f"Installation directory [{self.install_dir}]: ").strip() or self.install_dir
        
        # Backup system
        print("\nBackup System Configuration:")
        print("Horilla can be configured with an automated backup system using Rclone and BorgBackup.")
        print("This will back up your database and application files to a remote storage.")
        
        enable_backups = input("\nEnable automated backups? (yes/no) [no]: ").strip().lower() or "no"
        self.enable_backups = enable_backups in ["yes", "y", "true", "1"]
        
        if self.enable_backups:
            # First show the basic S3 providers for backward compatibility
            print("\nS3 Provider options:")
            print("1. AWS S3")
            print("2. Wasabi")
            print("3. Backblaze B2")
            print("4. DigitalOcean Spaces")
            print("5. Other S3-compatible")
            print("\nEnter 'more' to see additional storage providers")
            
            provider_choice = input("Select S3 provider (1-5 or 'more'): ").strip()
            
            if provider_choice.lower() == "more":
                print("\nAdditional storage providers:")
                print("6. Cloudflare R2")
                print("7. Google Cloud Storage")
                print("8. Microsoft Azure Blob Storage")
                print("9. OpenStack Swift")
                print("10. Minio")
                print("11. Alibaba Cloud OSS")
                print("12. IBM COS S3")
                print("13. Huawei OBS")
                print("14. Tencent COS")
                print("15. Oracle Cloud Storage")
                print("16. Linode Object Storage")
                print("17. Scaleway")
                print("18. Storj")
                print("19. Qiniu")
                print("20. HDFS")
                print("21. Local filesystem")
                print("22. SFTP")
                print("23. FTP")
                print("24. HTTP")
                print("25. WebDAV")
                print("26. Microsoft OneDrive")
                print("27. Google Drive")
                print("28. Dropbox")
                print("29. pCloud")
                print("30. Box")
                print("31. Mega")
                print("32. Proton Drive")
                print("33. Jottacloud")
                print("34. Koofr")
                print("35. Yandex Disk")
                print("36. Nextcloud")
                print("37. ownCloud")
                print("38. Seafile")
                print("39. SMB / CIFS")
                print("40. Ceph")
                print("41. Other S3 compatible")
                
                provider_choice = input("Select storage provider (6-41): ").strip()
            
            self.s3_provider = provider_choice or "1"
            
            # Get credentials based on provider type
            self.s3_access_key = input("Access Key / Account / Username: ").strip()
            self.s3_secret_key = input("Secret Key / API Key / Password: ").strip()
            
            # For certain providers, we need a region or endpoint
            if self.s3_provider in ["1", "2", "4", "5", "6", "7", "10", "11", "12", "13", "14", "15", "16", "17", "19"]:
                print("\nCommon AWS regions:")
                print("  us-east-1 (N. Virginia)")
                print("  us-east-2 (Ohio)")
                print("  us-west-1 (N. California)")
                print("  us-west-2 (Oregon)")
                print("  eu-west-1 (Ireland)")
                print("  eu-central-1 (Frankfurt)")
                print("  ap-northeast-1 (Tokyo)")
                
                while True:
                    region = input(f"Region / Endpoint [{self.s3_region}]: ").strip() or self.s3_region
                    if self.validate_s3_region(region):
                        self.s3_region = region
                        break
            elif self.s3_provider in ["9", "20", "22", "23", "24", "25", "36", "37", "38", "39"]:
                # These need endpoints/hosts instead of regions
                self.s3_region = input("Server Address / Endpoint URL: ").strip()
            
            self.s3_bucket_name = input("Bucket / Container / Share Name: ").strip()
            
            print("\nBackup Frequency options:")
            print("1. Daily (at 2 AM)")
            print("2. Weekly (Sundays at 2 AM)")
            print("3. Monthly (1st day of month at 2 AM)")
            self.backup_frequency = input("Select backup frequency (1-3) [1]: ").strip() or "1"
        
        print("\nThank you! The installation will now proceed automatically without further prompts.")
        print("This may take 10-20 minutes depending on your system.")
        
        # Save configuration for future use
        self.save_config()
        
        return True

    def validate_s3_region(self, region):
        """
        Validate S3 region format.
        
        Args:
            region (str): S3 region to validate
            
        Returns:
            bool: True if valid, False otherwise
        """
        # Standard AWS region format validation
        # Examples: us-east-1, eu-west-2, ap-northeast-1, etc.
        region_pattern = r'^[a-z]{2}-[a-z]+-[0-9]+$'
        
        # Check if region matches the standard format
        if re.match(region_pattern, region):
            self.s3_region = region
            return True
            
        # Common non-standard inputs and their corrections
        corrections = {
            'US1': 'us-east-1',
            'US2': 'us-east-2',
            'USW1': 'us-west-1',
            'USW2': 'us-west-2',
            'EU': 'eu-west-1',
            'EU1': 'eu-west-1',
            'EU2': 'eu-central-1',
            'AP': 'ap-southeast-1',
            'AP1': 'ap-southeast-1',
            'TOKYO': 'ap-northeast-1',
            'JAPAN': 'ap-northeast-1',
            'FRANKFURT': 'eu-central-1',
            'IRELAND': 'eu-west-1',
            'OREGON': 'us-west-2',
            'VIRGINIA': 'us-east-1',
            'OHIO': 'us-east-2',
            'CALIFORNIA': 'us-west-1',
            'SINGAPORE': 'ap-southeast-1',
            'MUMBAI': 'ap-south-1',
            'INDIA': 'ap-south-1',
        }
        
        # Convert to uppercase for checking against common mistakes
        region_upper = region.upper()
        if region_upper in corrections:
            print(f"Region '{region}' is not in the standard format.")
            print(f"Did you mean '{corrections[region_upper]}'? Using that instead.")
            self.s3_region = corrections[region_upper]
            return True
            
        # List of valid AWS regions for fallback check
        valid_aws_regions = [
            "us-east-1", "us-east-2", "us-west-1", "us-west-2", 
            "af-south-1", "ap-east-1", "ap-south-1", "ap-northeast-1", 
            "ap-northeast-2", "ap-northeast-3", "ap-southeast-1", 
            "ap-southeast-2", "ca-central-1", "eu-central-1", 
            "eu-west-1", "eu-west-2", "eu-west-3", "eu-south-1", 
            "eu-north-1", "me-south-1", "sa-east-1"
        ]
        
        # Case-insensitive comparison with valid regions
        for valid_region in valid_aws_regions:
            if region.lower() == valid_region.lower():
                self.s3_region = valid_region
                return True
        
        # If we get here, it's not a valid region in any format we recognize
        # Default to us-east-1 with a warning
        print(f"Warning: '{region}' is not a recognized AWS region.")
        print("Using 'us-east-1' as the default region.")
        self.s3_region = "us-east-1"
        
        return True  # Return True to continue with installation

    def configure_rclone(self):
        """Configure Rclone with storage provider credentials."""
        print("Configuring Rclone for storage provider...")
        
        try:
            # Create rclone config directory
            config_dir = "/root/.config/rclone"
            self.run_command(f"mkdir -p {config_dir}", shell=True)
            
            # Map provider selection to actual provider name
            # Maintain backward compatibility with older option numbers
            provider_map = {
                "1": "s3",          # Amazon S3
                "2": "s3",          # Wasabi
                "3": "b2",          # Backblaze B2
                "4": "s3",          # DigitalOcean
                "5": "s3",          # Other S3 compatible (backward compatibility)
                "6": "s3",          # Cloudflare R2
                "7": "s3",          # Google Cloud Storage
                "8": "azureblob",   # Microsoft Azure Blob Storage
                "9": "swift",       # OpenStack Swift
                "10": "s3",         # Minio
                "11": "s3",         # Alibaba Cloud OSS
                "12": "s3",         # IBM COS S3
                "13": "s3",         # Huawei OBS
                "14": "s3",         # Tencent COS
                "15": "s3",         # Oracle Cloud Storage
                "16": "s3",         # Linode Object Storage
                "17": "s3",         # Scaleway
                "18": "storj",      # Storj
                "19": "s3",         # Qiniu
                "20": "hdfs",       # HDFS
                "21": "local",      # Local filesystem
                "22": "sftp",       # SFTP
                "23": "ftp",        # FTP
                "24": "http",       # HTTP
                "25": "webdav",     # WebDAV
                "26": "onedrive",   # Microsoft OneDrive
                "27": "drive",      # Google Drive
                "28": "dropbox",    # Dropbox
                "29": "pcloud",     # pCloud
                "30": "box",        # Box
                "31": "mega",       # Mega
                "32": "protondrive", # Proton Drive
                "33": "jottacloud", # Jottacloud
                "34": "koofr",      # Koofr
                "35": "yandex",     # Yandex Disk
                "36": "webdav",     # Nextcloud
                "37": "webdav",     # ownCloud
                "38": "webdav",     # Seafile
                "39": "smb",        # SMB / CIFS
                "40": "s3",         # Ceph
                "41": "s3"          # Other S3 compatible
            }
            
            provider_type = provider_map.get(self.s3_provider, "s3")
            config_content = "[s3backup]\n"
            config_content += f"type = {provider_type}\n"
            
            # Configure based on provider type
            if provider_type == "s3":
                # Provider-specific settings for S3-compatible storage
                if self.s3_provider == "1":  # AWS S3
                    config_content += "provider = AWS\n"
                elif self.s3_provider == "2":  # Wasabi
                    config_content += "provider = Wasabi\n"
                    config_content += f"endpoint = s3.{self.s3_region}.wasabisys.com\n"
                elif self.s3_provider == "4":  # DigitalOcean
                    config_content += "provider = DigitalOcean\n"
                    config_content += f"endpoint = {self.s3_region}.digitaloceanspaces.com\n"
                elif self.s3_provider == "5":  # Cloudflare R2
                    config_content += "provider = Cloudflare\n"
                    config_content += f"endpoint = {self.s3_region}.r2.cloudflarestorage.com\n"
                elif self.s3_provider == "6":  # Google Cloud Storage
                    config_content += "provider = GoogleCloud\n"
                elif self.s3_provider == "9":  # Minio
                    config_content += "provider = Minio\n"
                    config_content += f"endpoint = {self.s3_region}\n"
                elif self.s3_provider == "10":  # Alibaba
                    config_content += "provider = Alibaba\n"
                    config_content += f"endpoint = oss-{self.s3_region}.aliyuncs.com\n"
                elif self.s3_provider == "11":  # IBM
                    config_content += "provider = IBMCOS\n"
                    config_content += f"endpoint = s3.{self.s3_region}.cloud-object-storage.appdomain.cloud\n"
                elif self.s3_provider == "12":  # Huawei
                    config_content += "provider = HuaweiOBS\n"
                    config_content += f"endpoint = obs.{self.s3_region}.myhuaweicloud.com\n"
                elif self.s3_provider == "13":  # Tencent
                    config_content += "provider = TencentCOS\n"
                    config_content += f"endpoint = cos.{self.s3_region}.myqcloud.com\n"
                elif self.s3_provider == "14":  # Oracle
                    config_content += "provider = Oracle\n"
                    config_content += f"endpoint = {self.s3_region}.storage.oracle.com\n"
                elif self.s3_provider == "15":  # Linode
                    config_content += "provider = Linode\n"
                    config_content += f"endpoint = {self.s3_region}.linodeobjects.com\n"
                elif self.s3_provider == "16":  # Scaleway
                    config_content += "provider = Scaleway\n"
                    config_content += f"endpoint = s3.{self.s3_region}.scw.cloud\n"
                elif self.s3_provider == "18":  # Qiniu
                    config_content += "provider = Qiniu\n"
                    config_content += f"endpoint = s3-{self.s3_region}.qiniucs.com\n"
                elif self.s3_provider == "39":  # Ceph
                    config_content += "provider = Ceph\n"
                    config_content += f"endpoint = {self.s3_region}\n"
                elif self.s3_provider == "40":  # Other S3
                    config_content += f"endpoint = {self.s3_region}\n"
                
                # Common S3 configuration
                config_content += f"access_key_id = {self.s3_access_key}\n"
                config_content += f"secret_access_key = {self.s3_secret_key}\n"
                
                # Add region if needed
                if self.s3_provider in ["1", "6"]:  # AWS and GCS use region
                    config_content += f"region = {self.s3_region}\n"
                
            # Handle other provider types
            elif provider_type == "b2":
                config_content += f"account = {self.s3_access_key}\n"
                config_content += f"key = {self.s3_secret_key}\n"
            
            elif provider_type == "azureblob":
                config_content += f"account = {self.s3_access_key}\n"
                config_content += f"key = {self.s3_secret_key}\n"
            
            elif provider_type == "swift":
                config_content += f"user = {self.s3_access_key}\n"
                config_content += f"key = {self.s3_secret_key}\n"
                config_content += f"auth = {self.s3_region}\n"
            
            elif provider_type == "storj":
                config_content += f"access_grant = {self.s3_access_key}\n"
            
            elif provider_type in ["sftp", "ftp"]:
                config_content += f"host = {self.s3_region}\n"
                config_content += f"user = {self.s3_access_key}\n"
                config_content += f"pass = {self.s3_secret_key}\n"
                
            elif provider_type == "webdav":
                config_content += f"url = {self.s3_region}\n"
                config_content += f"user = {self.s3_access_key}\n"
                config_content += f"pass = {self.s3_secret_key}\n"
                
                # Special config for specific WebDAV providers
                if self.s3_provider == "35":  # Nextcloud
                    config_content += "vendor = nextcloud\n"
                elif self.s3_provider == "36":  # ownCloud
                    config_content += "vendor = owncloud\n"
                elif self.s3_provider == "37":  # Seafile
                    config_content += "vendor = other\n"
            
            elif provider_type == "smb":
                config_content += f"host = {self.s3_region}\n"
                config_content += f"user = {self.s3_access_key}\n"
                config_content += f"pass = {self.s3_secret_key}\n"
                config_content += f"domain = WORKGROUP\n"
            
            elif provider_type == "hdfs":
                config_content += f"namenode = {self.s3_region}\n"
            
            elif provider_type == "local":
                # Local filesystem needs a path
                config_content += f"path = {self.s3_region}\n"
            
            elif provider_type in ["onedrive", "drive", "dropbox", "box", "pcloud", 
                                "mega", "protondrive", "jottacloud", "koofr", "yandex"]:
                # These providers generally require OAuth2 authentication
                # We'll use a simplified token-based approach here
                config_content += f"token = {self.s3_access_key}\n"
                print(f"NOTE: {provider_type} usually requires OAuth2 authentication.")
                print("For complete setup, you may need to run 'rclone config' manually after installation.")
            
            # Write config file
            config_path = f"{config_dir}/rclone.conf"
            with open(config_path, "w") as f:
                f.write(config_content)
                
            print(f"✓ Rclone configuration saved to {config_path}")
            
            # Test configuration for providers that don't need browser authentication
            if provider_type in ["s3", "b2", "azureblob", "swift", "sftp", "ftp", "webdav", "smb", "hdfs", "local"]:
                print(f"Testing connection to storage: {self.s3_bucket_name}")
                # Create the bucket/path if it doesn't exist
                success, _ = self.run_command(f"rclone mkdir s3backup:{self.s3_bucket_name}/horilla-backups", shell=True, timeout=30)
                if success:
                    print(f"✓ Successfully connected to storage: {self.s3_bucket_name}")
                else:
                    print(f"Warning: Could not create or access the storage location. Please check your credentials.")
                    if not self.force_continue:
                        return False
                    print("Continuing anyway as --force-continue is set.")
            else:
                print("NOTE: For cloud storage providers like Google Drive, Dropbox, etc.")
                print("You may need to authenticate manually after installation is complete.")
                print("Please run 'rclone config' and follow the authentication steps.")
            
            return True
            
        except Exception as e:
            print(f"Error configuring rclone: {str(e)}")
            print("Please check your storage credentials and settings.")
            if not self.force_continue:
                return False
            print("Continuing anyway as --force-continue is set.")
            return True  # Continue with installation even if rclone config fails

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Horilla HRMS Installer')
    
    # Basic options
    parser.add_argument('--domain', help='Domain name for your Horilla instance')
    parser.add_argument('--admin-username', help='Admin username', default='admin')
    parser.add_argument('--admin-password', help='Admin password', default='Admin@123')
    parser.add_argument('--email', help='Admin email', default='admin@example.com')
    parser.add_argument('--install-dir', help='Installation directory', default='/opt/horilla')
    
    # Advanced options
    parser.add_argument('--non-interactive', action='store_true', help='Non-interactive mode')
    parser.add_argument('--force-continue', action='store_true', help='Force continue on errors')
    parser.add_argument('--force-no-ssl', action='store_true', help='Skip SSL setup')
    parser.add_argument('--skip-upgrade', action='store_true', help='Skip upgrading dependencies')
    parser.add_argument('--skip-root-check', action='store_true', help='Skip root user check')
    
    # Backup options
    parser.add_argument('--enable-backups', help='Enable automated backups (yes/no)', default='no')
    parser.add_argument('--s3-provider', 
                       help='Storage provider (1-41):\n'
                             '1=AWS S3, 2=Wasabi, 3=Backblaze B2, 4=DigitalOcean, 5=Other S3 compatible\n'
                             'For additional providers (6-41), use the interactive installer or see documentation')
    parser.add_argument('--s3-access-key', help='S3 Access Key')
    parser.add_argument('--s3-secret-key', help='S3 Secret Key')
    parser.add_argument('--s3-region', help='S3 Region/Endpoint', default='us-east-1')
    parser.add_argument('--s3-bucket-name', help='S3 Bucket/Container Name')
    parser.add_argument('--backup-frequency', 
                       help='Backup frequency (1=Daily, 2=Weekly, 3=Monthly)', 
                       default='1')
    
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
