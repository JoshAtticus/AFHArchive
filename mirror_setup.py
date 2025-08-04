#!/usr/bin/env python3
"""
AFHArchive Mirror Setup Script
This script helps set up a mirror server for AFHArchive
"""

import os
import sys
import subprocess
from pathlib import Path

def check_python_version():
    """Check if Python version is 3.8+"""
    if sys.version_info < (3, 8):
        print("Error: Python 3.8 or higher is required")
        return False
    print(f"✓ Python {sys.version.split()[0]} detected")
    return True

def install_dependencies():
    """Install Python dependencies"""
    try:
        print("Installing dependencies...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'flask', 'requests', 'python-decouple'])
        print("✓ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError:
        print("Error: Failed to install dependencies")
        return False

def create_env_file():
    """Create .env file for mirror configuration"""
    env_content = '''# AFHArchive Mirror Configuration

# Main server URL (change this to your main server URL)
MAIN_SERVER_URL=https://afharchive.xyz

# Mirror identification
MIRROR_NAME=My Mirror Server
MIRROR_PORT=5000

# Storage configuration
STORAGE_PATH=mirror_uploads
MAX_FILES=1000

# Optional: Custom storage path (for VM mirrors with block storage)
# STORAGE_PATH=/mnt/mirror-storage

# Advanced configuration (usually don't need to change)
# MIRROR_LOG_LEVEL=INFO
'''
    
    env_file = Path('.env')
    if env_file.exists():
        overwrite = input(".env file already exists. Overwrite? (y/N): ")
        if overwrite.lower() != 'y':
            print("Keeping existing .env file")
            return True
    
    with open(env_file, 'w') as f:
        f.write(env_content)
    
    print("✓ Created .env file with default configuration")
    return True

def create_service_file():
    """Create systemd service file for automatic startup"""
    script_path = os.path.abspath('mirror.py')
    service_content = f'''[Unit]
Description=AFHArchive Mirror Server
After=network.target

[Service]
Type=simple
User=afharchive
WorkingDirectory={os.path.dirname(script_path)}
Environment=PATH={os.path.dirname(sys.executable)}
ExecStart={sys.executable} {script_path}
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
'''
    
    service_file = Path('afharchive-mirror.service')
    with open(service_file, 'w') as f:
        f.write(service_content)
    
    print(f"✓ Created systemd service file: {service_file}")
    print("\nTo install the service:")
    print(f"sudo cp {service_file} /etc/systemd/system/")
    print("sudo systemctl daemon-reload")
    print("sudo systemctl enable afharchive-mirror")
    print("sudo systemctl start afharchive-mirror")
    
    return True

def create_directories():
    """Create necessary directories"""
    dirs = ['mirror_uploads', 'logs']
    for dir_name in dirs:
        Path(dir_name).mkdir(exist_ok=True)
        print(f"✓ Created directory: {dir_name}")

def print_next_steps():
    """Print instructions for next steps"""
    print("\n" + "=" * 50)
    print("✅ Mirror setup completed successfully!")
    print("\nNext steps:")
    print("1. Edit .env to configure your mirror server")
    print("2. Get a pairing code from your main server admin")
    print("3. Start the mirror server:")
    print("   python mirror.py")
    print("4. Use the pairing endpoint to connect:")
    print("   curl -X POST http://localhost:5000/pair \\")
    print("     -H 'Content-Type: application/json' \\")
    print("     -d '{\"pairing_code\":\"YOUR_CODE\",\"direct_url\":\"your-server.com:5000\"}'")
    print("\nFor production deployment:")
    print("- Install the systemd service (instructions above)")
    print("- Configure your firewall to allow port 5000")
    print("- Set up a reverse proxy (nginx recommended)")
    print("- Configure Cloudflare Tunnel for public access")

def main():
    """Main setup function"""
    print("🚀 AFHArchive Mirror Setup Script")
    print("=" * 40)
    
    # Check Python version
    if not check_python_version():
        return False
    
    # Install dependencies
    if not install_dependencies():
        return False
    
    # Create configuration
    if not create_env_file():
        return False
    
    # Create directories
    create_directories()
    
    # Create service file
    create_service_file()
    
    # Print next steps
    print_next_steps()
    
    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
