import os
import re
import logging
from typing import Dict, Optional

# Configure a logger for this module
logger = logging.getLogger(__name__)


def _generate_gemini_prompt(
    dog_info: Dict, breed_analysis: Optional[str] = None
) -> str:
    """Generate the prompt for Gemini using user's preferences from prompt.txt."""
    try:
        with open("prompt.txt", "r", encoding="utf-8") as f:
            prompt_template = f.read()
    except FileNotFoundError:
        logger.error("prompt.txt not found. Using default prompt.")
        description = dog_info.get("full_description", "N/A")
        description = description[:1500]  # Truncate

        breed_text = ""
        if breed_analysis:
            breed_text = f"An AI image analysis suggests the following about the breed: '{breed_analysis}'. Please take this into account."

        return f"""
        Evaluate the dog's suitability for apartment living with a cat based *only* on the text below.
        Description: {description}
        {breed_text}
        On a scale of 0 to 100, where 100 is a perfect match, how suitable is this dog for a small apartment with a resident cat?
        Provide only the integer score, without any extra text or explanation.
        """

    dog_name = dog_info.get("name", "Unknown")
    description = dog_info.get("full_description", "N/A")
    description = description[:2000]  # Truncate

    if breed_analysis:
        description += f"\n\nAdditional breed analysis: {breed_analysis}"

    prompt = prompt_template.replace("{dog_name}", dog_name)
    prompt = prompt.replace("{raw_text}", description)
    return prompt


def score_dog_with_gemini(dog_info: Dict, breed_analysis: Optional[str] = None) -> Dict:
    """Score a dog's suitability for apartment living with a cat using Gemini."""
    try:
        import google.generativeai as genai

        api_key = os.environ.get("API_KEY")
        if not api_key:
            logger.error("API_KEY environment variable not set.")
            return {"score": 0, "score_details": ["Missing API Key"]}

        genai.configure(api_key=api_key)

        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = _generate_gemini_prompt(dog_info, breed_analysis)
        if not prompt:
            return {"score": -1, "score_details": ["Prompt generation failed"]}

        response = model.generate_content(prompt)
        score_text = response.text.strip()
        score_match = re.search(r"\d+", score_text)

        if score_match:
            score = int(score_match.group())
        else:
            logger.warning(f"Could not parse score from Gemini response: {score_text}")
            score = 0

        dog_info["score"] = score
        dog_info["score_details"] = [f"Gemini Score: {score}/100"]
        return dog_info
    except Exception as e:
        logger.error(f"Error scoring dog '{dog_info.get('name')}' with Gemini: {e}")
        return {
            "score": -1,
            "score_details": ["Error scoring with Gemini"],
        }
