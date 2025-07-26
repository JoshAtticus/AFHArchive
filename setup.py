#!/usr/bin/env python3
"""
AFHArchive Setup Script
This script helps set up the AFHArchive application
"""

import os
import secrets
import subprocess
import sys
from pathlib import Path

def check_python_version():
    """Check if Python version is 3.8+"""
    if sys.version_info < (3, 8):
        print("Error: Python 3.8 or higher is required")
        sys.exit(1)
    print(f"✓ Python {sys.version_info.major}.{sys.version_info.minor} detected")

def create_env_file():
    """Create .env file from .env.example"""
    env_example = Path('.env.example')
    env_file = Path('.env')
    
    if not env_example.exists():
        print("Error: .env.example not found")
        return False
    
    if env_file.exists():
        overwrite = input(".env file already exists. Overwrite? (y/N): ")
        if overwrite.lower() != 'y':
            print("Keeping existing .env file")
            return True
    
    # Read .env.example
    with open(env_example, 'r') as f:
        content = f.read()
    
    # Generate secret key
    secret_key = secrets.token_urlsafe(32)
    content = content.replace('your-secret-key-here', secret_key)
    
    # Write .env
    with open(env_file, 'w') as f:
        f.write(content)
    
    print("✓ Created .env file with generated secret key")
    print("⚠️  Please configure Google OAuth2 credentials in .env")
    return True

def install_dependencies():
    """Install Python dependencies"""
    try:
        print("Installing dependencies...")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt'])
        print("✓ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError:
        print("Error: Failed to install dependencies")
        return False

def create_upload_directory():
    """Create upload directory"""
    upload_dir = Path('uploads')
    upload_dir.mkdir(exist_ok=True)
    print(f"✓ Created upload directory: {upload_dir.absolute()}")

def initialize_database():
    """Initialize the database"""
    try:
        print("Initializing database...")
        subprocess.check_call([sys.executable, 'run.py', 'init-db'])
        print("✓ Database initialized successfully")
        return True
    except subprocess.CalledProcessError:
        print("Error: Failed to initialize database")
        return False

def main():
    """Main setup function"""
    print("🚀 AFHArchive Setup Script")
    print("=" * 40)
    
    # Check Python version
    check_python_version()
    
    # Install dependencies
    if not install_dependencies():
        return False
    
    # Create .env file
    if not create_env_file():
        return False
    
    # Create upload directory
    create_upload_directory()
    
    # Initialize database
    if not initialize_database():
        return False
    
    print("\n" + "=" * 40)
    print("✅ Setup completed successfully!")
    print("\nNext steps:")
    print("1. Configure Google OAuth2 credentials in .env")
    print("2. Update ADMIN_EMAILS in .env")
    print("3. Run: python run.py")
    print("\nFor Google OAuth2 setup, visit:")
    print("https://console.cloud.google.com/")
    
    return True

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
