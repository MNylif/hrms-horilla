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


class HorillaInstaller:
    def __init__(self, domain=None, email=None, admin_username=None, admin_password=None, 
                 install_dir=None, db_name="horilla", db_user="horilla", db_password="horilla",
                 non_interactive=False, force_continue=False, skip_upgrade=False, is_tty=False):
        """Initialize the installer with configuration parameters."""
        self.domain = domain
        self.email = email
        self.admin_username = admin_username
        self.admin_password = admin_password
        self.install_dir = install_dir or "/root/horilla"
        self.db_name = db_name
        self.db_user = db_user
        self.db_password = db_password
        self.non_interactive = non_interactive
        self.force_continue = force_continue
        self.skip_upgrade = skip_upgrade
        self.is_tty = is_tty
        
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
        """Execute a shell command and return the output."""
        if timeout is None:
            timeout = 600

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

    def check_apt_processes(self):
        """Check for running apt processes and return details."""
        cmd = "ps aux | grep -E 'apt|dpkg' | grep -v grep || true"
        success, output = self.run_command(cmd, shell=True)
        
        if not success:
            return []
            
        processes = []
        for line in output.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 2:
                    pid = parts[1]
                    command = ' '.join(parts[10:]) if len(parts) > 10 else 'unknown'
                    processes.append((pid, command))
        
        return processes

    def check_process_age(self, pid):
        """Check how long a process has been running."""
        cmd = f"ps -o etimes= -p {pid}"
        success, output = self.run_command(cmd, shell=True)
        
        if not success or not output.strip():
            return None
            
        try:
            seconds = int(output.strip())
            return seconds
        except ValueError:
            return None

    def run_apt_command(self, command, timeout=None):
        """Run an apt command with retries for lock issues."""
        for attempt in range(1, 6):  # max 5 attempts
            success, output = self.run_command(command, shell=True, timeout=timeout)
            
            # Check if it's a lock error
            if not success and ('Could not get lock' in output or 'Unable to acquire' in output or 'dpkg frontend lock' in output):
                # Extract the PID from the error message if possible
                pid_match = re.search(r'process (\d+)', output)
                locking_pid = pid_match.group(1) if pid_match else None
                
                # Check for running apt processes
                apt_processes = self.check_apt_processes()
                
                if locking_pid:
                    # Check how long the locking process has been running
                    age_seconds = self.check_process_age(locking_pid)
                    age_minutes = age_seconds // 60 if age_seconds else None
                    
                    print(f"\nLock is held by process {locking_pid}")
                    if age_minutes:
                        print(f"This process has been running for {age_minutes} minutes.")
                    
                    # Print what the process is doing
                    for pid, cmd in apt_processes:
                        if pid == locking_pid:
                            print(f"Process {pid} is running: {cmd}")
                
                print("\nRunning apt/dpkg processes:")
                if apt_processes:
                    for pid, cmd in apt_processes:
                        print(f"  PID {pid}: {cmd}")
                else:
                    print("  No apt/dpkg processes found (the lock might be stale)")
                
                # If we've tried a few times and there's still a lock, ask what to do
                if attempt >= 3 and not self.force_continue and self.is_tty:
                    print("\nThe system package manager is locked by another process.")
                    print("Options:")
                    print("  1. Wait and retry (recommended if a system update is in progress)")
                    print("  2. Abort installation")
                    print("  3. Try to continue anyway (may cause issues)")
                    
                    try:
                        choice = input("\nEnter your choice (1-3): ").strip()
                        
                        if choice == '2':
                            print("Aborting installation as requested.")
                            sys.exit(0)
                        elif choice == '3':
                            print("Attempting to continue despite lock issues...")
                            # Skip this command and proceed
                            return True, "Skipped due to lock"
                    except (EOFError, KeyboardInterrupt):
                        # If we can't get input, default to option 1 (wait and retry)
                        print("\nCannot read input. Defaulting to wait and retry.")
                
                if attempt < 5:
                    print(f"\nWaiting {10} seconds before retry {attempt}/5...")
                    time.sleep(10)
                    continue
            
            # Either it succeeded or it failed with a non-lock error, or we're out of retries
            return success, output
        
        # If we're here, we've exhausted all retries
        if not self.force_continue and self.is_tty:
            print("\nCould not acquire package manager lock after multiple attempts.")
            print("Options:")
            print("  1. Abort installation (recommended)")
            print("  2. Try to continue anyway (may cause issues)")
            
            try:
                choice = input("\nEnter your choice (1-2): ").strip()
                
                if choice == '2':
                    print("Attempting to continue despite lock issues...")
                    return True, "Skipped due to lock"
                else:
                    print("Aborting installation as requested.")
                    sys.exit(0)
            except (EOFError, KeyboardInterrupt):
                # If we can't get input, default to aborting
                print("\nCannot read input. Aborting installation.")
                sys.exit(1)
        elif self.force_continue:
            print("Force continue enabled. Skipping this command and proceeding...")
            return True, "Skipped due to lock (force continue enabled)"
        
        return False, f"Failed after 5 attempts: {command}"

    def get_user_input(self, prompt, default=None, validate_func=None, password=False):
        """Get user input with validation and default values."""
        if self.non_interactive:
            if default is not None:
                return default
            else:
                print(f"Error: Required input '{prompt}' has no default value in non-interactive mode.")
                sys.exit(1)
        
        # Ensure we're in a TTY environment
        if not self.is_tty:
            print(f"Warning: Not in a TTY environment. Using default value: {default}")
            if default is None:
                print(f"Error: Required input '{prompt}' has no default value in non-TTY environment.")
                sys.exit(1)
            return default
        
        while True:
            if default:
                prompt_text = f"{prompt} [{default}]: "
            else:
                prompt_text = f"{prompt}: "
            
            try:
                if password:
                    value = getpass.getpass(prompt_text)
                else:
                    value = input(prompt_text)
                
                if not value and default:
                    value = default
                
                if validate_func and not validate_func(value):
                    print("Invalid input. Please try again.")
                    continue
                
                return value
            except (EOFError, KeyboardInterrupt):
                print("\nInput interrupted. Exiting.")
                sys.exit(1)

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
        success, output = self.run_apt_command("apt-get update -y", timeout=300)
        if not success:
            print(f"Failed to update package index: {output}")
            return False
        
        # Skip apt upgrade if configured
        if not self.skip_upgrade:
            print("Upgrading system packages (this may take a while)...")
            success, output = self.run_apt_command("DEBIAN_FRONTEND=noninteractive apt-get upgrade -y -q", timeout=600)
            if not success:
                print(f"Warning: System upgrade failed: {output}")
                print("Continuing with installation...")
        else:
            print("Skipping system upgrade...")
        
        # First, let's wait for any ongoing apt/dpkg processes to finish
        print("Waiting for any ongoing apt/dpkg processes to finish...")
        self.run_command("ps aux | grep -E 'apt|dpkg' | grep -v grep || true", shell=True)
        
        # Try to fix any interrupted dpkg installations
        print("Attempting to fix any interrupted dpkg installations...")
        self.run_apt_command("DEBIAN_FRONTEND=noninteractive dpkg --configure -a", timeout=300)
        
        # Install required packages
        packages = [
            "apt-transport-https", 
            "ca-certificates", 
            "curl", 
            "software-properties-common",
            "gnupg",
            "lsb-release"
        ]
        
        # Install one package at a time to minimize lock issues
        for package in packages:
            print(f"Installing {package}...")
            success, output = self.run_apt_command(f"DEBIAN_FRONTEND=noninteractive apt-get install -y {package}", timeout=300)
            if not success:
                print(f"Failed to install {package}: {output}")
                return False
        
        # Set up Docker repository
        print("Setting up Docker repository...")
        commands = [
            "mkdir -p /etc/apt/keyrings",
            "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg",
            'echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null',
        ]
        
        for cmd in commands:
            success, output = self.run_command(cmd, shell=True, timeout=300)
            if not success:
                print(f"Failed to execute: {cmd}")
                print(f"Error: {output}")
                return False
        
        # Update package index again after adding Docker repository
        print("Updating package index with Docker repository...")
        success, output = self.run_apt_command("apt-get update -y", timeout=300)
        if not success:
            print(f"Failed to update package index with Docker repository: {output}")
            return False
        
        # Install Docker packages
        docker_packages = [
            "docker-ce",
            "docker-ce-cli", 
            "containerd.io", 
            "docker-buildx-plugin", 
            "docker-compose-plugin"
        ]
        
        for package in docker_packages:
            print(f"Installing {package}...")
            success, output = self.run_apt_command(f"DEBIAN_FRONTEND=noninteractive apt-get install -y {package}", timeout=300)
            if not success:
                print(f"Failed to install {package}: {output}")
                return False
        
        # Install Nginx and Certbot
        print("Installing Nginx and Certbot...")
        success, output = self.run_apt_command("DEBIAN_FRONTEND=noninteractive apt-get install -y nginx certbot python3-certbot-nginx", timeout=300)
        if not success:
            print(f"Failed to install Nginx and Certbot: {output}")
            return False
                
        print("✓ Dependencies installed successfully")
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
DB_NAME={self.db_name}
DB_USER={self.db_user}
DB_PASSWORD={self.db_password}
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
      - POSTGRES_USER={self.db_user}
      - POSTGRES_PASSWORD={self.db_password}
      - POSTGRES_DB={self.db_name}
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

from django.contrib.auth.models import User

username = '{self.admin_username}'
password = '{self.admin_password}'
email = '{self.email}'

if User.objects.filter(username=username).exists():
    print(f"User {{username}} already exists.")
else:
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f"Superuser {{username}} created successfully.")
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
            return False
        
        # Collect static files
        print("Collecting static files...")
        success, output = self.run_command(
            "docker compose exec web python manage.py collectstatic --noinput",
            shell=True,
            cwd=self.install_dir
        )
        
        if not success:
            print(f"Failed to collect static files: {output}")
            return False
        
        print("✓ Application initialized successfully")
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
            self.initialize_application
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
    """Main entry point for the installer."""
    parser = argparse.ArgumentParser(description="Horilla HRMS Installer")
    
    # Required parameters (with defaults for non-interactive mode)
    parser.add_argument("--domain", help="Domain name for Horilla HRMS")
    parser.add_argument("--email", help="Email address for SSL certificates")
    parser.add_argument("--admin-username", help="Admin username")
    parser.add_argument("--admin-password", help="Admin password")
    
    # Optional parameters
    parser.add_argument("--install-dir", default="/root/horilla", help="Installation directory")
    parser.add_argument("--db-name", default="horilla", help="Database name")
    parser.add_argument("--db-user", default="horilla", help="Database username")
    parser.add_argument("--db-password", default="horilla", help="Database password")
    parser.add_argument("--non-interactive", action="store_true", help="Run in non-interactive mode")
    parser.add_argument("--force-continue", action="store_true", help="Continue installation even if apt is locked")
    parser.add_argument("--skip-upgrade", action="store_true", help="Skip system upgrade")
    
    args = parser.parse_args()
    
    # Check if running in non-interactive mode
    is_tty = sys.stdin.isatty()
    if not is_tty and not args.non_interactive:
        print("Detected non-interactive environment. Enabling force-continue mode automatically.")
        args.non_interactive = True
        args.force_continue = True
    
    # Create and run the installer
    installer = HorillaInstaller(
        domain=args.domain,
        email=args.email,
        admin_username=args.admin_username,
        admin_password=args.admin_password,
        install_dir=args.install_dir,
        db_name=args.db_name,
        db_user=args.db_user,
        db_password=args.db_password,
        non_interactive=args.non_interactive,
        force_continue=args.force_continue,
        skip_upgrade=args.skip_upgrade,
        is_tty=is_tty
    )
    
    success = installer.run()
    
    if success:
        print("\n============================================================")
        print("🎉 Horilla HRMS installed successfully! 🎉")
        print("============================================================")
        print(f"You can access your Horilla HRMS instance at: http://{installer.domain}")
        if not installer.domain.endswith('.nip.io'):
            print(f"or with HTTPS at: https://{installer.domain}")
        print("\nAdmin credentials:")
        print(f"  Username: {installer.admin_username}")
        print(f"  Password: {installer.admin_password}")
        print("\nIMPORTANT: For security reasons, please change the admin password after first login.")
        print("============================================================")
        return 0
    else:
        print("\n❌ Installation failed.")
        print("Please check the error messages above and try again.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
