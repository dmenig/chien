import time
from datetime import datetime
from typing import Dict, List, Optional

from bs4 import BeautifulSoup


class RememberMeMixin:
    def scrape_rememberme(self) -> List[Dict]:
        self.logger.info("Scraping from remembermefrance.org")
        all_dogs: List[Dict] = []
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
        try:
            link_tag = article_soup.find("a", href=True)
            if not link_tag:
                return None
            detail_url = link_tag["href"]
            name_tag = article_soup.find("h3", class_="pet-title")
            name = name_tag.get_text(strip=True) if name_tag else "Unknown"
            # Use cache to avoid re-downloading on subsequent runs
            cached_desc = self.get_cached_description(detail_url)
            if cached_desc:
                full_description = cached_desc
                try:
                    self.stats_inc("rememberme", True)
                except Exception:
                    pass
            else:
                detail_soup = self.get_page(detail_url)
                full_description = ""
                if detail_soup:
                    content_area = detail_soup.find("div", class_="pet-description")
                    if content_area:
                        full_description = content_area.get_text(
                            separator="\n", strip=True
                        )
                    else:
                        full_description = detail_soup.get_text(
                            separator="\n", strip=True
                        )
                    if full_description:
                        self.set_cached_description(
                            detail_url, full_description, name=name
                        )
                        try:
                            self.stats_inc("rememberme", False)
                        except Exception:
                            pass
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
