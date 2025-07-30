#!/usr/bin/env python3
"""
Enable daily scheduling for the Dog Adoption Bot
"""

import re

def enable_daily_schedule():
    """Enable daily scheduling in the bot."""
    
    # Read the bot file
    with open('dog_adoption_bot.py', 'r') as f:
        content = f.read()
    
    # Replace the commented scheduler line
    content = re.sub(
        r'# bot\.start_scheduler\(\)',
        'bot.start_scheduler()',
        content
    )
    
    # Write back to the file
    with open('dog_adoption_bot.py', 'w') as f:
        f.write(content)
    
    print("✓ Daily scheduling enabled!")
    print("The bot will now run daily at 09:00 AM")
    print("Run './run_bot.py' to start the scheduled bot")

if __name__ == "__main__":
    enable_daily_schedule() 