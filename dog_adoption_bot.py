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


class DogAdoptionBot:
    def __init__(self, base_url: str = "https://www.secondechance.org"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
        )
        # Handle SSL issues
        self.session.verify = False
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.setup_logging()
        self.data_dir = "dog_data"
        self.ensure_data_directory()

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
        import os

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
        """Scrape dogs from all configured sources."""
        all_dogs = []

        # Scrape from secondechance.org
        self.logger.info("Scraping from secondechance.org")
        secondechance_dogs = self.scrape_secondechance()
        if secondechance_dogs:
            all_dogs.extend(secondechance_dogs)
        self.logger.info(f"Found {len(secondechance_dogs)} dogs from secondechance.org")

        # Scrape from chiensadonner.com
        self.logger.info("Scraping from chiensadonner.com")
        chiensadonner_dogs = self.scrape_chiensadonner()
        if chiensadonner_dogs:
            all_dogs.extend(chiensadonner_dogs)
        self.logger.info(f"Found {len(chiensadonner_dogs)} dogs from chiensadonner.com")

        # Deduplicate and sort
        self.logger.info(f"Total dogs scraped from all sources: {len(all_dogs)}")
        unique_dogs = []
        seen_dogs = set()
        for dog in all_dogs:
            # Using name and age for deduplication
            dog_key = (dog.get("name", "").lower(), dog.get("age", ""))
            if dog_key not in seen_dogs:
                seen_dogs.add(dog_key)
                unique_dogs.append(dog)

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

    def get_breed_score(self, dog_info: Dict) -> int:
        """Get score based on breed."""
        breed = dog_info.get("breed", "").lower()
        score = 0
        score_breakdown = []

        high_maintenance_shepherds = ["malinois", "australien", "allemand", "beauce"]

        # Penalize high-maintenance shepherds, even if 'berger' is in the name
        for high_maintenance_shepherd in high_maintenance_shepherds:
            if high_maintenance_shepherd in breed:
                score -= 30
                score_breakdown.append(
                    f"High-maintenance shepherd: -30 ({high_maintenance_shepherd})"
                )
                # Add score breakdown to dog_info and return immediately
                if "score_breakdown" not in dog_info:
                    dog_info["score_breakdown"] = []
                dog_info["score_breakdown"].extend(score_breakdown)
                return score

        # If it's not a high-maintenance shepherd, check for general low-maintenance keywords
        if "croise" in breed or "berger" in breed:
            score += 50
            score_breakdown.append("Low-maintenance breed (croisé/berger): +50")

        # Add the score breakdown to the dog_info dict to be used later
        if "score_breakdown" not in dog_info:
            dog_info["score_breakdown"] = []
        dog_info["score_breakdown"].extend(score_breakdown)

        return score

    def get_cat_score(self, dog_info: Dict) -> int:
        """Score based on cat-friendly characteristics."""
        description = dog_info.get("description", "").lower()
        full_desc = dog_info.get("full_description", "").lower()
        all_text = f"{description} {full_desc}"

        # Explicit cat-friendly mentions (50 points)
        cat_friendly_keywords = [
            "habitué à la présence des chats",
            "ok avec les chats",
            "s'entend avec les chats",
            "compatible avec les chats",
            "aime les chats",
            "bon avec les chats",
            "sociable avec les chats",
            "peut vivre avec des chats",
            "cohabite avec des chats",
            "testé avec des chats",
            "ok chats",
            "compatible chats",
        ]

        # Anti-cat mentions (0 points)
        anti_cat_keywords = [
            "pas de chat",
            "sans chats",
            "incompatible avec les chats",
            "n'aime pas les chats",
            "pas compatible chats",
            "pas testé avec des chats",
            "sans chat",
            "pas chat",
            "pas ok chats",
            "pas ok chat",
        ]

        # Check for anti-cat mentions first
        if any(keyword in all_text for keyword in anti_cat_keywords):
            return 0

        # Check for explicit cat-friendly mentions
        if any(keyword in all_text for keyword in cat_friendly_keywords):
            return 50

        # No explicit cat info gets moderate score
        return 25

    def get_temperament_score(self, dog_info: Dict) -> (int, List[str]):
        """Score based on calm temperament indicators and return keywords."""
        description = dog_info.get("description", "").lower()
        full_desc = dog_info.get("full_description", "").lower()
        all_text = f"{description} {full_desc}"

        calm_keywords = [
            "calme",
            "tranquille",
            "zen",
            "doux",
            "docile",
            "gentil",
            "patient",
            "sociable",
            "équilibré",
            "posé",
            "sage",
            "bien dans sa peau",
            "stable",
            "serein",
            "paisible",
        ]

        # Find all calm temperament indicators
        found_keywords = [keyword for keyword in calm_keywords if keyword in all_text]
        calm_count = len(found_keywords)

        # Score based on number of calm indicators
        score = 0
        if calm_count >= 3:
            score = 20
        elif calm_count >= 2:
            score = 15
        elif calm_count >= 1:
            score = 10

        return score, found_keywords

    def get_garden_score(self, dog_info: Dict) -> int:
        """
        Scores based on garden requirement.
        Returns a large penalty if a garden is needed.
        """
        full_desc = dog_info.get("full_description", "").lower()

        # Keywords indicating a garden is required
        requires_garden_keywords = [
            "maison avec jardin",
            "besoin d'un jardin",
            "accès jardin",
            "extérieur indispensable",
            "jardin obligatoire",
            "accès à un extérieur",
        ]

        # Keywords indicating apartment life is okay
        apartment_ok_keywords = [
            "peut vivre en appartement",
            "vie en appartement",
            "pas besoin de jardin",
        ]

        for keyword in requires_garden_keywords:
            if keyword in full_desc:
                # Heavy penalty if a garden is explicitly required
                return -100

        for keyword in apartment_ok_keywords:
            if keyword in full_desc:
                # Bonus if apartment life is explicitly mentioned as okay
                return 10

        # Neutral score if no specific mention
        return 0

    def score_dog(self, dog_info: Dict) -> Dict:
        """Score a dog based on multiple criteria."""
        score = 0
        score_details = []

        # Breed scoring (up to 50 points)
        breed_score = self.get_breed_score(dog_info)
        score += breed_score
        if breed_score != 0:
            score_details.extend(dog_info.get("score_breakdown", []))

        # Cat-friendly scoring (0-50 points)
        cat_score = self.get_cat_score(dog_info)
        score += cat_score
        if cat_score > 0:
            score_details.append(f"Cat-friendly: +{cat_score}")

        # Calm temperament bonus (0-20 points)
        temperament_score, temperament_keywords = self.get_temperament_score(dog_info)
        score += temperament_score
        if temperament_score > 0:
            score_details.append(f"Calm temperament: +{temperament_score}")

        dog_info["temperament_keywords"] = temperament_keywords

        # Garden requirement scoring (penalty)
        garden_score = self.get_garden_score(dog_info)
        score += garden_score
        if garden_score < 0:
            score_details.append(f"Garden requirement: {garden_score}")

        return {
            "total_score": score,
            "score_details": score_details,
            "breed_score": breed_score,
            "cat_score": cat_score,
            "temperament_score": temperament_score,
            "garden_score": garden_score,
        }

    def test_url_exists(self, url: str) -> bool:
        """Test if a URL exists without full parsing."""
        try:
            response = self.session.head(url, timeout=10)
            return response.status_code == 200
        except:
            return False

    def extract_dog_info(self, dog_element) -> Dict:
        """Extract information from a dog listing element."""
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
            "contact_info": "",
            "detail_url": "",
            "scraped_date": datetime.now().isoformat(),
        }

        try:
            # Try to find name - specific to secondechance.org structure
            name_elem = dog_element.find("h3", class_="pacifico-regular")
            if not name_elem:
                name_elem = dog_element.find(["h1", "h2", "h3", "h4", "h5"])
            if name_elem:
                dog_info["name"] = name_elem.get_text().strip()

            # Try to find detail URL
            detail_link = dog_element.find("a", href=True)
            if detail_link:
                dog_info["detail_url"] = urljoin(self.base_url, detail_link["href"])

            # Try to find image
            img_elem = dog_element.find("img")
            if img_elem and img_elem.get("src"):
                dog_info["image_url"] = urljoin(self.base_url, img_elem["src"])

            # Extract other details from text content
            text_content = dog_element.get_text()

            # Extract breed information more reliably
            breed_elem = dog_element.select_one("h4.text-sm.font-bold")
            if breed_elem:
                dog_info["breed"] = breed_elem.get_text(strip=True)
            else:
                # Fallback to regex on text content
                breed_patterns = [
                    r"Race :\s*([A-Z\s]+)",
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

            # If breed is still missing, try to get it from the URL
            if not dog_info["breed"] and dog_info["detail_url"]:
                try:
                    url_path = urlparse(dog_info["detail_url"]).path
                    # Extract the part between "chien-" and the trailing ID
                    match = re.search(r"chien-(.*?)-\d+", url_path)
                    if match:
                        slug = match.group(1)
                        # The name is usually the last part of the slug
                        parts = slug.split("-")
                        if len(parts) > 1:
                            # Assume last part is name, rest is breed
                            breed_parts = parts[:-1]
                            dog_info["breed"] = (
                                " ".join(breed_parts).replace("-", " ").title()
                            )
                        else:
                            dog_info["breed"] = slug.replace("-", " ").title()
                except Exception:
                    pass  # Ignore errors in URL parsing

            # Final cleanup on breed
            if dog_info["breed"]:
                breed_text = dog_info["breed"]
                # Remove size adjectives from breed
                size_adjectives = ["moyen", "grande", "petit", "petite", "grand"]
                for adj in size_adjectives:
                    breed_text = re.sub(
                        r"\b" + adj + r"\b", "", breed_text, flags=re.IGNORECASE
                    )

                breed_text = re.sub(
                    r"\sM$", "", breed_text
                )  # Remove trailing ' M' for Male
                dog_info["breed"] = breed_text.replace("Urgence", "").strip()

            # Extract size information
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
            age_patterns = [
                r"(\d+)\s*ans?",
                r"(\d+)\s*mois",
                r"(\d+)\s*years?",
                r"(\d+)\s*months?",
            ]
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

            # Extract location information - specific to secondechance.org structure
            location_elem = dog_element.find("h4", class_="open-sans font-bold")
            if location_elem:
                dog_info["location"] = location_elem.get_text().strip()
            else:
                # Fallback to pattern matching
                location_patterns = [
                    r"(\d{5})\s+([A-Z\s]+)",  # Postal code + city
                    r"(Paris|Île-de-France|Val-de-Marne|Seine-Saint-Denis|Hauts-de-Seine|Seine-et-Marne|Essonne|Yvelines|Val-d\'Oise)",
                    r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+\(\d{2,3}\)",  # City (department)
                ]

                for pattern in location_patterns:
                    match = re.search(pattern, text_content, re.IGNORECASE)
                    if match:
                        dog_info["location"] = match.group(0).strip()
                        break

            # Get description - specific to secondechance.org structure
            desc_elem = dog_element.find(
                "p", class_="open-sans text-sm text-gray-dark-sc"
            )
            if not desc_elem:
                desc_elem = dog_element.find("p")
            if desc_elem:
                dog_info["description"] = desc_elem.get_text().strip()[
                    :500
                ]  # Limit description length

            # Try to get full description from detail page (only for filtered dogs)
            # We'll get this after filtering to save time
            dog_info["full_description"] = ""

            # Try to find contact info
            contact_elem = dog_element.find(
                string=re.compile(r"contact|téléphone|email|@", re.IGNORECASE)
            )
            if contact_elem:
                dog_info["contact_info"] = contact_elem.strip()

        except Exception as e:
            self.logger.warning(f"Error extracting dog info: {e}")

        return dog_info

    def is_valid_dog_listing(self, dog_info: Dict) -> bool:
        """Check if the extracted info represents a valid dog listing."""
        name = dog_info["name"].lower()
        description = dog_info["description"].lower()

        # Filter out obvious non-dog content
        non_dog_keywords = [
            "livre",
            "book",
            "ouvrage",
            "du mois",
            "témoignage",
            "testimonial",
            "success story",
            "j'ai adopté",
            "nous avons adopté",
            "grâce à seconde chance",
            "adopter un chien",
            "adopter un chat",
            "exclure les animaux",
            "voir les autres animaux",
            "coup de coeur",
            "voir plus",
        ]

        # Check if name or description contains non-dog keywords
        for keyword in non_dog_keywords:
            if keyword in name or keyword in description:
                return False

        # Additional validation: should have some dog-related info
        dog_indicators = ["ans", "mâle", "femelle", "race", "chien", "chienne"]
        has_dog_info = any(indicator in description for indicator in dog_indicators)

        # If we have an image URL, it's likely a real dog listing
        has_image = bool(dog_info.get("image_url"))

        # Filter out cats
        if "chat" in dog_info.get("detail_url", "").lower():
            return False

        return has_dog_info or has_image

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
            "sizes[]=2",  # Medium
            "sizes[]=3",  # Large
        ]

        if broader_search:
            # Search multiple regions around Paris
            regions = ["2", "3", "4", "5"]  # Île-de-France, Nord, Est, Sud-Est
            for region in regions:
                params.append(f"regions[]={region}")
            self.logger.info("Using broader search across multiple regions")
        else:
            # Just Paris region
            params.append("region=2")  # Île-de-France

            # Add Paris region departments
            paris_departments = [
                "41",
                "42",
                "43",
                "44",
                "45",
                "46",
                "47",
                "48",
            ]  # 75, 77, 78, 91, 92, 93, 94, 95
            for dept in paris_departments:
                params.append(f"departments[]={dept}")

        filtered_url = f"{base_url}?{'&'.join(params)}"
        self.logger.info(f"Using filtered URL: {filtered_url}")
        return filtered_url

    def is_from_paris_region(self, dog_info: Dict) -> bool:
        """Check if the dog's location is in the Paris region."""
        location = dog_info.get("location", "").lower()
        name = dog_info.get("name", "").lower()
        text_to_check = f"{location} {name}"

        department_names = [
            "paris",
            "île-de-france",
            "idf",
            "seine-et-marne",
            "yvelines",
            "essonne",
            "hauts-de-seine",
            "seine-saint-denis",
            "val-de-marne",
            "val-d'oise",
        ]
        if any(dept in text_to_check for dept in department_names):
            return True

        # Check for department codes (e.g., 75, 77, 91, etc.)
        department_codes = ["75", "77", "78", "91", "92", "93", "94", "95"]
        # Use regex to avoid matching parts of other numbers (e.g., '95' in '1955')
        for code in department_codes:
            if re.search(r"\b" + code + r"\b", text_to_check):
                return True

        return False

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
                        "race",
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
                        "age": "",
                        "gender": "",
                        "breed": "",
                        "weight": "",
                        "location": "",
                        "description": "",
                        "full_description": content,
                        "detail_url": dog_url,
                        "image_url": "",
                        "adoption_url": dog_url,  # Use the dog_url as the adoption URL
                    }

                    # Extract basic info from content
                    lines = content.split("\n")
                    for line in lines:
                        line = line.strip()
                        if any(
                            keyword in line.lower() for keyword in ["mâle", "femelle"]
                        ):
                            # Try to extract age, gender, breed from lines like "CHIEN CROISE Mâle - 2 ans"
                            if "mâle" in line.lower():
                                dog_info["gender"] = "Mâle"
                            elif "femelle" in line.lower():
                                dog_info["gender"] = "Femelle"

                            # Extract age
                            if "ans" in line.lower():
                                words = line.split()
                                for i, word in enumerate(words):
                                    if "ans" in word.lower() and i > 0:
                                        dog_info["age"] = words[i - 1] + " ans"
                                        break

                            # Extract breed
                            if any(
                                breed in line.upper()
                                for breed in [
                                    "CHIEN",
                                    "CROISE",
                                    "BERGER",
                                    "LABRADOR",
                                    "GOLDEN",
                                ]
                            ):
                                dog_info["breed"] = (
                                    line.split()[0] if line.split() else ""
                                )

                            break

                    # Only process if we have basic info and it looks like a valid dog
                    if dog_info["name"] and self.is_valid_dog_listing(dog_info):
                        # Score the dog instead of filtering
                        scoring_result = self.score_dog(dog_info)
                        dog_info["score"] = scoring_result["total_score"]
                        dog_info["score_details"] = scoring_result["score_details"]
                        dog_info["breed_score"] = scoring_result["breed_score"]
                        dog_info["cat_score"] = scoring_result["cat_score"]
                        dog_info["temperament_score"] = scoring_result[
                            "temperament_score"
                        ]

                        dogs.append(dog_info)
                        self.logger.info(
                            f"Added dog: {dog_info['name']} (Score: {dog_info['score']}/120)"
                        )

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
                    if dog_info["name"] and self.is_valid_dog_listing(dog_info):
                        if dog_info["detail_url"]:
                            dog_info["full_description"] = self.get_full_description(
                                dog_info["detail_url"]
                            )

                        # Score the dog instead of filtering
                        scoring_result = self.score_dog(dog_info)
                        dog_info["score"] = scoring_result["total_score"]
                        dog_info["score_details"] = scoring_result["score_details"]
                        dog_info["breed_score"] = scoring_result["breed_score"]
                        dog_info["cat_score"] = scoring_result["cat_score"]
                        dog_info["temperament_score"] = scoring_result[
                            "temperament_score"
                        ]

                        dogs.append(dog_info)
                        self.logger.info(
                            f"Added dog: {dog_info['name']} (Score: {dog_info['score']}/120)"
                        )

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
        """Scrape dogs from chiensadonner.com."""
        all_dogs = []
        base_url = "https://www.chiensadonner.com/ads/"

        region_mapping = {"ile-de-france": "75"}
        # The bot iterates through regions in self.regions. For now, we assume
        # this is not yet implemented and hardcode to ile-de-france.
        regions_to_scrape = ["ile-de-france"]

        for region in regions_to_scrape:
            location_code = region_mapping.get(region)
            if not location_code:
                self.logger.warning(
                    f"No location code for region '{region}', skipping."
                )
                continue

            # Scrape up to 5 pages
            for page_num in range(1, 6):
                # The new URL for the 'Île-de-France' region is: `https://www.chiensadonner.com/ads/?s=&location=75&scat=0&lat=0&lng=0&radius=80&st=ad_listing`
                url = f"{base_url}?s=&location={location_code}&scat=0&lat=0&lng=0&radius=80&st=ad_listing&paged={page_num}"

                soup = self.get_page(url)
                if not soup:
                    # This indicates a 404 or other error, so stop paginating
                    self.logger.info(
                        f"Stopping pagination for region '{region}' due to an error on page {page_num}."
                    )
                    break

                dog_elements = soup.select("article.listing-item")
                if not dog_elements:
                    if page_num > 1:
                        self.logger.info(
                            f"No more dogs found for region '{region}' on page {page_num}. Stopping."
                        )
                        break  # No more pages for this region
                    continue

                self.logger.info(
                    f"Found {len(dog_elements)} potential dogs on page {page_num} for region '{region}'"
                )

                for element in dog_elements:
                    dog_info = self.extract_dog_info_chiensadonner(element)
                    if dog_info:
                        all_dogs.append(dog_info)
                        self.logger.info(
                            f"Added dog from chiensadonner.com: {dog_info['name']} (Score: {dog_info.get('score', 'N/A')}/120)"
                        )
        return all_dogs

    def extract_dog_info_chiensadonner(self, dog_element) -> Optional[Dict]:
        """Extract dog info from chiensadonner.com listing."""
        try:
            dog_info = {
                "name": "Unknown",
                "breed": "",
                "age": "",
                "gender": "",
                "location": "",
                "description": "",
                "full_description": "",
                "size": "",
                "image_url": "",
                "contact_info": "",
                "detail_url": "",
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

            # Get breed and full description from detail page
            if dog_info["detail_url"]:
                detail_soup = self.get_page(dog_info["detail_url"])
                if not detail_soup:
                    self.logger.error(
                        f"Failed to fetch detail page: {dog_info['detail_url']}"
                    )
                    return None

                # 1. Breed Extraction
                breed_element = detail_soup.select_one("span.entry-category a")
                if breed_element:
                    dog_info["breed"] = breed_element.get_text(strip=True)

                # 2. Description Extraction
                description_element = detail_soup.select_one(
                    "section#cp_widget_listing_content-2"
                )
                if description_element:
                    dog_info["full_description"] = description_element.get_text(
                        strip=True
                    )
                else:
                    self.logger.warning(
                        f"Could not find description for {dog_info['detail_url']}"
                    )

            # Extract other details from the full description
            text_content = (
                dog_info["name"] + " " + dog_info["full_description"]
            ).lower()

            # Location is often in the title or a specific element
            location_element = dog_element.select_one("[data-address]")
            if location_element:
                dog_info["location"] = location_element["data-address"]
            else:
                # Fallback to searching in text
                location_match = re.search(
                    r"\b(paris|île-de-france|idf|75|77|78|91|92|93|94|95)\b",
                    text_content,
                    re.IGNORECASE,
                )
                if location_match:
                    dog_info["location"] = location_match.group(0)

            # Gender
            if "mâle" in text_content:
                dog_info["gender"] = "Mâle"
            elif "femelle" in text_content:
                dog_info["gender"] = "Femelle"

            # Age
            age_match = re.search(r"(\d+)\s*an(s)?", text_content)
            if age_match:
                dog_info["age"] = f"{age_match.group(1)} ans"
            else:
                age_match_months = re.search(r"(\d+)\s*mois", text_content)
                if age_match_months:
                    dog_info["age"] = f"{age_match_months.group(1)} mois"

            # 5. Scoring
            score_info = self.score_dog(dog_info)
            dog_info["score"] = score_info["total_score"]
            dog_info["score_details"] = score_info["score_details"]

            return dog_info

        except Exception as e:
            self.logger.warning(
                f"Error extracting dog info from chiensadonner.com: {e}"
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
                gender = dog.get("gender", "Unknown")
                age = dog.get("age", "Unknown age")
                breed = dog.get("breed", "Unknown breed")

                # Color coding based on score
                if score >= 80:
                    score_indicator = "🟢 EXCELLENT"
                elif score >= 60:
                    score_indicator = "🟡 GOOD"
                elif score >= 40:
                    score_indicator = "🟠 FAIR"
                else:
                    score_indicator = "🔴 POOR"

                print(
                    f"\n{i}. {name} ({gender}, {age}) - {score_indicator} ({score}/120)"
                )
                print(f"   Breed: {breed}")
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
