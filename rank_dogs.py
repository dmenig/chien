#!/usr/bin/env python3
"""
Rank dogs by suitability for low-maintenance apartment living
Based on ChatGPT criteria: large size, calm temperament, minimal exercise needs
"""

import json
import re
from typing import Dict, List, Tuple


def analyze_dog_suitability(dog: Dict) -> Tuple[int, str]:
    """
    Analyze a dog's suitability for low-maintenance apartment living.
    Returns (score, explanation) where higher score = better match
    """
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


def main():
    """Analyze and rank the latest dog data."""
    # Find the most recent dog data file
    import os
    import glob

    data_files = glob.glob("dog_data/dogs_*.json")
    if not data_files:
        print("No dog data files found!")
        return

    latest_file = max(data_files, key=os.path.getctime)
    print(f"📊 Analyzing dogs from: {latest_file}")
    print("=" * 80)

    with open(latest_file, "r", encoding="utf-8") as f:
        dogs = json.load(f)

    # Analyze each dog
    scored_dogs = []
    for dog in dogs:
        score, explanation = analyze_dog_suitability(dog)
        scored_dogs.append((score, dog, explanation))

    # Sort by score (highest first)
    scored_dogs.sort(key=lambda x: x[0], reverse=True)

    print(f"🏆 **RANKING FOR LOW-MAINTENANCE APARTMENT LIVING**")
    print(f"📋 Criteria: Large size + Calm temperament + Minimal exercise needs")
    print("=" * 80)

    for rank, (score, dog, explanation) in enumerate(scored_dogs, 1):
        age = dog.get("age", "Unknown")
        location = (
            dog.get("location", "").split("\n")[0] if dog.get("location") else "Unknown"
        )

        print(f"\n🏅 **#{rank}. {dog['name']}** (Score: {score}/100)")
        print(f"   📍 {location}")
        print(f"   🎂 Age: {age}")
        print(f"   📊 Analysis: {explanation}")

        # Show key description snippets
        full_desc = dog.get("full_description", "")
        if len(full_desc) > 200:
            # Find the most relevant sentence about temperament
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
                print(f'   💬 Key info: "{best_sentence}"')

        if rank <= 3:  # Show adoption details for top 3
            detail_url = dog.get("detail_url", "")
            if detail_url:
                print(f"   🔗 Details: {detail_url}")

    print("\n" + "=" * 80)
    print("🎯 **RECOMMENDATION:**")

    if scored_dogs:
        best_dog = scored_dogs[0][1]
        best_score = scored_dogs[0][0]

        if best_score >= 60:
            print(
                f"✅ **{best_dog['name']}** is an excellent match for your lifestyle!"
            )
        elif best_score >= 40:
            print(f"⚠️ **{best_dog['name']}** could work but may need some compromise")
        else:
            print(f"❌ Current options may not be ideal - wait for better matches")

        print(
            f"\n🔄 The bot runs daily and will find Greyhounds/Mastiffs when available!"
        )


if __name__ == "__main__":
    main()
