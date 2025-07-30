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

    def _generate_gemini_prompt(self, dog_info: Dict) -> str:
        """Generate a detailed prompt for Gemini based on the raw text of a dog listing."""
        try:
            with open("prompt.txt", "r", encoding="utf-8") as f:
                prompt_template = f.read()
        except FileNotFoundError:
            self.logger.error("prompt.txt not found. Please create it.")
            return ""

        raw_text = dog_info.get("full_description", "No description available.")
        dog_name = dog_info.get("name", "Unknown")

        return prompt_template.format(dog_name=dog_name, raw_text=raw_text)

    def score_dog_with_gemini(self, dog_info: Dict) -> Dict:
        """Score a dog using the Gemini 1.5 Flash model based on raw text."""
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
            prompt = self._generate_gemini_prompt(dog_info)
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

    def start_scheduler(self):
        """Start the daily scheduler."""
        schedule.every().day.at("09:00").do(self.run_daily_scrape)

    def run_daily_scrape(self):
        """Run the daily scraping job."""
        self.logger.info("Starting daily dog scraping job")

        dogs = self.scrape_all_sources()

        if dogs:
            self.save_data(dogs)
            print(f"\n🐕 FOUND {len(dogs)} DOGS IN PARIS REGION")
            print(f"📊 Ranked by apartment suitability & cat compatibility:")
            print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

            for i, dog in enumerate(dogs, 1):
                score = dog.get("score", 0)
                name = dog.get("name", "Unknown")

                # Color coding based on score
                if score >= 80:
                    score_indicator = "🟢 EXCELLENT"
                elif score >= 60:
                    score_indicator = "🟡 GOOD"
                elif score >= 40:
                    score_indicator = "🟠 FAIR"
                else:
                    score_indicator = "🔴 POOR"

                print(f"\n{i}. {name} - {score_indicator} ({score}/100)")
                print(f"   Score breakdown: {', '.join(dog.get('score_details', []))}")
                print(f"   🔗 {dog.get('detail_url', 'No URL')}")

                # Add separator after top 3
                if i == 3 and len(dogs) > 3:
                    print(f"   ── Other dogs ──")
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
