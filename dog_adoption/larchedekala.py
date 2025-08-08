import json
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin


class LarcheDeKalaMixin:
    def scrape_larchedekala(self) -> List[Dict]:
        self.logger.info("Scraping from larchedekala.fr")
        all_dogs: List[Dict] = []
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
                        "Warning: Could not decode JSON for a product on larchedekala.fr."
                    )
                    continue
        return all_dogs

    def extract_dog_info_larchedekala(self, detail_url: str) -> Optional[Dict]:
        try:
            dog_info: Dict = {
                "name": "Unknown",
                "detail_url": detail_url,
                "full_description": "",
                "scraped_date": datetime.now().isoformat(),
                "source": "larchedekala.fr",
            }
            # Try cache first
            cached_desc = self.get_cached_description(dog_info["detail_url"])
            cached_name = self.get_cached_name(dog_info["detail_url"])
            if cached_desc:
                dog_info["name"] = cached_name or dog_info["name"]
                dog_info["full_description"] = cached_desc
                try:
                    self.stats_inc("larchedekala", True)
                except Exception:
                    pass
            else:
                detail_soup = self.get_page(dog_info["detail_url"])
                if not detail_soup:
                    self.logger.warning(f"Could not fetch detail page for {detail_url}")
                    return None
                name_element = detail_soup.find("h1", class_="product-page__heading")
                if name_element:
                    dog_info["name"] = name_element.get_text(strip=True)
                description_element = detail_soup.find(
                    "div", class_="product-page__description"
                )
                if description_element:
                    full_text = description_element.get_text(separator="\n", strip=True)
                else:
                    full_text = detail_soup.get_text(separator="\n", strip=True)
                dog_info["full_description"] = full_text
                if full_text:
                    self.set_cached_description(
                        dog_info["detail_url"], full_text, name=dog_info["name"]
                    )
                    try:
                        self.stats_inc("larchedekala", False)
                    except Exception:
                        pass
            return dog_info
        except Exception as e:
            self.logger.warning(f"Error extracting dog info from larchedekala.fr: {e}")
            return None
