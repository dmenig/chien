import logging
import os
import re
import json
import time
import hashlib
import threading
from collections import defaultdict
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
        # Simple JSON file cache for descriptions and scores
        self.cache_file = os.path.join(self.data_dir, "cache.json")
        self.cache_lock = threading.Lock()
        self.cache = self._load_cache()
        # Stats for cache usage per source
        self.cache_stats = {}
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

    # ---------------
    # Cache utilities
    # ---------------
    def _load_cache(self) -> Dict:
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # shape: {"descriptions": {url: {"text": str, "updated_at": ts}},
                    #         "scores": {url: {prompt_hash: {"score": int, "score_details": [str], "updated_at": ts}}}}
                    if "descriptions" not in data:
                        data["descriptions"] = {}
                    if "scores" not in data:
                        data["scores"] = {}
                    return data
            except Exception as e:
                self.logger.warning(
                    f"Failed to load cache file: {e}. A new cache will be created."
                )
        return {"descriptions": {}, "scores": {}}

    def _save_cache(self) -> None:
        try:
            with self.cache_lock:
                tmp_path = self.cache_file + ".tmp"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(self.cache, f, ensure_ascii=False, indent=2)
                os.replace(tmp_path, self.cache_file)
        except Exception as e:
            self.logger.warning(f"Failed to save cache file: {e}")

    def _compute_prompt_hash(self) -> str:
        try:
            with open("prompt.txt", "rb") as f:
                content = f.read()
        except FileNotFoundError:
            # mirror default prompt template used in _generate_gemini_prompt
            default_template = (
                "Evaluate the dog's suitability for apartment living with a cat based *only* on the text below.\n"
            ).encode("utf-8")
            content = default_template
        return hashlib.md5(content).hexdigest()

    def get_cached_description(self, detail_url: str) -> str:
        if not detail_url:
            return ""
        with self.cache_lock:
            entry = self.cache.get("descriptions", {}).get(detail_url)
            return entry.get("text", "") if entry else ""

    def set_cached_description(
        self, detail_url: str, text: str, name: Optional[str] = None
    ) -> None:
        if not detail_url or not text:
            return
        with self.cache_lock:
            entry = {
                "text": text,
                "updated_at": int(time.time()),
            }
            if name:
                entry["name"] = name
            self.cache.setdefault("descriptions", {})[detail_url] = entry
        self._save_cache()

    def get_cached_name(self, detail_url: str) -> str:
        if not detail_url:
            return ""
        with self.cache_lock:
            entry = self.cache.get("descriptions", {}).get(detail_url)
            return entry.get("name", "") if entry else ""

    def get_cached_score(self, detail_url: str, prompt_hash: str) -> Optional[Dict]:
        if not detail_url or not prompt_hash:
            return None
        with self.cache_lock:
            by_url = self.cache.get("scores", {}).get(detail_url)
            if not by_url:
                return None
            return by_url.get(prompt_hash)

    # ---------------
    # Cache stats utilities
    # ---------------
    def stats_reset(self) -> None:
        self.cache_stats = {}

    def stats_inc(self, source: str, cached: bool) -> None:
        if not source:
            source = "unknown"
        entry = self.cache_stats.setdefault(source, {"cached": 0, "fetched": 0})
        if cached:
            entry["cached"] += 1
        else:
            entry["fetched"] += 1

    def print_cache_stats(self) -> None:
        if not self.cache_stats:
            print("No cache stats available")
            return
        print("\nCache usage per site:")
        for site, counts in self.cache_stats.items():
            total = counts.get("cached", 0) + counts.get("fetched", 0)
            print(
                f" - {site}: total={total}, from_cache={counts.get('cached', 0)}, fetched={counts.get('fetched', 0)}"
            )

    def set_cached_score(
        self, detail_url: str, prompt_hash: str, score: int, score_details: List[str]
    ) -> None:
        if not detail_url or not prompt_hash:
            return
        with self.cache_lock:
            self.cache.setdefault("scores", {}).setdefault(detail_url, {})[
                prompt_hash
            ] = {
                "score": int(score),
                "score_details": list(score_details),
                "updated_at": int(time.time()),
            }
        self._save_cache()

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
            detail_url = dog_info.get("detail_url", "")
            full_desc = dog_info.get("full_description") or self.get_cached_description(
                detail_url
            )
            if full_desc:
                # ensure cache has it for next runs
                self.set_cached_description(detail_url, full_desc)
            else:
                # Try to fetch description if we have a URL
                if detail_url:
                    full_desc = self.get_full_description(detail_url)
                    if full_desc:
                        dog_info["full_description"] = full_desc
                        self.set_cached_description(detail_url, full_desc)
                # If still missing, skip Gemini
                if not full_desc:
                    self.logger.info(
                        f"Skipping Gemini for {dog_info.get('name', 'Unknown')} due to missing description"
                    )
                    return {"score": -1, "score_details": ["Missing description"]}

            prompt_hash = self._compute_prompt_hash()
            cached = self.get_cached_score(detail_url, prompt_hash)
            if cached is not None:
                return {
                    "score": cached["score"],
                    "score_details": cached["score_details"],
                }
            # If we have a cached description but no cached score for this prompt, warn
            try:
                if detail_url and self.get_cached_description(detail_url):
                    self.logger.warning(
                        f"Cached description found for {detail_url} but no cached score for current prompt (hash={prompt_hash}). Gemini will be called."
                    )
            except Exception:
                pass

            result = self._call_gemini_api(dog_info, breed_analysis)
            if isinstance(result, dict) and "score" in result:
                self.set_cached_score(
                    detail_url,
                    prompt_hash,
                    result.get("score", 0),
                    result.get("score_details", []),
                )
            return result
        except Exception as e:
            self.logger.error(
                f"Error scoring dog '{dog_info.get('name')}' with Gemini: {e}"
            )
            return {"score": -1, "score_details": ["Error scoring with Gemini"]}

    def _call_gemini_api(
        self, dog_info: Dict, breed_analysis: Optional[str] = None
    ) -> Dict:
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
        score = self._parse_gemini_score(
            response.text if hasattr(response, "text") else str(response)
        )
        dog_info["score"] = score
        dog_info["score_details"] = [f"Gemini Score: {score}/100"]
        return dog_info

    def _parse_gemini_score(self, score_text: str) -> int:
        score_text = score_text.strip()
        score_match = re.search(r"\d+", score_text)
        if score_match:
            try:
                return int(score_match.group())
            except ValueError:
                return 0
        self.logger.warning(f"Could not parse score from Gemini response: {score_text}")
        return 0

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
            # Avoid re-downloading if already cached successfully
            cached = self.get_cached_description(detail_url)
            if cached:
                return cached

            soup = self.get_page(detail_url)
            if not soup:
                return ""
            full_desc = ""
            full_desc += self._extract_section_text(soup, "Présentation")
            full_desc += self._extract_section_text(
                soup, "Particularités", prefix="PARTICULARITÉ: "
            )
            if not full_desc:
                paragraphs = soup.find_all("p")
                for p in paragraphs:
                    text = p.get_text().strip()
                    if len(text) > 50:
                        full_desc += text + "\n\n"
            full_desc = full_desc.strip()
            if full_desc:
                self.set_cached_description(detail_url, full_desc)
            return full_desc
        except Exception as e:
            self.logger.warning(
                f"Error getting full description from {detail_url}: {e}"
            )
            return ""

    def _extract_section_text(self, soup, header_text: str, prefix: str = "") -> str:
        text_accum = ""
        section = soup.find("h3", string=header_text)
        if not section:
            return text_accum
        next_elem = section.find_next_sibling()
        while next_elem and next_elem.name != "h3":
            if next_elem.name in ["p", "div", "ul", "li"]:
                txt = next_elem.get_text().strip()
                if txt and len(txt) > (2 if prefix else 10):
                    text_accum += f"{prefix}{txt}\n\n"
            next_elem = next_elem.find_next_sibling()
        return text_accum

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
            largest_image = self._find_largest_image(soup)
            if largest_image:
                image_url = urljoin(detail_url, largest_image)
                self.logger.info(f"Found largest image via fallback: {image_url}")
                return image_url
            self.logger.warning(f"Could not find a suitable image on {detail_url}")
            return None
        except Exception as e:
            self.logger.warning(f"Error scraping image from {detail_url}: {e}")
            return None

    def _find_largest_image(self, soup):
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
        return largest_image

    def get_page_with_selenium(self, url: str) -> str:
        """Render a page using Selenium and return page source (keeps previous behavior)."""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            import time

            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            try:
                self.logger.info(f"Loading page with selenium: {url}")
                driver.get(url)
                time.sleep(3)
                last_height = driver.execute_script("return document.body.scrollHeight")
                scroll_count = 0
                while True:
                    driver.execute_script(
                        "window.scrollTo(0, document.body.scrollHeight);"
                    )
                    time.sleep(2)
                    new_height = driver.execute_script(
                        "return document.body.scrollHeight"
                    )
                    if new_height == last_height or scroll_count > 10:
                        break
                    last_height = new_height
                    scroll_count += 1
                time.sleep(2)
                return driver.page_source
            finally:
                driver.quit()
        except Exception as e:
            self.logger.error(f"Selenium rendering failed for {url}: {e}")
            return ""
