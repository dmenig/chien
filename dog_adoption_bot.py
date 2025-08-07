import logging
from typing import List, Dict, Optional
from datetime import datetime
import re
from urllib.parse import urljoin, urlparse
from urllib.parse import urlencode
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


from common.io import save_data
from common.web import get_page_with_selenium
from common.gemini import score_dog_with_gemini
from common import dog_scrapers


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
        self.search_regions = ["2", "3", "4", "5"]  # Île-de-France, Nord, Est, Sud-Est
        self.paris_departments = [
            "75",
            "77",
            "78",
            "91",
            "92",
            "93",
            "94",
            "95",
        ]  # Paris departments

    def setup_logging(self):
        """Set up logging configuration."""
        log_file = "dog_bot.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler()],
        )
        self.logger = logging.getLogger(__name__)

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
        sources = {
            "secondechance": dog_scrapers.scrape_secondechance,
            "chiensadonner": dog_scrapers.scrape_chiensadonner,
            "crocsmignons": dog_scrapers.scrape_crocsmignons,
            "larchedekala": dog_scrapers.scrape_larchedekala,
            "rememberme": dog_scrapers.scrape_rememberme,
            "happydogsforever": dog_scrapers.scrape_happydogsforever,
            "happytogether": dog_scrapers.scrape_happytogether,
        }
        all_dogs = self._execute_scraping_tasks(sources)
        unique_dogs = self._deduplicate_dogs(all_dogs)
        scored_dogs = self._score_dogs(unique_dogs)
        scored_dogs.sort(key=lambda x: x.get("score", 0), reverse=True)
        self.logger.info(f"Total unique dogs from all sources: {len(scored_dogs)}")
        return scored_dogs

    def _execute_scraping_tasks(self, sources: Dict) -> List[Dict]:
        all_dogs = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_source = {
                executor.submit(scraper, self): name
                for name, scraper in sources.items()
            }
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    dogs = future.result()
                    all_dogs.extend(dogs)
                    self.logger.info(f"Found {len(dogs)} dogs from {source}.org")
                except Exception as exc:
                    self.logger.error(f"{source} generated an exception: {exc}")
        return all_dogs

    def _deduplicate_dogs(self, dogs: List[Dict]) -> List[Dict]:
        unique_dogs = {}
        for dog in dogs:
            # Use a tuple of sorted items for the key to handle dictionaries with the same content but different order
            key = tuple(sorted(dog.items()))
            if key not in unique_dogs:
                unique_dogs[key] = dog
        return list(unique_dogs.values())

    def _score_dogs(self, dogs: List[Dict]) -> List[Dict]:
        with ThreadPoolExecutor(max_workers=20) as executor:
            future_to_dog = {
                executor.submit(score_dog_with_gemini, dog): dog for dog in dogs
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
        return dogs

    def run_daily_scrape(self):
        """Run the daily scraping job."""
        self.logger.info("Starting daily dog adoption scrape...")
        all_dogs = self.scrape_all_sources()
        if all_dogs:
            save_data(all_dogs, "all_sources")
            self.logger.info(f"Successfully scraped {len(all_dogs)} dogs.")
        else:
            self.logger.warning("No dogs were scraped in this run.")

    def scrape_dogs_page_filtered(
        self, url: str
    ) -> (List[Dict], Optional[BeautifulSoup]):
        """Scrape a single page of dog listings from secondechance.org."""
        soup = self.get_page(url)
        if not soup:
            return [], None

        dogs = []
        dog_elements = soup.select("div.card-animal-container")
        self.logger.info(f"Found {len(dog_elements)} potential dogs on {url}")

        for element in dog_elements:
            dog_info = self.extract_dog_info_secondechance(element)
            if dog_info:
                dogs.append(dog_info)
        return dogs, soup

    def find_pagination_urls(self, soup: BeautifulSoup, current_url: str) -> List[str]:
        """Find all pagination links on the page."""
        urls = []
        pagination = soup.find("ul", class_="pagination")
        if pagination:
            for link in pagination.find_all("a", href=True):
                page_url = urljoin(current_url, link["href"])
                if urlparse(page_url).path == urlparse(current_url).path:
                    urls.append(page_url)
        return urls

    def extract_dog_info_secondechance(self, element: BeautifulSoup) -> Optional[Dict]:
        """Extract dog information from a single listing element on secondechance.org."""
        try:
            name_element = element.select_one("h3.card-title a")
            name = name_element.text.strip()
            detail_url = urljoin(self.base_url, name_element["href"])

            # Extract other details
            breed = element.select_one("div.card-animal-subtitle").text.strip()
            sex_age_size = element.select_one("ul.card-animal-list li").text.strip()
            sex, age, size = [item.strip() for item in sex_age_size.split("/")]

            return {
                "name": name,
                "breed": breed,
                "sex": sex,
                "age": age,
                "size": size,
                "detail_url": detail_url,
                "source": "secondechance.org",
            }
        except (AttributeError, IndexError) as e:
            self.logger.warning(f"Could not extract dog info from element: {e}")
            return None

    def extract_dog_info_chiensadonner(self, element: BeautifulSoup) -> Optional[Dict]:
        """Extract dog information from a single listing on chiensadonner.com."""
        try:
            title_element = element.select_one("h2.listing-title a")
            name = title_element.text.strip()
            detail_url = title_element["href"]

            # Extract other details from the listing
            location_element = element.select_one(".listing-location a")
            location = location_element.text.strip() if location_element else "N/A"

            breed_element = element.select_one(".listing-cat a")
            breed = breed_element.text.strip() if breed_element else "N/A"

            description_element = element.select_one(".listing-content p")
            description_text = (
                description_element.text.strip() if description_element else "N/A"
            )

            # Use regex to find age if available
            age_match = re.search(r"(\d+)\s+ans?", description_text, re.IGNORECASE)
            age = f"{age_match.group(1)} ans" if age_match else "N/A"

            return {
                "name": name,
                "breed": breed,
                "location": location,
                "age": age,
                "detail_url": detail_url,
                "source": "chiensadonner.com",
                "description": description_text,
            }
        except (AttributeError, IndexError) as e:
            self.logger.warning(f"Could not extract dog info from chiensadonner: {e}")
            return None

    def extract_dog_info_crocsmignons(self, dog_url: str) -> Optional[Dict]:
        """Extract dog information from a single dog page on latribudescrocsmignons.com."""
        try:
            soup = self.get_page(dog_url)
            if not soup:
                return None

            name = soup.select_one("h1.elementor-heading-title").text.strip()

            # Extract details from the info table
            details = {}
            info_elements = soup.select(
                "div.elementor-widget-container ul.elementor-icon-list-items li"
            )
            for item in info_elements:
                text = item.text.strip()
                if ":" in text:
                    key, value = text.split(":", 1)
                    details[key.strip().lower()] = value.strip()

            return {
                "name": name,
                "age": details.get("âge"),
                "sex": details.get("sexe"),
                "breed": details.get("race"),
                "detail_url": dog_url,
                "source": "latribudescrocsmignons.com",
            }
        except (AttributeError, IndexError) as e:
            self.logger.warning(f"Could not extract dog info from {dog_url}: {e}")
            return None

    def extract_dog_info_happydogsforever(
        self, element: BeautifulSoup
    ) -> Optional[Dict]:
        """Extract dog information from a single dog section on happydogsforever.com."""
        try:
            name_element = element.select_one("h3")
            if not name_element:
                return None
            name = name_element.text.strip()

            # Extract other details
            paragraphs = element.select("p")
            description = "\n".join([p.text for p in paragraphs])

            # Placeholder for details not easily available
            return {
                "name": name,
                "description": description,
                "source": "happydogsforever.com",
                "detail_url": "https://www.happydogsforever.com/a-l-adoption",  # No individual pages
            }
        except (AttributeError, IndexError) as e:
            self.logger.warning(
                f"Could not extract dog info from happydogsforever element: {e}"
            )
            return None

    def extract_dog_info_rememberme(self, element: BeautifulSoup) -> Optional[Dict]:
        """Extract dog information from a single listing on remembermefrance.org."""
        try:
            name = element.select_one(
                "h3.jet-engine-listing-dynamic-field__content"
            ).text.strip()
            detail_url = urljoin(
                "https://www.remembermefrance.org/", element.find("a")["href"]
            )

            # Extract other details
            info_list = element.select("ul.info-chien li")
            details = {
                item.find("strong").text.strip(): item.find(
                    text=True, recursive=False
                ).strip()
                for item in info_list
                if item.find("strong")
            }

            return {
                "name": name,
                "breed": details.get("Race:"),
                "sex": details.get("Sexe:"),
                "age": details.get("Âge:"),
                "detail_url": detail_url,
                "source": "remembermefrance.org",
            }
        except (AttributeError, IndexError) as e:
            self.logger.warning(f"Could not extract dog info from rememberme: {e}")
            return None

    def extract_dog_info_larchedekala(self, detail_url: str) -> Optional[Dict]:
        """Extract dog information from a product page on larchedekala.fr."""
        try:
            soup = self.get_page(detail_url)
            if not soup:
                return None

            name = soup.select_one("h1.title").text.strip()
            description = soup.select_one("div.description").text.strip()

            return {
                "name": name,
                "description": description,
                "detail_url": detail_url,
                "source": "larchedekala.fr",
            }
        except (AttributeError, IndexError) as e:
            self.logger.warning(f"Could not extract dog info from {detail_url}: {e}")
            return None

    def get_forum_topics_happytogether(self, forum_url: str) -> List[Dict]:
        """Get all topics from a forum page on happytogether.forumactif.com."""
        topics = []
        soup = self.get_page(forum_url)
        if not soup:
            return topics

        topic_rows = soup.select("table.table.forum.topics tbody tr")
        for row in topic_rows:
            title_element = row.select_one("a.topictitle")
            if title_element:
                topics.append(
                    {
                        "title": title_element.text.strip(),
                        "url": urljoin(
                            "https://happytogether.forumactif.com/",
                            title_element["href"],
                        ),
                    }
                )
        return topics

    def get_topic_details_happytogether(self, topic_url: str) -> Optional[Dict]:
        """Get dog details from a topic page on happytogether.forumactif.com."""
        try:
            soup = self.get_page(topic_url)
            if not soup:
                return None

            post_content = soup.select_one("div.post.post-content")
            name = soup.select_one("h1 a").text.strip()

            return {
                "name": name,
                "description": post_content.text.strip(),
                "detail_url": topic_url,
                "source": "happytogether.forumactif.com",
            }
        except (AttributeError, IndexError) as e:
            self.logger.warning(f"Could not extract dog details from {topic_url}: {e}")
            return None


def main():
    """Main function to run the dog adoption bot."""
    bot = DogAdoptionBot()
    bot.run_daily_scrape()


if __name__ == "__main__":
    main()
