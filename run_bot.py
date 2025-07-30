#!/usr/bin/env python3
"""
Runner script for Dog Adoption Bot
"""

import subprocess
import sys
import os

def main():
    """Run the bot using the virtual environment."""
    if not os.path.exists("env"):
        print("Virtual environment not found. Please run setup.py first:")
        print("  python3 setup.py")
        sys.exit(1)
    
    # Run the bot using the virtual environment
    try:
        subprocess.run([
            "env/bin/python", 
            "dog_adoption_bot.py"
        ], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running bot: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nBot stopped by user")

if __name__ == "__main__":
    main() 