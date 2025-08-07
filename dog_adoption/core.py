import logging
import os
import re
import json
import time
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup


class CoreMixin:
    def __init__(self, base_url: str = "https://www.secondechance.org"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
        )
        self.setup_logging()
        self.data_dir = "dog_data"
        self.ensure_data_directory()
        self.search_regions = ["2", "3", "4", "5"]
        self.paris_departments = [
            "41",
            "42",
            "43",
            "44",
            "45",
            "46",
            "47",
            "48",
        ]

    def setup_logging(self):
        log_file = "dog_bot.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
        )
        self.logger = logging.getLogger(__name__)

    def ensure_data_directory(self):
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            self.logger.info(f"Created data directory: {self.data_dir}")

    def get_page(self, url: str, retries: int = 3) -> Optional[BeautifulSoup]:
        for attempt in range(retries):
            try:
                response = self.session.get(url, timeout=30)
                response.raise_for_status()
                return BeautifulSoup(response.content, "lxml")
            except requests.exceptions.ConnectionError as e:
                self.logger.error(f"Connection refused for {url}: {e}")
                return None
            except requests.RequestException as e:
                self.logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                if attempt < retries - 1:
                    time.sleep(2**attempt)
                else:
                    self.logger.error(f"Failed to fetch {url} after {retries} attempts")
                    return None

    def save_data(self, dogs: List[Dict]):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_filename = f"{self.data_dir}/dogs_{timestamp}.json"
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump(dogs, f, ensure_ascii=False, indent=2)
        if dogs:
            csv_filename = f"{self.data_dir}/dogs_{timestamp}.csv"
            df = pd.DataFrame(dogs)
            df.to_csv(csv_filename, index=False, encoding="utf-8")
        self.logger.info(
            f"Data saved to {json_filename} and {csv_filename if dogs else 'CSV not created (no data)'}"
        )

    def _generate_gemini_prompt(
        self, dog_info: Dict, breed_analysis: Optional[str] = None
    ) -> str:
        try:
            with open("prompt.txt", "r", encoding="utf-8") as f:
                prompt_template = f.read()
        except FileNotFoundError:
            self.logger.error("prompt.txt not found. Using default prompt.")
            description = dog_info.get("full_description", "N/A")
            description = description[:1500]
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
        description = description[:2000]
        if breed_analysis:
            description += f"\n\nAdditional breed analysis: {breed_analysis}"
        prompt = prompt_template.replace("{dog_name}", dog_name)
        prompt = prompt.replace("{raw_text}", description)
        return prompt

    def score_dog_with_gemini(
        self, dog_info: Dict, breed_analysis: Optional[str] = None
    ) -> Dict:
        try:
            import google.generativeai as genai

            api_key = os.environ.get("API_KEY")
            if not api_key:
                self.logger.error("API_KEY environment variable not set.")
                return {"score": 0, "score_details": ["Missing API Key"]}

            genai.configure(api_key=api_key)
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = self._generate_gemini_prompt(dog_info, breed_analysis)
            if not prompt:
                return {"score": -1, "score_details": ["Prompt generation failed"]}
            response = model.generate_content(prompt)
            score_text = response.text.strip()
            score_match = re.search(r"\d+", score_text)
            if score_match:
                score = int(score_match.group())
            else:
                self.logger.warning(
                    f"Could not parse score from Gemini response: {score_text}"
                )
                score = 0
            dog_info["score"] = score
            dog_info["score_details"] = [f"Gemini Score: {score}/100"]
            return dog_info
        except Exception as e:
            self.logger.error(
                f"Error scoring dog '{dog_info.get('name')}' with Gemini: {e}"
            )
            return {"score": -1, "score_details": ["Error scoring with Gemini"]}

    def extract_dog_info(self, dog_element) -> Dict:
        dog_info = {
            "name": "Unknown",
            "detail_url": "",
            "full_description": "",
            "scraped_date": datetime.now().isoformat(),
        }
        try:
            name_elem = dog_element.find("h3", class_="pacifico-regular")
            if name_elem:
                dog_info["name"] = name_elem.get_text(strip=True)
            detail_link = dog_element.find("a", href=True)
            if detail_link:
                dog_info["detail_url"] = urljoin(self.base_url, detail_link["href"])
            dog_info["full_description"] = dog_element.get_text(
                separator="\n", strip=True
            )
        except Exception as e:
            self.logger.warning(f"Error extracting dog info: {e}")
        return dog_info

    def get_full_description(self, detail_url: str) -> str:
        try:
            soup = self.get_page(detail_url)
            if not soup:
                return ""
            full_desc = ""
            presentation_section = soup.find("h3", string="Présentation")
            if presentation_section:
                next_elem = presentation_section.find_next_sibling()
                while next_elem and next_elem.name != "h3":
                    if next_elem.name == "p" or next_elem.name == "div":
                        text = next_elem.get_text().strip()
                        if text and len(text) > 10:
                            full_desc += text + "\n\n"
                    next_elem = next_elem.find_next_sibling()
            particularites_section = soup.find("h3", string="Particularités")
            if particularites_section:
                next_elem = particularites_section.find_next_sibling()
                while next_elem and next_elem.name != "h3":
                    if next_elem.name in ["p", "div", "ul", "li"]:
                        text = next_elem.get_text().strip()
                        if text and len(text) > 2:
                            full_desc += f"PARTICULARITÉ: {text}\n\n"
                    next_elem = next_elem.find_next_sibling()
            if not full_desc:
                paragraphs = soup.find_all("p")
                for p in paragraphs:
                    text = p.get_text().strip()
                    if len(text) > 50:
                        full_desc += text + "\n\n"
            return full_desc.strip()
        except Exception as e:
            self.logger.warning(
                f"Error getting full description from {detail_url}: {e}"
            )
            return ""

    def get_dog_image_url(self, detail_url: str) -> Optional[str]:
        if not detail_url:
            return None
        try:
            soup = self.get_page(detail_url)
            if not soup:
                return None
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                image_url = urljoin(detail_url, og_image["content"])
                self.logger.info(f"Found image via og:image tag: {image_url}")
                return image_url
            parsed_url = urlparse(detail_url)
            if "secondechance.org" in parsed_url.netloc:
                slider_img = soup.select_one(".splide__slide img")
                if slider_img and slider_img.get("src"):
                    image_url = urljoin(detail_url, slider_img["src"])
                    self.logger.info(f"Found secondechance image: {image_url}")
                    return image_url
            if "chiensadonner.com" in parsed_url.netloc:
                main_img = soup.select_one(".single-ad-main-image img")
                if main_img and main_img.get("src"):
                    image_url = urljoin(detail_url, main_img["src"])
                    self.logger.info(f"Found chiensadonner image: {image_url}")
                    return image_url
            largest_image = None
            max_area = 0
            for img in soup.find_all("img"):
                src = img.get("src")
                if (
                    not src
                    or "logo" in src.lower()
                    or "icon" in src.lower()
                    or ".svg" in src.lower()
                ):
                    continue
                try:
                    width = int(img.get("width", 0))
                    height = int(img.get("height", 0))
                    area = width * height
                    if area > max_area:
                        max_area = area
                        largest_image = src
                except (ValueError, TypeError):
                    continue
            if largest_image:
                image_url = urljoin(detail_url, largest_image)
                self.logger.info(f"Found largest image via fallback: {image_url}")
                return image_url
            self.logger.warning(f"Could not find a suitable image on {detail_url}")
            return None
        except Exception as e:
            self.logger.warning(f"Error scraping image from {detail_url}: {e}")
            return None
