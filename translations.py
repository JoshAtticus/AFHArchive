#!/usr/bin/env python3
"""
Translation management script for AFHArchive
"""
import os
import sys
import subprocess
from pathlib import Path

# Use the correct Python executable for this system
PYTHON_EXE = "C:/Users/josha/AppData/Local/Microsoft/WindowsApps/python3.13.exe"

def run_command(cmd, cwd=None):
    """Run a command and return the result"""
    try:
        result = subprocess.run(cmd, shell=True, cwd=cwd, 
                              capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {cmd}")
        print(f"Error: {e.stderr}")
        return None

def extract_messages():
    """Extract messages from Python files and templates"""
    print("Extracting messages...")
    
    # Create messages.pot file
    cmd = f"{PYTHON_EXE} -m babel.messages.frontend extract -F babel.cfg -k _ -o app/translations/messages.pot ."
    result = run_command(cmd)
    
    if result is not None:
        print("Messages extracted successfully to app/translations/messages.pot")
    else:
        print("Failed to extract messages")

def init_language(lang_code):
    """Initialize a new language"""
    print(f"Initializing language: {lang_code}")
    
    cmd = f"{PYTHON_EXE} -m babel.messages.frontend init -i app/translations/messages.pot -d app/translations -l {lang_code}"
    result = run_command(cmd)
    
    if result is not None:
        print(f"Language {lang_code} initialized successfully")
        print(f"Edit app/translations/{lang_code}/LC_MESSAGES/messages.po to add translations")
    else:
        print(f"Failed to initialize language {lang_code}")

def update_translations():
    """Update existing translations"""
    print("Updating translations...")
    
    cmd = f"{PYTHON_EXE} -m babel.messages.frontend update -i app/translations/messages.pot -d app/translations"
    result = run_command(cmd)
    
    if result is not None:
        print("Translations updated successfully")
    else:
        print("Failed to update translations")

def compile_translations():
    """Compile all translations"""
    print("Compiling translations...")
    
    cmd = f"{PYTHON_EXE} -m babel.messages.frontend compile -d app/translations"
    result = run_command(cmd)
    
    if result is not None:
        print("Translations compiled successfully")
    else:
        print("Failed to compile translations")

def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python translations.py extract      - Extract messages from code")
        print("  python translations.py init <lang>  - Initialize new language")
        print("  python translations.py update       - Update existing translations")
        print("  python translations.py compile      - Compile translations")
        return
    
    command = sys.argv[1]
    
    if command == "extract":
        extract_messages()
    elif command == "init" and len(sys.argv) == 3:
        init_language(sys.argv[2])
    elif command == "update":
        update_translations()
    elif command == "compile":
        compile_translations()
    else:
        print("Invalid command or missing parameters")

if __name__ == "__main__":
    main()
