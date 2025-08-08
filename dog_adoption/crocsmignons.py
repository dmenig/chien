from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


class CrocsMignonsMixin:
    def scrape_crocsmignons(self) -> List[Dict]:
        self.logger.info("Scraping from latribudescrocsmignons.com")
        all_dogs: List[Dict] = []
        url = "https://www.latribudescrocsmignons.com/a-l-adoption"
        try:
            page_src = self.get_page_with_selenium(url)
            if not page_src:
                return all_dogs
            soup = BeautifulSoup(page_src, "lxml")
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
        return all_dogs

    def extract_dog_info_crocsmignons(self, detail_url: str) -> Optional[Dict]:
        try:
            dog_info: Dict = {
                "name": "Unknown",
                "detail_url": detail_url,
                "full_description": "",
                "scraped_date": datetime.now().isoformat(),
                "source": "latribudescrocsmignons.com",
            }
            # Try cache first to avoid re-downloading
            cached_desc = self.get_cached_description(dog_info["detail_url"])
            cached_name = self.get_cached_name(dog_info["detail_url"])
            if cached_desc:
                dog_info["name"] = cached_name or dog_info["name"]
                dog_info["full_description"] = cached_desc
                try:
                    self.stats_inc("crocsmignons", True)
                except Exception:
                    pass
            else:
                detail_soup = self.get_page(dog_info["detail_url"])
                if detail_soup:
                    title_element = detail_soup.find("title")
                    if title_element:
                        dog_info["name"] = (
                            title_element.get_text(strip=True).split("|")[0].strip()
                        )
                    full_text = detail_soup.get_text(separator="\n", strip=True)
                    dog_info["full_description"] = full_text
                    self.set_cached_description(
                        dog_info["detail_url"], full_text, name=dog_info["name"]
                    )
                    try:
                        self.stats_inc("crocsmignons", False)
                    except Exception:
                        pass
                else:
                    self.logger.warning(f"Could not fetch detail page for {detail_url}")
                    return None
            return dog_info
        except Exception as e:
            self.logger.warning(
                f"Error extracting dog info from latribudescrocsmignons.com: {e}"
            )
            return None
