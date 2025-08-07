import json
import os
from datetime import datetime
from typing import List, Dict


def save_data(data: List[Dict], source: str):
    """Save data to a JSON file in the dog_data directory."""
    if not data:
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"dog_data/dogs_{source}_{timestamp}.json"

    os.makedirs(os.path.dirname(filename), exist_ok=True)

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"Data saved to {filename}")
