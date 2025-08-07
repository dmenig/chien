from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup


class HappyDogsForeverMixin:
    def scrape_happydogsforever(self) -> List[Dict]:
        self.logger.info("Scraping from happydogsforever.com")
        all_dogs: List[Dict] = []
        url = "https://www.happydogsforever.com/nos-chiens-chats"
        try:
            page_src = self.get_page_with_selenium(url)
            if not page_src:
                return all_dogs
            soup = BeautifulSoup(page_src, "lxml")
            category_links: List[str] = []
            category_selectors = [
                "a[href*='nos-chiens-chats']",
                "a[href*='nos-chiens-a-l-adoption']",
            ]
            for selector in category_selectors:
                links = soup.select(selector)
                for link in links:
                    href = link.get("href")
                    if not href:
                        continue
                    if href.startswith("http"):
                        full_url = href
                    else:
                        full_url = urljoin("https://www.happydogsforever.com", href)
                    if (
                        full_url not in category_links
                        and "les-chats" not in full_url.lower()
                        and "ils-sont-adoptes" not in full_url.lower()
                    ):
                        category_links.append(full_url)
                        self.logger.info(f"Found category link: {full_url}")
            self.logger.info(f"Found {len(category_links)} category links to follow")
            for category_url in category_links:
                try:
                    self.logger.info(f"Scraping category: {category_url}")
                    page_src = self.get_page_with_selenium(category_url)
                    if not page_src:
                        continue
                    category_soup = BeautifulSoup(page_src, "lxml")
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
                    unique_dog_elements = []
                    for element in dog_elements:
                        if element not in unique_dog_elements:
                            unique_dog_elements.append(element)
                    self.logger.info(
                        f"Found {len(unique_dog_elements)} unique potential dog elements in category"
                    )
                    for element in unique_dog_elements:
                        try:
                            dog_info = self.extract_dog_info_happydogsforever(element)
                            if dog_info and dog_info["name"] != "Unknown":
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
        self.logger.info(f"Scraped {len(all_dogs)} dogs from happydogsforever.com")
        return all_dogs

    def extract_dog_info_happydogsforever(self, dog_element) -> Optional[Dict]:
        try:
            dog_info: Dict = {
                "name": "Unknown",
                "detail_url": "",
                "full_description": "",
                "scraped_date": datetime.now().isoformat(),
                "source": "happydogsforever.com",
            }
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
            for selector in name_selectors:
                name_elem = dog_element.select_one(selector)
                if name_elem:
                    name_text = name_elem.get_text(strip=True)
                    if (
                        name_text
                        and len(name_text) > 1
                        and name_text.lower()
                        not in ["dog", "pet", "animal", "chien", "chat"]
                    ):
                        dog_info["name"] = name_text
                        break
            if dog_info["name"] == "Unknown":
                element_text = dog_element.get_text(strip=True)
                if element_text and len(element_text) > 1:
                    lines = element_text.split("\n")
                    if lines:
                        first_line = lines[0].strip()
                        if first_line and len(first_line) > 1:
                            dog_info["name"] = first_line[:50]
            link_elem = dog_element.find("a", href=True)
            if link_elem:
                href = link_elem["href"]
                if href.startswith("http"):
                    dog_info["detail_url"] = href
                else:
                    dog_info["detail_url"] = urljoin(
                        "https://www.happydogsforever.com", href
                    )
            dog_info["full_description"] = dog_element.get_text(
                separator="\n", strip=True
            )
            if dog_info["detail_url"]:
                detail_soup = self.get_page(dog_info["detail_url"])
                if detail_soup:
                    detail_text = detail_soup.get_text(separator="\n", strip=True)
                    if len(detail_text) > len(dog_info["full_description"]):
                        dog_info["full_description"] = detail_text
            if dog_info["name"] != "Unknown" or dog_info["full_description"]:
                return dog_info
            return None
        except Exception as e:
            self.logger.warning(
                f"Error extracting dog info from happydogsforever.com: {e}"
            )
            return None
