#!/usr/bin/env python3
"""
Rank ALL dogs currently available on the site by low-maintenance criteria
"""

import requests
from bs4 import BeautifulSoup
import urllib3
import re
from urllib.parse import urljoin
from typing import Dict, List, Tuple

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_full_description(session, detail_url: str) -> str:
    """Get full description from dog detail page."""
    try:
        response = session.get(detail_url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml")

        # Look for description content
        desc_selectors = [
            'div[class*="description"]',
            'div[class*="content"]',
            'div[class*="details"]',
            ".description",
            ".content",
            ".details",
        ]

        for selector in desc_selectors:
            desc_elem = soup.select_one(selector)
            if desc_elem:
                return desc_elem.get_text().strip()

        # Fallback: look for paragraphs with substantial text
        paragraphs = soup.find_all("p")
        full_desc = ""
        for p in paragraphs:
            text = p.get_text().strip()
            if len(text) > 50:  # Only include substantial paragraphs
                full_desc += text + "\n\n"

        return full_desc.strip()

    except Exception as e:
        print(f"Error getting description from {detail_url}: {e}")
        return ""


def extract_dog_info(session, dog_element) -> Dict:
    """Extract information from a dog listing element."""
    base_url = "https://www.secondechance.org"

    dog_info = {
        "name": "",
        "breed": "",
        "age": "",
        "gender": "",
        "location": "",
        "description": "",
        "full_description": "",
        "size": "",
        "image_url": "",
        "detail_url": "",
    }

    try:
        # Try to find name
        name_elem = dog_element.find("h3", class_="pacifico-regular")
        if not name_elem:
            name_elem = dog_element.find(["h1", "h2", "h3", "h4", "h5"])
        if name_elem:
            dog_info["name"] = name_elem.get_text().strip()

        # Try to find detail URL
        detail_link = dog_element.find("a", href=True)
        if detail_link:
            dog_info["detail_url"] = urljoin(base_url, detail_link["href"])

        # Try to find image
        img_elem = dog_element.find("img")
        if img_elem and img_elem.get("src"):
            dog_info["image_url"] = urljoin(base_url, img_elem["src"])

        # Extract other details from text content
        text_content = dog_element.get_text()

        # Extract breed, age, gender, size, location patterns
        breed_patterns = [
            r"(CHIEN\s+[A-Z\s]+)\s+(?:Mâle|Femelle)",
            r"(BERGER\s+[A-Z\s]+)",
            r"(CHIHUAHUA|LABRADOR|GOLDEN|HUSKY|BULLDOG|BEAGLE|BOXER|PITBULL)",
            r"(CROISE?)\s+(?:MOYEN|GRAND|PETIT)?",
        ]

        for pattern in breed_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                dog_info["breed"] = match.group(1).strip()
                break

        # Size patterns
        size_patterns = [
            r"(GRAND|GRANDE|MOYEN|MOYENNE|PETIT|PETITE)",
            r"(GRAND\s+CHIEN|PETIT\s+CHIEN|CHIEN\s+MOYEN)",
            r"(\d+\s*kg)",
            r"(TRÈS\s+GRAND|TRÈS\s+PETIT)",
        ]

        for pattern in size_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                dog_info["size"] = match.group(1).strip()
                break

        # Age patterns
        age_patterns = [r"(\d+)\s*ans?", r"(\d+)\s*mois"]
        for pattern in age_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                dog_info["age"] = match.group(0)
                break

        # Gender patterns
        gender_patterns = [r"\b(mâle|femelle|male|female)\b"]
        for pattern in gender_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                dog_info["gender"] = match.group(1)
                break

        # Location
        location_elem = dog_element.find("h4", class_="open-sans font-bold")
        if location_elem:
            dog_info["location"] = location_elem.get_text().strip()

        # Description
        desc_elem = dog_element.find("p", class_="open-sans text-sm text-gray-dark-sc")
        if not desc_elem:
            desc_elem = dog_element.find("p")
        if desc_elem:
            dog_info["description"] = desc_elem.get_text().strip()[:500]

        # Get full description
        if dog_info["detail_url"]:
            dog_info["full_description"] = get_full_description(
                session, dog_info["detail_url"]
            )

        return dog_info

    except Exception as e:
        print(f"Error extracting dog info: {e}")
        return dog_info


def analyze_dog_suitability(dog: Dict) -> Tuple[int, str]:
    """Analyze a dog's suitability for low-maintenance apartment living."""
    score = 0
    reasons = []

    # Get all text content
    name = dog.get("name", "")
    breed = dog.get("breed", "").lower()
    age = dog.get("age", "")
    size = dog.get("size", "").lower()
    description = dog.get("description", "").lower()
    full_desc = dog.get("full_description", "").lower()

    all_text = f"{breed} {size} {description} {full_desc}"

    # 1. SIZE CRITERIA (Large dogs preferred) - Max 30 points
    weight_match = re.search(r"(\d+)\s*kg", all_text)
    if weight_match:
        weight = int(weight_match.group(1))
        if weight >= 25:
            score += 25
            reasons.append(f"✅ Large size ({weight}kg)")
        elif weight >= 15:
            score += 15
            reasons.append(f"⚠️ Medium size ({weight}kg)")
        else:
            score += 5
            reasons.append(f"❌ Small size ({weight}kg)")
    elif "grand" in all_text or "gros" in all_text or "large" in all_text:
        score += 20
        reasons.append("✅ Described as large")
    elif "moyen" in all_text or "moyenne" in all_text:
        score += 10
        reasons.append("⚠️ Described as medium")
    elif "petit" in all_text or "petite" in all_text:
        score += 2
        reasons.append("❌ Described as small")
    else:
        score += 5
        reasons.append("❓ Size unclear")

    # 2. TEMPERAMENT CRITERIA (Calm, low-energy) - Max 40 points
    calm_keywords = [
        "calme",
        "tranquille",
        "posé",
        "placide",
        "serein",
        "doux",
        "gentil",
        "paisible",
        "sage",
        "obéissant",
        "réservée",
        "réservé",
        "discret",
        "discrète",
    ]

    energy_keywords = [
        "énergie",
        "énergique",
        "actif",
        "active",
        "joueur",
        "enthousiaste",
        "vif",
        "plein d'énergie",
        "besoin d'espace",
    ]

    calm_count = sum(1 for keyword in calm_keywords if keyword in all_text)
    energy_count = sum(1 for keyword in energy_keywords if keyword in all_text)

    if calm_count >= 3:
        score += 40
        reasons.append("✅ Very calm temperament")
    elif calm_count >= 2:
        score += 30
        reasons.append("✅ Calm temperament")
    elif calm_count >= 1:
        score += 20
        reasons.append("⚠️ Somewhat calm")

    if energy_count >= 3:
        score -= 20
        reasons.append("❌ High energy described")
    elif energy_count >= 2:
        score -= 10
        reasons.append("⚠️ Some energy mentioned")

    # 3. AGE CRITERIA (Older dogs tend to be calmer) - Max 15 points
    age_match = re.search(r"(\d+)\s*ans?", age)
    if age_match:
        age_years = int(age_match.group(1))
        if age_years >= 5:
            score += 15
            reasons.append(f"✅ Mature age ({age_years} ans)")
        elif age_years >= 3:
            score += 10
            reasons.append(f"⚠️ Adult age ({age_years} ans)")
        else:
            score += 5
            reasons.append(f"❌ Young age ({age_years} ans)")
    elif "mois" in age:
        score += 2
        reasons.append("❌ Puppy (high energy)")

    # 4. BREED CRITERIA (Target low-maintenance breeds) - Max 15 points
    low_maintenance_breeds = [
        "lévrier",
        "levrier",
        "greyhound",
        "galgo",
        "whippet",
        "mastiff",
        "mastin",
        "dogue allemand",
        "great dane",
        "cane corso",
        "saint-bernard",
        "terre-neuve",
        "newfoundland",
    ]

    if any(breed_name in all_text for breed_name in low_maintenance_breeds):
        score += 15
        reasons.append("✅ Low-maintenance breed")
    elif "croisé" in all_text or "croise" in all_text:
        score += 8
        reasons.append("⚠️ Mixed breed (potential)")

    # 5. EXERCISE NEEDS (Penalize high exercise needs) - Max penalty -20
    exercise_keywords = [
        "adore les promenades",
        "besoin d'espace",
        "se dépenser",
        "activité",
        "stimulante",
        "équilibrée",
    ]

    exercise_count = sum(1 for keyword in exercise_keywords if keyword in all_text)
    if exercise_count >= 2:
        score -= 15
        reasons.append("❌ High exercise needs")
    elif exercise_count >= 1:
        score -= 8
        reasons.append("⚠️ Some exercise needs")

    return score, " | ".join(reasons)


def get_all_dogs():
    """Fetch all dogs currently available on the site."""
    base_url = "https://www.secondechance.org/animal/adopter-un-chien"

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
    )
    session.verify = False

    # Just get all dogs without filters
    url = base_url + "?species=1"

    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "lxml")

        # Find all dog elements
        elements = soup.select("div.p-6.w-full")

        dogs = []
        for element in elements:
            dog_info = extract_dog_info(session, element)
            if dog_info["name"]:  # Only add if we found a name
                dogs.append(dog_info)

        return dogs

    except Exception as e:
        print(f"Error fetching dogs: {e}")
        return []


def main():
    """Rank all dogs currently available on the site."""
    print("🔍 Fetching ALL dogs from secondechance.org...")
    dogs = get_all_dogs()

    if not dogs:
        print("No dogs found!")
        return

    print(f"Found {len(dogs)} dogs total")
    print("=" * 80)

    # Analyze each dog
    scored_dogs = []
    for dog in dogs:
        score, explanation = analyze_dog_suitability(dog)
        scored_dogs.append((score, dog, explanation))

    # Sort by score (highest first)
    scored_dogs.sort(key=lambda x: x[0], reverse=True)

    print(f"🏆 **ALL {len(dogs)} DOGS RANKED BY LOW-MAINTENANCE CRITERIA**")
    print("=" * 80)

    for rank, (score, dog, explanation) in enumerate(scored_dogs, 1):
        age = dog.get("age", "Unknown")
        location = (
            dog.get("location", "").split("\n")[0] if dog.get("location") else "Unknown"
        )

        # Color coding based on score
        if score >= 60:
            emoji = "🟢"
        elif score >= 40:
            emoji = "🟡"
        else:
            emoji = "🔴"

        print(f"\n{emoji} **#{rank}. {dog['name']}** (Score: {score}/100)")
        print(f"   📍 {location}")
        print(f"   🎂 Age: {age}")
        print(f"   📊 Analysis: {explanation}")

        # Show key description snippets
        full_desc = dog.get("full_description", "")
        if len(full_desc) > 200:
            sentences = full_desc.split(".")
            best_sentence = ""
            for sentence in sentences:
                if any(
                    word in sentence.lower()
                    for word in ["calme", "tranquille", "doux", "gentil", "énergie"]
                ):
                    best_sentence = sentence.strip()
                    break
            if best_sentence:
                print(
                    f'   💬 Key info: "{best_sentence[:100]}{"..." if len(best_sentence) > 100 else ""}"'
                )

        if rank <= 5:  # Show URLs for top 5
            detail_url = dog.get("detail_url", "")
            if detail_url:
                print(f"   🔗 Details: {detail_url}")

    print("\n" + "=" * 80)
    print("🎯 **LEGEND:**")
    print("🟢 Excellent match (60+ points) - Perfect for your lifestyle")
    print("🟡 Good match (40-59 points) - Could work with some compromise")
    print("🔴 Poor match (<40 points) - Likely too demanding")


if __name__ == "__main__":
    main()
