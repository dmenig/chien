#!/usr/bin/env python3
"""
Setup script for Dog Adoption Bot
"""

import subprocess
import sys
import os

def run_command(command, description):
    """Run a command and handle errors."""
    print(f"Running: {description}")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        print(f"✓ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ {description} failed: {e}")
        if e.stdout:
            print(f"STDOUT: {e.stdout}")
        if e.stderr:
            print(f"STDERR: {e.stderr}")
        return False

def main():
    """Main setup function."""
    print("Setting up Dog Adoption Bot...")
    
    # Create virtual environment
    if not os.path.exists("env"):
        if not run_command("python3 -m venv env", "Creating virtual environment"):
            sys.exit(1)
    else:
        print("✓ Virtual environment already exists")
    
    # Install dependencies
    if not run_command("env/bin/pip install -r requirements.txt", "Installing dependencies"):
        sys.exit(1)
    
    print("\n✓ Setup complete!")
    print("To run the bot:")
    print("  ./run_bot.py")
    print("Or activate the virtual environment first:")
    print("  source env/bin/activate")
    print("  python dog_adoption_bot.py")

if __name__ == "__main__":
    main() 