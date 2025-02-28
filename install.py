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
from pathlib import Path


class HorillaInstaller:
    def __init__(self, domain=None, email=None, install_dir=None, 
                 db_user="postgres", db_password="postgres", db_name="horilla",
                 admin_username=None, admin_password=None, non_interactive=False,
                 skip_upgrade=True, timeout=600):
        """Initialize the installer with configuration parameters."""
        self.domain = domain
        self.email = email
        self.install_dir = install_dir or os.path.expanduser("~/horilla")
        self.db_user = db_user
        self.db_password = db_password
        self.db_name = db_name
        self.admin_username = admin_username
        self.admin_password = admin_password
        self.non_interactive = non_interactive
        self.skip_upgrade = skip_upgrade
        self.timeout = timeout
        
        # Validate if running as root or with sudo
        if os.geteuid() != 0:
            print("This script must be run as root or with sudo privileges.")
            sys.exit(1)

    def run_command(self, command, shell=False, cwd=None, env=None, timeout=None):
        """Execute a shell command and return the output."""
        if timeout is None:
            timeout = self.timeout

        try:
            if isinstance(command, str) and not shell:
                command = command.split()
            
            print(f"Running command (timeout: {timeout}s): {command}")
            
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=shell,
                cwd=cwd,
                env=env
            )
            
            try:
                stdout, stderr = process.communicate(timeout=timeout)
                returncode = process.returncode
            except subprocess.TimeoutExpired:
                process.kill()
                print(f"Command timed out after {timeout} seconds: {command}")
                return False, "Command timed out"
            
            if returncode != 0:
                print(f"Command failed with exit code {returncode}: {command}")
                print(f"Error: {stderr}")
                return False, stderr
            
            return True, stdout
        except Exception as e:
            print(f"Exception occurred: {e}")
            return False, str(e)

    def get_user_input(self, prompt, default=None, validate_func=None, password=False):
        """Get user input with validation and default values."""
        if self.non_interactive and default is not None:
            return default
        
        while True:
            if password:
                value = getpass.getpass(prompt)
            else:
                value = input(prompt)
            
            # Use default if empty
            if not value and default is not None:
                return default
            
            # Validate if needed
            if validate_func and not validate_func(value):
                continue
                
            return value

    def validate_domain(self, domain):
        """Validate domain format."""
        if not domain:
            print("Domain cannot be empty.")
            return False
            
        domain_pattern = re.compile(r'^([a-zA-Z0-9]([a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$')
        if not domain_pattern.match(domain):
            print("Invalid domain format. Please enter a valid domain (e.g., hrms.example.com).")
            return False
            
        return True

    def validate_email(self, email):
        """Validate email format."""
        if not email:
            print("Email cannot be empty.")
            return False
            
        email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
        if not email_pattern.match(email):
            print("Invalid email format. Please enter a valid email address.")
            return False
            
        return True

    def check_system_requirements(self):
        """Check if the system meets the requirements."""
        print("\n[1/8] Checking system requirements...")
        
        # Check if running on Ubuntu
        success, output = self.run_command("lsb_release -is", timeout=30)
        if not success or "Ubuntu" not in output:
            print("This script is designed for Ubuntu. Current OS:", output.strip() if success else "Unknown")
            return False
            
        print("✓ Running on Ubuntu")
        return True

    def install_dependencies(self):
        """Install required dependencies."""
        print("\n[2/8] Installing dependencies...")
        
        # Update package index
        print("Updating package index...")
        success, output = self.run_command("apt-get update -y", shell=True, timeout=300)
        if not success:
            print(f"Failed to update package index: {output}")
            return False
        
        # Skip apt upgrade if configured
        if not self.skip_upgrade:
            print("Upgrading system packages (this may take a while)...")
            success, output = self.run_command("DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -q", shell=True, timeout=600)
            if not success:
                print(f"Warning: System upgrade failed: {output}")
                print("Continuing with installation...")
        else:
            print("Skipping system upgrade...")
        
        # Install required packages
        commands = [
            "apt-get install -y apt-transport-https ca-certificates curl software-properties-common",
            "mkdir -p /etc/apt/keyrings",
            "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg",
            'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null',
            "apt-get update -y",
            "apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin",
            "apt-get install -y nginx certbot python3-certbot-nginx"
        ]
        
        for cmd in commands:
            print(f"Running: {cmd}")
            success, output = self.run_command(cmd, shell=True, timeout=300)
            if not success:
                print(f"Failed to execute: {cmd}")
                print(f"Error: {output}")
                return False
                
        print("✓ Dependencies installed successfully")
        return True

    def setup_horilla(self):
        """Clone and set up Horilla repository."""
        print("\n[3/8] Setting up Horilla...")
        
        # Create installation directory
        os.makedirs(self.install_dir, exist_ok=True)
        
        # Clone the repository
        print(f"Cloning Horilla repository to {self.install_dir}...")
        success, output = self.run_command(
            f"git clone https://github.com/horilla-opensource/horilla.git {self.install_dir}",
            shell=True
        )
        
        if not success:
            print(f"Failed to clone repository: {output}")
            return False
            
        # Make entrypoint executable
        entrypoint_path = os.path.join(self.install_dir, "entrypoint.sh")
        if os.path.exists(entrypoint_path):
            os.chmod(entrypoint_path, 0o755)
            print("✓ Made entrypoint.sh executable")
        else:
            print("Warning: entrypoint.sh not found. This might cause issues later.")
            
        print("✓ Horilla setup completed")
        return True

    def configure_settings(self):
        """Configure Horilla settings."""
        print("\n[4/8] Configuring Horilla settings...")
        
        # Get domain if not provided
        if not self.domain:
            self.domain = self.get_user_input(
                "Enter your domain (e.g., hrms.example.com): ",
                validate_func=self.validate_domain
            )
        
        settings_path = os.path.join(self.install_dir, "horilla", "settings.py")
        if not os.path.exists(settings_path):
            print(f"Error: settings.py not found at {settings_path}")
            return False
            
        # Add CSRF and ALLOWED_HOSTS settings
        with open(settings_path, "a") as f:
            f.write(f"\n# Added by installer\n")
            f.write(f"CSRF_TRUSTED_ORIGINS = ['https://{self.domain}', 'http://{self.domain}']\n")
            f.write(f"ALLOWED_HOSTS = ['{self.domain}', 'localhost', '127.0.0.1', '*']\n")
            
        print(f"✓ Updated settings.py with domain: {self.domain}")
        return True

    def setup_docker_compose(self):
        """Create and configure docker-compose.yml."""
        print("\n[5/8] Setting up Docker Compose...")
        
        docker_compose_content = f"""version: '3.8'
services:
  db:
    image: postgres:16-bullseye
    environment:
      POSTGRES_DB: {self.db_name}
      POSTGRES_USER: {self.db_user}
      POSTGRES_PASSWORD: {self.db_password}
      PGDATA: /var/lib/postgresql/data/pgdata
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "{self.db_user}"]
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
      DATABASE_URL: "postgres://{self.db_user}:{self.db_password}@db:5432/{self.db_name}"
      CSRF_TRUSTED_ORIGINS: "https://{self.domain},http://{self.domain}"
      ALLOWED_HOSTS: "{self.domain},localhost,127.0.0.1,*"
      DEBUG: "False"
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./:/app/
    command: bash -c "chmod +x /app/entrypoint.sh && /app/entrypoint.sh"

volumes:
  postgres_data:
"""
        
        docker_compose_path = os.path.join(self.install_dir, "docker-compose.yml")
        with open(docker_compose_path, "w") as f:
            f.write(docker_compose_content)
            
        print("✓ Created docker-compose.yml")
        
        # Start Docker containers
        print("Starting Docker containers...")
        success, output = self.run_command("docker compose up -d", shell=True, cwd=self.install_dir)
        if not success:
            print(f"Failed to start Docker containers: {output}")
            return False
            
        print("✓ Docker containers started")
        return True

    def configure_nginx(self):
        """Configure Nginx as a reverse proxy."""
        print("\n[6/8] Configuring Nginx...")
        
        nginx_config = f"""server {{
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
        
        nginx_conf_path = "/etc/nginx/sites-available/horilla"
        with open(nginx_conf_path, "w") as f:
            f.write(nginx_config)
            
        # Create symbolic link
        if os.path.exists("/etc/nginx/sites-enabled/horilla"):
            os.remove("/etc/nginx/sites-enabled/horilla")
            
        os.symlink(nginx_conf_path, "/etc/nginx/sites-enabled/horilla")
        
        # Test and restart Nginx
        success, output = self.run_command("nginx -t")
        if not success:
            print(f"Nginx configuration test failed: {output}")
            return False
            
        success, output = self.run_command("systemctl restart nginx")
        if not success:
            print(f"Failed to restart Nginx: {output}")
            return False
            
        print("✓ Nginx configured successfully")
        return True

    def setup_ssl(self):
        """Set up SSL with Let's Encrypt."""
        print("\n[7/8] Setting up SSL with Let's Encrypt...")
        
        # Get email if not provided
        if not self.email:
            self.email = self.get_user_input(
                "Enter your email address for Let's Encrypt notifications: ",
                validate_func=self.validate_email
            )
        
        # Run certbot
        cmd = f"certbot --nginx -d {self.domain} --non-interactive --agree-tos --email {self.email} --redirect"
        success, output = self.run_command(cmd, shell=True)
        if not success:
            print(f"Failed to obtain SSL certificate: {output}")
            print("This could be due to DNS not being properly configured or the domain not pointing to this server.")
            print("You can try manually later with: certbot --nginx -d " + self.domain)
            return False
            
        print("✓ SSL certificate obtained and configured")
        return True

    def initialize_horilla(self):
        """Initialize Horilla and create admin user."""
        print("\n[8/8] Initializing Horilla...")
        
        # Wait for the application to be ready
        print("Waiting for the application to initialize (this may take a minute)...")
        time.sleep(30)
        
        # Get admin credentials if not provided
        if not self.admin_username:
            self.admin_username = self.get_user_input(
                "Enter admin username [admin]: ",
                default="admin"
            )
            
        if not self.admin_password:
            while True:
                self.admin_password = self.get_user_input(
                    "Enter admin password (min 8 characters): ",
                    password=True
                )
                if len(self.admin_password) >= 8:
                    break
                print("Password must be at least 8 characters long.")
        
        # Create superuser
        cmd = f'docker compose exec -T server python manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); User.objects.create_superuser(\'{self.admin_username}\', \'admin@example.com\', \'{self.admin_password}\')" || true'
        success, output = self.run_command(cmd, shell=True, cwd=self.install_dir)
        
        print("✓ Horilla initialized")
        return True

    def run(self):
        """Run the complete installation process."""
        print("=" * 60)
        print("Horilla HRMS Automated Installation")
        print("=" * 60)
        
        steps = [
            self.check_system_requirements,
            self.install_dependencies,
            self.setup_horilla,
            self.configure_settings,
            self.setup_docker_compose,
            self.configure_nginx,
            self.setup_ssl,
            self.initialize_horilla
        ]
        
        for step in steps:
            if not step():
                print("\n❌ Installation failed at step:", step.__name__)
                return False
                
        print("\n" + "=" * 60)
        print("✅ Installation completed successfully!")
        print(f"You can now access Horilla HRMS at: https://{self.domain}")
        print(f"Admin username: {self.admin_username}")
        print("=" * 60)
        
        return True


def main():
    parser = argparse.ArgumentParser(description="Horilla HRMS Automated Installation")
    parser.add_argument("--domain", help="Domain name for Horilla (e.g., hrms.example.com)")
    parser.add_argument("--email", help="Email address for Let's Encrypt notifications")
    parser.add_argument("--install-dir", help="Installation directory (default: ~/horilla)")
    parser.add_argument("--db-user", default="postgres", help="Database username")
    parser.add_argument("--db-password", help="Database password")
    parser.add_argument("--db-name", default="horilla", help="Database name")
    parser.add_argument("--admin-username", help="Admin username")
    parser.add_argument("--admin-password", help="Admin password")
    parser.add_argument("--non-interactive", action="store_true", help="Run in non-interactive mode (requires all parameters)")
    parser.add_argument("--no-skip-upgrade", action="store_false", dest="skip_upgrade", help="Do not skip system upgrade (apt upgrade)")
    parser.add_argument("--timeout", type=int, default=600, help="Command execution timeout in seconds (default: 600)")
    
    args = parser.parse_args()
    
    # Validate non-interactive mode has all required parameters
    if args.non_interactive and (not args.domain or not args.email or not args.admin_password):
        print("Error: Non-interactive mode requires --domain, --email, and --admin-password")
        sys.exit(1)
    
    installer = HorillaInstaller(
        domain=args.domain,
        email=args.email,
        install_dir=args.install_dir,
        db_user=args.db_user,
        db_password=args.db_password or "postgres",
        db_name=args.db_name,
        admin_username=args.admin_username,
        admin_password=args.admin_password,
        non_interactive=args.non_interactive,
        skip_upgrade=args.skip_upgrade,
        timeout=args.timeout
    )
    
    if installer.run():
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
