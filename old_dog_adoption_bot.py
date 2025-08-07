import logging
from typing import List, Dict, Optional
from datetime import datetime
import re
from urllib.parse import urljoin, urlparse
import schedule
import requests
from bs4 import BeautifulSoup
import time
import json
import pandas as pd
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


class DogAdoptionBot:
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
        self.search_regions = ["2", "3", "4", "5"]  # Île-de-France, Nord, Est, Sud-Est
        self.paris_departments = [
            "41",
            "42",
            "43",
            "44",
            "45",
            "46",
            "47",
            "48",
        ]  # 75, 77, 78, 91, 92, 93, 94, 95

    def setup_logging(self):
        """Set up logging configuration."""
        log_file = "dog_bot.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
        )
        self.logger = logging.getLogger(__name__)

    def ensure_data_directory(self):
        """Ensure the data directory exists."""
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            self.logger.info(f"Created data directory: {self.data_dir}")

    def get_page(self, url: str, retries: int = 3) -> Optional[BeautifulSoup]:
        """Fetch a page with retry logic."""
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

    def scrape_all_sources(self) -> List[Dict]:
        """Scrape dogs from all configured sources in parallel."""
        all_dogs = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            # Submit scraping tasks
            future_to_source = {
                executor.submit(self.scrape_secondechance): "secondechance",
                executor.submit(self.scrape_chiensadonner): "chiensadonner",
                executor.submit(self.scrape_crocsmignons): "crocsmignons",
                executor.submit(self.scrape_larchedekala): "larchedekala",
                executor.submit(self.scrape_rememberme): "rememberme",
                executor.submit(self.scrape_happydogsforever): "happydogsforever",
            }

            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    dogs = future.result()
                    all_dogs.extend(dogs)
                    self.logger.info(f"Found {len(dogs)} dogs from {source}.org")
                except Exception as exc:
                    self.logger.error(f"{source} generated an exception: {exc}")

        # Deduplicate and sort
        self.logger.info(f"Total dogs scraped from all sources: {len(all_dogs)}")
        unique_dogs = []
        seen_dogs = set()
        for dog in all_dogs:
            # Using name and detail_url for deduplication
            dog_key = (dog.get("name", "").lower(), dog.get("detail_url", ""))
            if dog_key not in seen_dogs:
                seen_dogs.add(dog_key)
                unique_dogs.append(dog)

        # Parallel scoring
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_dog = {
                executor.submit(self.score_dog_with_gemini, dog): dog
                for dog in unique_dogs
            }
            for future in as_completed(future_to_dog):
                dog = future_to_dog[future]
                try:
                    scoring_result = future.result()
                    dog.update(scoring_result)
                except Exception as exc:
                    self.logger.error(
                        f"Dog {dog.get('name')} generated an exception during scoring: {exc}"
                    )
                    dog["score"] = -1
                    dog["score_details"] = ["Scoring failed"]

        unique_dogs.sort(key=lambda x: x.get("score", 0), reverse=True)

        self.logger.info(f"Total unique dogs from all sources: {len(unique_dogs)}")
        return unique_dogs

    def save_data(self, dogs: List[Dict]):
        """Save scraped data to JSON and CSV files."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Save as JSON
        json_filename = f"{self.data_dir}/dogs_{timestamp}.json"
        with open(json_filename, "w", encoding="utf-8") as f:
            json.dump(dogs, f, ensure_ascii=False, indent=2)

        # Save as CSV
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
        """Generate the prompt for Gemini using user's preferences from prompt.txt."""
        # Read the user's prompt template from file
        try:
            with open("prompt.txt", "r", encoding="utf-8") as f:
                prompt_template = f.read()
        except FileNotFoundError:
            self.logger.error("prompt.txt not found. Using default prompt.")
            description = dog_info.get("full_description", "N/A")
            # Truncate to avoid excessive length
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

        # Get dog information
        dog_name = dog_info.get("name", "Unknown")
        description = dog_info.get("full_description", "N/A")

        # Truncate description to avoid excessive length
        description = description[:2000]

        # If there's breed analysis, append it to the description
        if breed_analysis:
            description += f"\n\nAdditional breed analysis: {breed_analysis}"

        # Replace template variables in the prompt
        prompt = prompt_template.replace("{dog_name}", dog_name)
        prompt = prompt.replace("{raw_text}", description)

        return prompt

    def score_dog_with_gemini(
        self, dog_info: Dict, breed_analysis: Optional[str] = None
    ) -> Dict:
        """Score a dog's suitability for apartment living with a cat using Gemini."""
        try:
            import google.generativeai as genai

            # Configure the Gemini API key
            # Make sure to set the API_KEY environment variable
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

            # Extract the score from the response
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
            return {
                "score": -1,  # Use -1 to indicate an error
                "score_details": ["Error scoring with Gemini"],
            }

    def extract_dog_info(self, dog_element) -> Dict:
        """Extracts the raw text content and basic info for a dog listing."""
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

            # Get the raw text content for Gemini
            dog_info["full_description"] = dog_element.get_text(
                separator="\n", strip=True
            )

        except Exception as e:
            self.logger.warning(f"Error extracting dog info: {e}")

        return dog_info

    def get_full_description(self, detail_url: str) -> str:
        """Get full description from dog detail page including Particularités section."""
        try:
            soup = self.get_page(detail_url)
            if not soup:
                return ""

            full_desc = ""

            # Get main presentation/description
            presentation_section = soup.find("h3", string="Présentation")
            if presentation_section:
                # Get the content after the "Présentation" header
                next_elem = presentation_section.find_next_sibling()
                while next_elem and next_elem.name != "h3":
                    if next_elem.name == "p" or next_elem.name == "div":
                        text = next_elem.get_text().strip()
                        if text and len(text) > 10:
                            full_desc += text + "\n\n"
                    next_elem = next_elem.find_next_sibling()

            # Get "Particularités" section - CRITICAL for garden requirements
            particularites_section = soup.find("h3", string="Particularités")
            if particularites_section:
                # Get the content after the "Particularités" header
                next_elem = particularites_section.find_next_sibling()
                while next_elem and next_elem.name != "h3":
                    if next_elem.name in ["p", "div", "ul", "li"]:
                        text = next_elem.get_text().strip()
                        if text and len(text) > 2:
                            full_desc += f"PARTICULARITÉ: {text}\n\n"
                    next_elem = next_elem.find_next_sibling()

            # Look for any other relevant sections
            if not full_desc:
                # Fallback: look for paragraphs with substantial text
                paragraphs = soup.find_all("p")
                for p in paragraphs:
                    text = p.get_text().strip()
                    if len(text) > 50:  # Only include substantial paragraphs
                        full_desc += text + "\n\n"

            return full_desc.strip()

        except Exception as e:
            self.logger.warning(
                f"Error getting full description from {detail_url}: {e}"
            )
            return ""

    def get_dog_image_url(self, detail_url: str) -> Optional[str]:
        """Get the primary image URL from a dog's detail page."""
        if not detail_url:
            return None
        try:
            soup = self.get_page(detail_url)
            if not soup:
                return None

            # 1. Try Open Graph meta tag first (most reliable)
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                image_url = urljoin(detail_url, og_image["content"])
                self.logger.info(f"Found image via og:image tag: {image_url}")
                return image_url

            # 2. Site-specific fallbacks
            parsed_url = urlparse(detail_url)

            # Secondechance.org: slider images
            if "secondechance.org" in parsed_url.netloc:
                slider_img = soup.select_one(".splide__slide img")
                if slider_img and slider_img.get("src"):
                    image_url = urljoin(detail_url, slider_img["src"])
                    self.logger.info(f"Found secondechance image: {image_url}")
                    return image_url

            # chiensadonner.com: main image in listing
            if "chiensadonner.com" in parsed_url.netloc:
                main_img = soup.select_one(".single-ad-main-image img")
                if main_img and main_img.get("src"):
                    image_url = urljoin(detail_url, main_img["src"])
                    self.logger.info(f"Found chiensadonner image: {image_url}")
                    return image_url

            # 3. Generic fallback: find the largest image
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
                    # Fetch image headers to get size, this is slow
                    # A better heuristic is needed if this is too slow.
                    # Let's try to get width/height attributes first.
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

    def build_filtered_url(self, broader_search=False) -> str:
        """Build URL with filters for big dogs from Paris region or broader search."""
        base_url = f"{self.base_url}/animal/adopter-un-chien"

        # Parameters for big dogs
        params = [
            "species=1",  # Dogs
        ]

        if broader_search:
            # Search multiple regions around Paris
            for region in self.search_regions:
                params.append(f"regions[]={region}")
            self.logger.info("Using broader search across multiple regions")
        else:
            # Just Paris region
            params.append("region=2")  # Île-de-France

            # Add Paris region departments
            for dept in self.paris_departments:
                params.append(f"departments[]={dept}")

        filtered_url = f"{base_url}?{'&'.join(params)}"
        self.logger.info(f"Using filtered URL: {filtered_url}")
        return filtered_url

    def scrape_secondechance(self) -> List[Dict]:
        """Scrape dogs from secondechance.org Paris region."""
        all_dogs = []

        # Use the site's filtered URL
        filtered_url = self.build_filtered_url()

        visited_urls = set()
        urls_to_visit = [filtered_url]

        while urls_to_visit:
            current_url = urls_to_visit.pop(0)
            if current_url in visited_urls:
                continue

            visited_urls.add(current_url)
            self.logger.info(f"Scraping from secondechance.org: {current_url}")

            # Scrape dogs from current page
            dogs, soup = self.scrape_dogs_page_filtered(current_url)
            if dogs:
                all_dogs.extend(dogs)

            # Find pagination URLs from the returned soup
            if soup:
                pagination_urls = self.find_pagination_urls(soup, current_url)
                for url in pagination_urls:
                    if url not in visited_urls:
                        urls_to_visit.append(url)

            # Limit to reasonable number of pages
            if len(visited_urls) >= 10:
                break

        return all_dogs

    def scrape_dogs_page_filtered(self, url: str) -> List[Dict]:
        """Scrape dogs from a page and score them based on criteria."""
        soup = self.get_page(url)
        if not soup:
            return []

        dogs = []

        # Look for actual dog listings more systematically
        # First, try to find links to individual dog pages
        dog_links = []
        all_links = soup.find_all("a", href=True)
        for link in all_links:
            href = link.get("href", "")
            # Look for links that appear to be individual dog pages
            if "/animal/" in href and not any(
                skip in href
                for skip in [
                    "adopter-un-chien",
                    "adopter-un-chat",
                    "ils-ont-ete-adoptes",
                    "perles-noires",
                    "seniors-en-or",
                    "pourquoi-pas-moi",
                    "urgences",
                    "coup-de-coeur",
                    "voir-plus",
                    "exclure",
                ]
            ):
                # Check if this looks like a dog listing (contains text with dog info)
                link_text = link.get_text().strip()
                if any(
                    indicator in link_text.lower()
                    for indicator in [
                        "mâle",
                        "femelle",
                        "ans",
                        "chien",
                        "chienne",
                        "bouledogue anglais",
                        "carlin",
                        "shih tzu",
                        "cavalier king charles",
                        "bichon havanais",
                        "bichon frisé",
                        "lhasa apso",
                        "boston terrier",
                        "petit brabançon",
                    ]
                ):
                    if not href.startswith("http"):
                        href = f"{self.base_url}{href}"
                    dog_links.append(href)

        self.logger.info(f"Found {len(dog_links)} potential dog pages")

        # If we found dog links, process them
        if dog_links:
            for dog_url in dog_links:
                # Extract basic info from the link page
                dog_soup = self.get_page(dog_url)
                if dog_soup:
                    # Extract dog information from the detail page
                    title = dog_soup.find("title")
                    name = title.get_text().strip() if title else "Unknown"

                    # Get all text content to extract info
                    content = dog_soup.get_text()

                    # Create basic dog info structure
                    dog_info = {
                        "name": name.split("-")[0].strip() if "-" in name else name,
                        "full_description": content,
                        "detail_url": dog_url,
                    }

                    # Only process if we have a name for the dog
                    if dog_info["name"]:
                        dogs.append(dog_info)

        # Fallback: try the old method if no dogs found
        if not dogs:
            # Use the old selector approach
            elements = soup.select("div.p-6.w-full")
            if elements:
                self.logger.info(
                    f"Found {len(elements)} dog elements with old selector"
                )
                for element in elements:
                    dog_info = self.extract_dog_info(element)
                    if dog_info["name"]:
                        if dog_info["detail_url"]:
                            dog_info["full_description"] = self.get_full_description(
                                dog_info["detail_url"]
                            )
                        dogs.append(dog_info)

        self.logger.info(f"Scraped {len(dogs)} dogs from {url}")
        return dogs, soup

    def find_pagination_urls(self, soup: BeautifulSoup, base_url: str) -> List[str]:
        """Find pagination URLs from a page."""
        pagination_urls = []
        pagination_divs = soup.select("div.pagination")
        if pagination_divs:
            for div in pagination_divs:
                links = div.select("a")
                for link in links:
                    href = link.get("href")
                    if href and "page" in href and "?" in href:
                        # Ensure it's a relative URL and not an external link
                        if not href.startswith("http"):
                            href = urljoin(base_url, href)
                        pagination_urls.append(href)
        return pagination_urls

    def scrape_chiensadonner(self) -> List[Dict]:
        """Scrape dogs from chiensadonner.com for all Ile-de-France departments."""
        all_dogs = []
        base_url = "https://www.chiensadonner.com/"
        # Department codes for Île-de-France
        ile_de_france_departments = ["75", "77", "78", "91", "92", "93", "94", "95"]

        for location_code in ile_de_france_departments:
            # Start with the first page URL for the department
            current_url = f"{base_url}ads/?s=&location={location_code}&scat=0&lat=0&lng=0&radius=80&st=ad_listing"
            page_num = 1

            while current_url and page_num <= 5:  # Limit to 5 pages per department
                self.logger.info(
                    f"Scraping chiensadonner page {page_num} for department '{location_code}': {current_url}"
                )
                soup = self.get_page(current_url)
                if not soup:
                    self.logger.info(
                        f"Stopping pagination for department '{location_code}' due to an error on page {page_num}."
                    )
                    break

                dog_elements = soup.select("article.listing-item")
                if not dog_elements:
                    if page_num > 1:
                        self.logger.info(
                            f"No more dogs found for department '{location_code}' on page {page_num}. Stopping."
                        )
                    break

                self.logger.info(
                    f"Found {len(dog_elements)} potential dogs on page {page_num} for department '{location_code}'"
                )

                for element in dog_elements:
                    dog_info = self.extract_dog_info_chiensadonner(element)
                    if dog_info:
                        all_dogs.append(dog_info)

                # Find the 'next page' link to handle pagination dynamically
                next_page_element = soup.select_one("a.next.page-numbers")
                if next_page_element and next_page_element.get("href"):
                    current_url = next_page_element["href"]
                else:
                    current_url = None  # No more pages

                page_num += 1
        return all_dogs

    def extract_dog_info_chiensadonner(self, dog_element) -> Optional[Dict]:
        """Extracts raw text and basic info from a chiensadonner.com listing."""
        try:
            dog_info = {
                "name": "Unknown",
                "detail_url": "",
                "full_description": "",
                "scraped_date": datetime.now().isoformat(),
                "source": "chiensadonner.com",
            }

            title_element = dog_element.select_one("h2.entry-title a")
            if not title_element:
                return None

            dog_info["name"] = title_element.get_text(strip=True)
            dog_info["detail_url"] = urljoin(
                "https://www.chiensadonner.com", title_element.get("href")
            )

            # Get the full description from the detail page for Gemini
            if dog_info["detail_url"]:
                detail_soup = self.get_page(dog_info["detail_url"])
                if detail_soup:
                    dog_info["full_description"] = detail_soup.get_text(
                        separator="\n", strip=True
                    )
                else:
                    self.logger.warning(
                        f"Could not fetch detail page for {dog_info['name']}"
                    )
                    # We can still try to score with the limited info from the listing page
                    dog_info["full_description"] = dog_element.get_text(
                        separator="\n", strip=True
                    )

            return dog_info

        except Exception as e:
            self.logger.warning(
                f"Error extracting dog info from chiensadonner.com: {e}"
            )
            return None

    def scrape_crocsmignons(self) -> List[Dict]:
        """Scrape dogs from latribudescrocsmignons.com."""
        self.logger.info("Scraping from latribudescrocsmignons.com")
        all_dogs = []
        url = "https://www.latribudescrocsmignons.com/a-l-adoption"

        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        driver = None
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)

            driver.get(url)
            time.sleep(5)  # Wait for initial page load

            last_height = driver.execute_script("return document.body.scrollHeight")
            while True:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    break
                last_height = new_height

            soup = BeautifulSoup(driver.page_source, "lxml")
            links = set()
            for a in soup.find_all("a", href=True):
                if "single-post" in a["href"]:
                    links.add(a["href"])

            self.logger.info(
                f"Found {len(links)} potential dog pages from latribudescrocsmignons.com"
            )

            for link in links:
                dog_info = self.extract_dog_info_crocsmignons(link)
                if dog_info:
                    all_dogs.append(dog_info)

        except Exception as e:
            self.logger.error(f"Error scraping latribudescrocsmignons.com: {e}")
        finally:
            if driver:
                driver.quit()

        return all_dogs

    def extract_dog_info_crocsmignons(self, detail_url: str) -> Optional[Dict]:
        """Extracts raw text and basic info from a latribudescrocsmignons.com listing."""
        try:
            dog_info = {
                "name": "Unknown",
                "detail_url": detail_url,
                "full_description": "",
                "scraped_date": datetime.now().isoformat(),
                "source": "latribudescrocsmignons.com",
            }

            detail_soup = self.get_page(dog_info["detail_url"])
            if detail_soup:
                title_element = detail_soup.find("title")
                if title_element:
                    # Extract name from title, e.g., "Nepita, une petite pépite corse | La Tribu des Crocs Mignons"
                    dog_info["name"] = (
                        title_element.get_text(strip=True).split("|")[0].strip()
                    )

                dog_info["full_description"] = detail_soup.get_text(
                    separator="\n", strip=True
                )
            else:
                self.logger.warning(f"Could not fetch detail page for {detail_url}")
                return None

            return dog_info

        except Exception as e:
            self.logger.warning(
                f"Error extracting dog info from latribudescrocsmignons.com: {e}"
            )
            return None

    def scrape_happydogsforever(self) -> List[Dict]:
        """Scrape dogs from happydogsforever.com."""
        self.logger.info("Scraping from happydogsforever.com")
        all_dogs = []
        url = "https://www.happydogsforever.com/nos-chiens-chats"

        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        driver = None
        try:
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)

            driver.get(url)
            time.sleep(5)  # Wait for initial page load

            # Scroll to load all content
            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_count = 0
            while True:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height or scroll_count > 10:
                    break
                last_height = new_height
                scroll_count += 1

            soup = BeautifulSoup(driver.page_source, "lxml")

            # First, find category links to follow
            category_links = []
            category_selectors = [
                "a[href*='nos-chiens-chats']",
                "a[href*='nos-chiens-a-l-adoption']",
            ]

            for selector in category_selectors:
                links = soup.select(selector)
                for link in links:
                    href = link.get("href")
                    if href:
                        if href.startswith("http"):
                            full_url = href
                        else:
                            full_url = urljoin("https://www.happydogsforever.com", href)
                        # Filter out categories for cats and already adopted dogs
                        if (
                            full_url not in category_links
                            and "les-chats" not in full_url.lower()
                            and "ils-sont-adoptes" not in full_url.lower()
                        ):
                            category_links.append(full_url)
                            self.logger.info(f"Found category link: {full_url}")

            self.logger.info(f"Found {len(category_links)} category links to follow")

            # Process each category link
            for category_url in category_links:
                try:
                    self.logger.info(f"Scraping category: {category_url}")
                    driver.get(category_url)
                    time.sleep(3)  # Wait for page to load

                    # Scroll to load all content in category
                    cat_last_height = driver.execute_script(
                        "return document.body.scrollHeight"
                    )
                    cat_scroll_count = 0
                    while True:
                        driver.execute_script(
                            "window.scrollTo(0, document.body.scrollHeight);"
                        )
                        time.sleep(2)
                        cat_new_height = driver.execute_script(
                            "return document.body.scrollHeight"
                        )
                        if cat_new_height == cat_last_height or cat_scroll_count > 5:
                            break
                        cat_last_height = cat_new_height
                        cat_scroll_count += 1

                    category_soup = BeautifulSoup(driver.page_source, "lxml")

                    # Try to find individual dog elements in this category
                    dog_selectors = [
                        "[class*='dog'i]",
                        "[class*='pet'i]",
                        "[class*='animal'i]",
                        "[class*='card'i]",
                        "[class*='profile'i]",
                        "article",
                        ".entry",
                        ".post",
                        "[class*='item'i]",
                    ]

                    dog_elements = []
                    for selector in dog_selectors:
                        elements = category_soup.select(selector)
                        if elements:
                            dog_elements.extend(elements)
                            self.logger.info(
                                f"Found {len(elements)} elements with selector '{selector}' in category"
                            )

                    # Remove duplicates while preserving order
                    unique_dog_elements = []
                    for element in dog_elements:
                        if element not in unique_dog_elements:
                            unique_dog_elements.append(element)

                    self.logger.info(
                        f"Found {len(unique_dog_elements)} unique potential dog elements in category"
                    )

                    # Process each potential dog element
                    for element in unique_dog_elements:
                        try:
                            dog_info = self.extract_dog_info_happydogsforever(element)
                            if dog_info and dog_info["name"] != "Unknown":
                                # Make sure we don't add duplicates
                                is_duplicate = False
                                for existing_dog in all_dogs:
                                    if (
                                        existing_dog["name"] == dog_info["name"]
                                        and existing_dog["detail_url"]
                                        == dog_info["detail_url"]
                                    ):
                                        is_duplicate = True
                                        break

                                if not is_duplicate:
                                    all_dogs.append(dog_info)
                        except Exception as e:
                            self.logger.warning(
                                f"Error processing dog element in category: {e}"
                            )
                            continue

                except Exception as e:
                    self.logger.error(f"Error scraping category {category_url}: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Error scraping happydogsforever.com: {e}")
        finally:
            if driver:
                driver.quit()

        self.logger.info(f"Scraped {len(all_dogs)} dogs from happydogsforever.com")
        return all_dogs

    def extract_dog_info_happydogsforever(self, dog_element) -> Optional[Dict]:
        """Extracts raw text and basic info from a happydogsforever.com listing."""
        try:
            dog_info = {
                "name": "Unknown",
                "detail_url": "",
                "full_description": "",
                "scraped_date": datetime.now().isoformat(),
                "source": "happydogsforever.com",
            }

            # Try to find name in various elements
            name_selectors = [
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                ".name",
                ".title",
                ".dog-name",
                "[class*='dog'i]",
                "[class*='pet'i]",
                "[class*='animal'i]",
            ]

            # Try each selector to find the name
            for selector in name_selectors:
                name_elem = dog_element.select_one(selector)
                if name_elem:
                    name_text = name_elem.get_text(strip=True)
                    # Only set as name if it's not empty and not too generic
                    if (
                        name_text
                        and len(name_text) > 1
                        and name_text.lower()
                        not in ["dog", "pet", "animal", "chien", "chat"]
                    ):
                        dog_info["name"] = name_text
                        break

            # If we still don't have a name, try to get text content from the element
            if dog_info["name"] == "Unknown":
                element_text = dog_element.get_text(strip=True)
                if element_text and len(element_text) > 1:
                    # Use first line or first few words as name
                    lines = element_text.split("\n")
                    if lines:
                        first_line = lines[0].strip()
                        if first_line and len(first_line) > 1:
                            dog_info["name"] = first_line[:50]  # Limit length

            # Try to find detail URL
            link_elem = dog_element.find("a", href=True)
            if link_elem:
                href = link_elem["href"]
                if href.startswith("http"):
                    dog_info["detail_url"] = href
                else:
                    dog_info["detail_url"] = urljoin(
                        "https://www.happydogsforever.com", href
                    )

            # Get full description from the element
            dog_info["full_description"] = dog_element.get_text(
                separator="\n", strip=True
            )

            # If we have a detail URL, try to get more detailed description
            if dog_info["detail_url"]:
                detail_soup = self.get_page(dog_info["detail_url"])
                if detail_soup:
                    # Try to get a more detailed description
                    detail_text = detail_soup.get_text(separator="\n", strip=True)
                    if len(detail_text) > len(dog_info["full_description"]):
                        dog_info["full_description"] = detail_text

            # Only return dog info if we have some content
            if dog_info["name"] != "Unknown" or dog_info["full_description"]:
                return dog_info

            return None

        except Exception as e:
            self.logger.warning(
                f"Error extracting dog info from happydogsforever.com: {e}"
            )
            return None

    def scrape_rememberme(self) -> List[Dict]:
        """Scrape dogs from remembermefrance.org."""
        self.logger.info("Scraping from remembermefrance.org")
        all_dogs = []
        base_url = "https://remembermefrance.org/pets/?breed=chiot&pets_search%5Bsexe%5D=all&pets_search%5Bou_est_le_chien%5D=En+Roumanie&pets_search%5Burgence%5D=all"
        page = 1

        while True:
            self.logger.info(f"Scraping remembermefrance.org page {page}")
            url = f"{base_url}&_page={page}"
            if page > 1:
                url = f"https://remembermefrance.org/pets/page/{page}/?breed=chiot&pets_search%5Bsexe%5D=all&pets_search%5Bou_est_le_chien%5D=En+Roumanie&pets_search%5Burgence%5D=all"

            soup = self.get_page(url)
            if not soup:
                break

            dog_articles = soup.find_all("article", class_="pets")
            if not dog_articles:
                break

            for article in dog_articles:
                dog_info = self.extract_dog_info_rememberme(article)
                if dog_info:
                    all_dogs.append(dog_info)

            next_link = soup.find("a", class_="next page-numbers")
            if not next_link:
                break

            page += 1
            time.sleep(1)

        return all_dogs

    def extract_dog_info_rememberme(
        self, article_soup: BeautifulSoup
    ) -> Optional[Dict]:
        """Extracts raw text and basic info from a remembermefrance.org listing."""
        try:
            link_tag = article_soup.find("a", href=True)
            if not link_tag:
                return None

            detail_url = link_tag["href"]
            name_tag = article_soup.find("h3", class_="pet-title")
            name = name_tag.get_text(strip=True) if name_tag else "Unknown"

            detail_soup = self.get_page(detail_url)
            full_description = ""
            if detail_soup:
                content_area = detail_soup.find("div", class_="pet-description")
                if content_area:
                    full_description = content_area.get_text(
                        separator="\\n", strip=True
                    )
                else:
                    # Fallback to the whole page text if the specific container is not found
                    full_description = detail_soup.get_text(separator="\\n", strip=True)

            return {
                "name": name,
                "detail_url": detail_url,
                "full_description": full_description,
                "scraped_date": datetime.now().isoformat(),
                "source": "remembermefrance.org",
            }
        except Exception as e:
            self.logger.warning(
                f"Error extracting dog info from remembermefrance.org: {e}"
            )
            return None

    def scrape_larchedekala(self) -> List[Dict]:
        """Scrape dogs from larchedekala.fr."""
        self.logger.info("Scraping from larchedekala.fr")
        all_dogs = []
        url = "https://www.larchedekala.fr/nos-chiens-a-l-adoption/les-chiots-jusqu-a-1-an"

        soup = self.get_page(url)
        if not soup:
            return []

        dog_elements = soup.find_all("div", class_="js-product-container")

        for element in dog_elements:
            if "data-webshop-product" in element.attrs:
                product_data = element["data-webshop-product"]
                try:
                    dog_info_json = json.loads(product_data)
                    detail_url = urljoin(
                        "https://www.larchedekala.fr", dog_info_json.get("url")
                    )

                    dog_info = self.extract_dog_info_larchedekala(detail_url)
                    if dog_info:
                        all_dogs.append(dog_info)

                except json.JSONDecodeError:
                    self.logger.warning(
                        f"Warning: Could not decode JSON for a product on larchedekala.fr."
                    )
                    continue

        return all_dogs

    def extract_dog_info_larchedekala(self, detail_url: str) -> Optional[Dict]:
        """Extracts raw text and basic info from a larchedekala.fr listing."""
        try:
            dog_info = {
                "name": "Unknown",
                "detail_url": detail_url,
                "full_description": "",
                "scraped_date": datetime.now().isoformat(),
                "source": "larchedekala.fr",
            }

            detail_soup = self.get_page(dog_info["detail_url"])
            if detail_soup:
                name_element = detail_soup.find("h1", class_="product-page__heading")
                if name_element:
                    dog_info["name"] = name_element.get_text(strip=True)

                description_element = detail_soup.find(
                    "div", class_="product-page__description"
                )
                if description_element:
                    dog_info["full_description"] = description_element.get_text(
                        separator="\\n", strip=True
                    )
                else:
                    # Fallback to getting all text if the specific div isn't found
                    dog_info["full_description"] = detail_soup.get_text(
                        separator="\\n", strip=True
                    )
            else:
                self.logger.warning(f"Could not fetch detail page for {detail_url}")
                return None

            return dog_info

        except Exception as e:
            self.logger.warning(f"Error extracting dog info from larchedekala.fr: {e}")
            return None

    def start_scheduler(self):
        """Start the daily scheduler."""
        schedule.every().day.at("09:00").do(self.run_daily_scrape)

    def scrape_happytogether(self) -> List[Dict]:
        """Scrape dog adoption listings from happytogether.forumactif.com sections 1 and 2 only."""
        self.logger.info("Scraping from happytogether.forumactif.com")
        all_dogs = []

        # Forum sections for dog adoption (only sections 1 and 2 as requested)
        forum_sections = {
            "En Roumanie": "/f16-en-roumanie",
            "En Famille d'Accueil": "/f24-en-famille-d-accueil",
        }

        base_url = "https://happytogether.forumactif.com"

        for section_name, section_path in forum_sections.items():
            self.logger.info(f"Scraping section: {section_name}")
            forum_url = urljoin(base_url, section_path)

            # Get topics from the forum section
            topics = self.get_forum_topics_happytogether(forum_url)

            # Get details for each topic
            for i, topic in enumerate(topics[:10]):  # Limit to first 10 for testing
                self.logger.info(
                    f"Scraping topic {i + 1}/{min(10, len(topics))}: {topic['title']}"
                )
                dog_details = self.get_topic_details_happytogether(topic["url"])
                if dog_details:
                    # Add source information
                    dog_details["source"] = "happytogether.forumactif.com"
                    all_dogs.append(dog_details)

        self.logger.info(
            f"Scraped {len(all_dogs)} dogs from happytogether.forumactif.com"
        )
        return all_dogs

    def get_page_with_selenium(self, url):
        """
        Fetch page content with Selenium for dynamic content
        """
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")

        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        try:
            self.logger.info(f"Loading page: {url}")
            driver.get(url)
            # Wait for initial content to load
            time.sleep(3)

            # Scroll to load all content
            last_height = driver.execute_script("return document.body.scrollHeight")
            scroll_count = 0
            while True:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height or scroll_count > 5:
                    break
                last_height = new_height
                scroll_count += 1

            # Wait a bit more for any remaining content to load
            time.sleep(2)

            return driver.page_source
        finally:
            driver.quit()

    def get_forum_topics_happytogether(self, forum_url):
        """
        Get all topics (dog listings) from a forum page
        """
        try:
            html_content = self.get_page_with_selenium(forum_url)
            soup = BeautifulSoup(html_content, "html.parser")

            topics = []
            # Look for topic links in the forum
            topic_elements = soup.select("ul.topiclist li.row")

            for element in topic_elements:
                topic_link = element.select_one("a.topictitle")
                if topic_link:
                    topic_url = urljoin(
                        "https://happytogether.forumactif.com", topic_link.get("href")
                    )
                    topic_title = topic_link.get_text().strip()

                    # Extract additional info if available
                    last_post_elem = element.select_one(".lastpost")
                    last_post_info = ""
                    if last_post_elem:
                        last_post_info = last_post_elem.get_text().strip()

                    topics.append(
                        {
                            "title": topic_title,
                            "url": topic_url,
                            "last_post": last_post_info,
                            "scraped_date": datetime.now().isoformat(),
                        }
                    )

            self.logger.info(f"Found {len(topics)} topics in forum")
            return topics
        except Exception as e:
            self.logger.error(f"Error getting forum topics: {e}")
            return []

    def get_topic_details_happytogether(self, topic_url):
        """
        Get detailed information from a topic page
        """
        try:
            html_content = self.get_page_with_selenium(topic_url)
            soup = BeautifulSoup(html_content, "html.parser")

            # Extract topic title
            title_elem = soup.select_one("h1.page-title, h1.topic-title, h1")
            title = title_elem.get_text().strip() if title_elem else "Unknown"

            # Extract main content
            content_area = soup.select_one(".post, .content, .post-content, .message")
            full_description = ""
            if content_area:
                full_description = content_area.get_text(separator="\n", strip=True)
            else:
                # Fallback to getting all text content
                full_description = soup.get_text(separator="\n", strip=True)

            # Try to extract structured information
            dog_info = {
                "name": self.extract_dog_name_happytogether(title, full_description),
                "breed": self.extract_breed_happytogether(full_description),
                "age": self.extract_age_happytogether(full_description),
                "gender": self.extract_gender_happytogether(full_description),
                "size": self.extract_size_happytogether(full_description),
                "description": full_description[:1000],  # First 1000 chars as summary
                "full_description": full_description,
                "detail_url": topic_url,
                "scraped_date": datetime.now().isoformat(),
            }

            return dog_info
        except Exception as e:
            self.logger.error(f"Error getting topic details: {e}")
            return None

    def extract_dog_name_happytogether(self, title, description):
        """Extract dog name from title or description"""
        # Often the name is the first word in the title
        if title and " - " in title:
            return title.split(" - ")[0].strip()
        return title or "Unknown"

    def extract_breed_happytogether(self, description):
        """Extract breed information from description"""
        # Common breed patterns
        breed_keywords = [
            "berger",
            "labrador",
            "golden",
            "chihuahua",
            "bouledogue",
            "carlin",
            "caniche",
            "cavalier",
            "retriever",
            "husky",
        ]

        description_lower = description.lower()
        for keyword in breed_keywords:
            if keyword in description_lower:
                # Try to get a more complete breed name
                start = description_lower.find(keyword)
                if start > -1:
                    end = min(start + 50, len(description))
                    return description[start:end].strip()
        return ""

    def extract_age_happytogether(self, description):
        """Extract age information from description"""
        import re

        # Look for age patterns
        age_patterns = [
            r"(\d+)\s*ans?",
            r"(\d+)\s*mois",
            r"né\s*en\s*(\d{4})",
            r"née\s*en\s*(\d{4})",
        ]
        description_lower = description.lower()

        for pattern in age_patterns:
            match = re.search(pattern, description_lower)
            if match:
                return match.group(0)
        return ""

    def extract_gender_happytogether(self, description):
        """Extract gender information from description"""
        description_lower = description.lower()
        if "mâle" in description_lower or "male" in description_lower:
            return "Mâle"
        elif "femelle" in description_lower or "femelle" in description_lower:
            return "Femelle"
        return ""

    def extract_size_happytogether(self, description):
        """Extract size information from description"""
        description_lower = description.lower()
        if "petit" in description_lower:
            return "Petit"
        elif "moyen" in description_lower:
            return "Moyen"
        elif "grand" in description_lower:
            return "Grand"
        return ""

    def run_daily_scrape(self):
        """Run the daily scraping job."""
        self.logger.info("Starting daily dog scraping job")

        dogs = self.scrape_all_sources()

        if dogs:
            # First, get image URLs for top dogs and rescore them
            for dog in dogs:
                # Sort by score
                dogs.sort(key=lambda x: x.get("score", 0), reverse=True)

            self.save_data(dogs)
            print(f"\n🐕 FOUND {len(dogs)} DOGS IN PARIS REGION")
            print(f"📊 Ranked by apartment suitability & cat compatibility:")
            print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            # Filter for dogs with a score of 80 or higher
            excellent_dogs = [dog for dog in dogs if dog.get("score", 0) >= 80]

            if not excellent_dogs:
                print("\nNo dogs scored 80 or higher in this run.")

            for i, dog in enumerate(excellent_dogs, 1):
                score = dog.get("score", 0)
                name = dog.get("name", "Unknown")
                score_indicator = "🟢 EXCELLENT"

                print(f"\n{i}. {name} - {score_indicator} ({score}/100)")
                print(f"   Score breakdown: {', '.join(dog.get('score_details', []))}")
                print(f"   🔗 {dog.get('detail_url', 'No URL')}")

                if dog.get("image_url"):
                    print(f"   🖼️ Image: {dog['image_url']}")

        else:
            print(f"\n⚠️  No dogs found")
            print(
                f"💡 Try checking the site manually or expand search to other regions"
            )

        self.logger.info("Daily scraping job completed")


def main():
    """Main function to run the bot."""
    bot = DogAdoptionBot()

    # Run once immediately for testing
    bot.run_daily_scrape()

    # Uncomment to start daily scheduler
    # bot.start_scheduler()


if __name__ == "__main__":
    main()
