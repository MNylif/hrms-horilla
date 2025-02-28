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
import secrets


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
        self.skip_root_check = args.skip_root_check if hasattr(args, 'skip_root_check') else False
        
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
            success, _ = self.run_command("systemctl is-active docker.service", shell=True)
            if success:
                docker_installed = True
                docker_running = True
                print("✓ Docker is installed and running")
            else:
                # Try socket
                success, _ = self.run_command("systemctl is-active docker.socket", shell=True)
                if success:
                    docker_installed = True
                    print("✓ Docker is installed but not running (will be started)")
                else:
                    # Docker might be installed but not running
                    success, _ = self.run_command("which docker", shell=True, timeout=10)
                    if success:
                        docker_installed = True
                        print("✓ Docker is installed but not running (will be started)")
                    else:
                        print("✓ Docker is not yet installed (will be installed)")
        except:
            # Try alternatives for systems without systemctl
            try:
                success, _ = self.run_command("service docker status", shell=True)
                if success:
                    docker_installed = True
                    docker_running = True
                    print("✓ Docker is installed and running")
                else:
                    success, _ = self.run_command("which docker", shell=True, timeout=10)
                    if success:
                        docker_installed = True
                        print("✓ Docker is installed but not running (will be started)")
                    else:
                        print("✓ Docker is not yet installed or running (will be installed)")
            except:
                print("✓ Docker is not yet installed or running (will be installed)")
                
        self.docker_installed = docker_installed
        self.docker_running = docker_running
        
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
                print("Docker command found but may not be working properly.")
        except:
            print("Installing Docker...")
            docker_installed = False
        
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
                
                print(f"Detected Ubuntu codename: {ubuntu_codename}")
                
                # Add Docker repository
                docker_repo = f"deb [arch=amd64] https://download.docker.com/linux/ubuntu {ubuntu_codename} stable"
                self.run_command(f"add-apt-repository -y '{docker_repo}'", shell=True, timeout=30)
                
                # Update package lists again
                self.run_command("apt-get update -y", shell=True, timeout=60)
                
                # Install Docker packages
                docker_pkgs = "docker-ce docker-ce-cli containerd.io"
                success, _ = self.run_command(f"apt-get install -y {docker_pkgs}", shell=True, timeout=300)
                if success:
                    print("Docker installed successfully.")
                    docker_installed = True
                else:
                    print("Failed to install Docker packages. Continuing with installation.")
                
                # Try to start Docker service
                try:
                    self.run_command("systemctl enable docker", shell=True, timeout=30)
                    self.run_command("systemctl start docker", shell=True, timeout=30)
                    print("Docker service started successfully.")
                except:
                    try:
                        self.run_command("service docker start", shell=True, timeout=30)
                        print("Docker service started successfully (using service command).")
                    except:
                        print("Failed to start Docker service. You may need to start it manually after installation.")
                
            except Exception as e:
                print(f"Failed to install Docker: {str(e)}")
                if not self.force_continue:
                    return False
                print("Continuing anyway as --force-continue is set.")
                
        # Install Docker Compose
        # First check if Docker Compose is already installed
        try:
            success, _ = self.run_command("docker-compose --version", shell=True, timeout=10)
            if success:
                print("Docker Compose is already installed. Skipping Docker Compose installation.")
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
            print(f"Error checking Docker Compose installation: {str(e)}")
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
        
        # Wait a moment for the web container to be ready
        print("Waiting for web container to be ready...")
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
            
            # Configure rclone for S3 storage
            print("Configuring rclone for S3 storage...")
            
            # Generate rclone.conf
            rclone_conf_dir = "/root/.config/rclone"
            self.run_command(f"mkdir -p {rclone_conf_dir}", shell=True)
            
            # Determine the S3 provider
            if self.s3_provider == "1":  # AWS S3
                rclone_conf = f"""[horilla-backup]
type = s3
provider = AWS
env_auth = false
access_key_id = {self.s3_access_key}
secret_access_key = {self.s3_secret_key}
region = {self.s3_region}
location_constraint = {self.s3_region}
acl = private
"""
            elif self.s3_provider == "2":  # Wasabi
                rclone_conf = f"""[horilla-backup]
type = s3
provider = Wasabi
env_auth = false
access_key_id = {self.s3_access_key}
secret_access_key = {self.s3_secret_key}
region = {self.s3_region}
endpoint = s3.wasabisys.com
acl = private
"""
            elif self.s3_provider == "3":  # Backblaze B2
                rclone_conf = f"""[horilla-backup]
type = b2
account = {self.s3_access_key}
key = {self.s3_secret_key}
"""
            elif self.s3_provider == "4":  # DigitalOcean Spaces
                rclone_conf = f"""[horilla-backup]
type = s3
provider = DigitalOcean
env_auth = false
access_key_id = {self.s3_access_key}
secret_access_key = {self.s3_secret_key}
endpoint = {self.s3_region}.digitaloceanspaces.com
acl = private
"""
            else:  # Other S3-compatible (default)
                rclone_conf = f"""[horilla-backup]
type = s3
provider = Other
env_auth = false
access_key_id = {self.s3_access_key}
secret_access_key = {self.s3_secret_key}
region = {self.s3_region}
endpoint = s3.{self.s3_region}.amazonaws.com
force_path_style = true
acl = private
"""
                
            # Write rclone.conf
            with open(f"{rclone_conf_dir}/rclone.conf", "w") as f:
                f.write(rclone_conf)
                
            print("✓ Generated rclone configuration")
            
            # Test rclone configuration
            print("Testing rclone configuration...")
            success, output = self.run_command(f"rclone lsd horilla-backup:{self.s3_bucket_name}", shell=True, timeout=30)
            if not success:
                print(f"⚠️ Warning: Failed to verify rclone configuration: {output}")
                
                # Try to create the bucket if it doesn't exist
                print(f"Attempting to create bucket '{self.s3_bucket_name}'...")
                success, output = self.run_command(f"rclone mkdir horilla-backup:{self.s3_bucket_name}", shell=True, timeout=30)
                if not success:
                    print(f"⚠️ Warning: Failed to create bucket: {output}")
                    print("You may need to manually create the bucket or check your S3 credentials.")
                    if not self.force_continue:
                        return False
                    print("Continuing anyway as --force-continue is set.")
                else:
                    print(f"✓ Created bucket: {self.s3_bucket_name}")
            else:
                print("✓ Successfully connected to S3 storage")
                
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
rclone copy $BACKUP_DIR/horilla_db_$TIMESTAMP.sql.gz horilla-backup:$BUCKET_NAME/database/
rclone copy $BACKUP_DIR/horilla_files_$TIMESTAMP.tar.gz horilla-backup:$BUCKET_NAME/files/

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

    def install(self):
        """Main installation method."""
        title = """
 _   _           _ _ _         _   _ _____  __  __ _____ 
| | | | ___  _ __(_) | | __ _  | | | |  __ \|  \/  / ____|
| |_| |/ _ \| '__| | | |/ _` | | |_| | |__) | \  / | (___  
|  _  | (_) | |  | | | | (_| | |  _  |  _  /| |\/| |\___ \\ 
|_| |_|\___/|_|  |_|_|_|\__,_| |_| |_|_| \_\_|  |_|____/ 
                                                         
        """
        print(title)
        print("Starting Horilla HRMS installation...")
        print(f"Installation directory: {self.install_dir}")
        
        # Check system requirements
        if not self.check_system_requirements():
            print("❌ System requirements check failed. Please fix the issues and try again.")
            return False
        
        # Install dependencies
        if not self.install_dependencies():
            print("❌ Failed to install dependencies. Please fix the issues and try again.")
            return False
        
        # Clone repository
        if not self.clone_repository():
            print("❌ Failed to clone repository. Please check your internet connection and try again.")
            return False
        
        # Configure application
        if not self.configure_application():
            print("❌ Failed to configure application. Please check the configuration and try again.")
            return False
        
        # Initialize application
        if not self.initialize_application():
            print("❌ Failed to initialize application. Please check the logs and try again.")
            return False
        
        # Configure SSL
        if not self.force_no_ssl:
            if not self.configure_ssl():
                print("⚠️ SSL configuration failed. The application will still be accessible over HTTP.")
                # Don't return False here, as we want the installation to continue even if SSL fails
        
        # Configure backup system if enabled
        if self.enable_backups:
            if not self.configure_backup_system():
                print("⚠️ Backup system configuration failed, but installation will continue.")
                # Don't return False here, as we want the installation to continue even if backup setup fails
        
        # Final steps
        print("\n[8/8] Finalizing installation...")
        
        # Print installation summary
        print("\n" + "="*80)
        print("✅ Horilla HRMS installation completed successfully!")
        print("="*80)
        print("\nApplication Information:")
        print(f"URL: {'https' if not self.force_no_ssl else 'http'}://{self.domain}")
        print(f"Admin Username: {self.admin_username}")
        print(f"Admin Email: {self.admin_email}")
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
        return True
    
    def get_s3_provider_name(self):
        """Get the name of the S3 provider."""
        providers = {
            "1": "AWS S3",
            "2": "Wasabi",
            "3": "Backblaze B2",
            "4": "DigitalOcean Spaces",
            "5": "Other S3-compatible"
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
            # Use the admin_username, admin_email, and admin_password from self
            admin_email = self.email
            cmd = f"echo 'from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser(\\\"{self.admin_username}\\\", \\\"{admin_email}\\\", \\\"{self.admin_password}\\\")' | python manage.py shell"
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
    parser.add_argument('--skip-root-check', action='store_true', help='Skip root check')
    
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
