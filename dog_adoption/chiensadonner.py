from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin


class ChiensADonnerMixin:
    def scrape_chiensadonner(self) -> List[Dict]:
        all_dogs: List[Dict] = []
        base_url = "https://www.chiensadonner.com/"
        ile_de_france_departments = ["75", "77", "78", "91", "92", "93", "94", "95"]
        for location_code in ile_de_france_departments:
            current_url = f"{base_url}ads/?s=&location={location_code}&scat=0&lat=0&lng=0&radius=80&st=ad_listing"
            page_num = 1
            while current_url and page_num <= 5:
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
                next_page_element = soup.select_one("a.next.page-numbers")
                if next_page_element and next_page_element.get("href"):
                    current_url = next_page_element["href"]
                else:
                    current_url = None
                page_num += 1
        return all_dogs

    def extract_dog_info_chiensadonner(self, dog_element) -> Optional[Dict]:
        try:
            dog_info: Dict = {
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
                    dog_info["full_description"] = dog_element.get_text(
                        separator="\n", strip=True
                    )
            return dog_info
        except Exception as e:
            self.logger.warning(
                f"Error extracting dog info from chiensadonner.com: {e}"
            )
            return None


