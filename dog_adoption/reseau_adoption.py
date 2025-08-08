from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup


class ReseauAdoptionMixin:
    def scrape_reseauadoption(self) -> List[Dict]:
        """Scrape dogs from https://reseau-adoption.fr/adoption/liste/chien
        Uses pagination where available and falls back to collecting card-like elements.
        """
        self.logger.info("Scraping from reseau-adoption.fr")
        all_dogs: List[Dict] = []
        base_list_url = "https://reseau-adoption.fr/adoption/liste/chien"
        try:
            page = 1
            visited = set()
            while True:
                # Try common page param; site may also use path-based pagination but this is resilient enough
                url = f"{base_list_url}?page={page}"
                self.logger.info(f"Fetching list page: {url}")
                soup = self.get_page(url)
                if not soup:
                    break

                # Heuristic selectors for card-like elements
                selectors = [
                    "article",
                    ".annonce",
                    ".ad",
                    ".card",
                    ".liste-annonce",
                    ".item",
                    ".ad-item",
                    ".result",
                ]
                dog_elements = []
                for sel in selectors:
                    els = soup.select(sel)
                    if els:
                        dog_elements.extend(els)

                # Fallback: collect parents of links that look like detail links
                if not dog_elements:
                    detail_links = soup.select(
                        "a[href*='/annonce/'], a[href*='/adoption/']"
                    )
                    for a in detail_links:
                        parent = a.find_parent()
                        if parent:
                            dog_elements.append(parent)

                if not dog_elements:
                    self.logger.info(
                        "No dog elements found on page; stopping pagination"
                    )
                    break

                unique_elements = []
                for el in dog_elements:
                    if el not in unique_elements:
                        unique_elements.append(el)

                for el in unique_elements:
                    try:
                        dog_info = self.extract_dog_info_reseauadoption(el)
                        if dog_info and dog_info.get("name", "Unknown") != "Unknown":
                            key = (
                                dog_info.get("name", "").lower(),
                                dog_info.get("detail_url", ""),
                            )
                            if key in visited:
                                continue
                            visited.add(key)
                            all_dogs.append(dog_info)
                    except Exception as e:
                        self.logger.warning(
                            f"Error processing reseau-adoption element: {e}"
                        )

                # Attempt to detect if there is a next page; many sites have rel='next' or a link with text 'Suivant'
                next_link = soup.select_one("a[rel='next']")
                if not next_link:
                    for a in soup.find_all("a", href=True):
                        txt = a.get_text(strip=True).lower()
                        if "suivant" in txt or txt == ">" or "»" in txt:
                            next_link = a
                            break

                if next_link and next_link.get("href"):
                    page += 1
                    continue
                # No detectable next link — stop pagination
                break

        except Exception as e:
            self.logger.error(f"Error scraping reseau-adoption.fr: {e}")

        self.logger.info(f"Scraped {len(all_dogs)} dogs from reseau-adoption.fr")
        return all_dogs

    def extract_dog_info_reseauadoption(self, element) -> Optional[Dict]:
        try:
            dog_info: Dict = {
                "name": "Unknown",
                "detail_url": "",
                "full_description": "",
                "image_url": None,
                "scraped_date": datetime.now().isoformat(),
                "source": "reseau-adoption.fr",
            }

            # Name heuristics
            name_selectors = [
                "h1",
                "h2",
                "h3",
                ".titre",
                ".title",
                ".name",
                ".item-title",
            ]
            for sel in name_selectors:
                name_elem = element.select_one(sel)
                if name_elem:
                    name_text = name_elem.get_text(strip=True)
                    if name_text and len(name_text) > 1:
                        dog_info["name"] = name_text
                        break

            if dog_info["name"] == "Unknown":
                text = element.get_text(strip=True)
                if text and len(text) > 1:
                    first_line = text.split("\n")[0].strip()
                    if first_line:
                        dog_info["name"] = first_line[:60]

            # Detail link
            link_elem = element.find("a", href=True)
            if link_elem:
                href = link_elem["href"]
                if href.startswith("http"):
                    dog_info["detail_url"] = href
                else:
                    dog_info["detail_url"] = urljoin("https://reseau-adoption.fr", href)

            # Short description
            dog_info["full_description"] = element.get_text(separator="\n", strip=True)

            # Try to fetch detail page for longer description if we have a URL
            if dog_info["detail_url"]:
                cached_desc = self.get_cached_description(dog_info["detail_url"])
                cached_name = self.get_cached_name(dog_info["detail_url"])
                if cached_desc:
                    if cached_name:
                        dog_info["name"] = cached_name
                    dog_info["full_description"] = cached_desc
                    try:
                        self.stats_inc("reseau-adoption", True)
                    except Exception:
                        pass
                else:
                    detail_soup = self.get_page(dog_info["detail_url"])
                    if detail_soup:
                        # Prefer specific description containers if present
                        desc_selectors = [
                            ".description",
                            ".desc",
                            ".annonce-description",
                            ".annonce-txt",
                            ".ad-description",
                            ".entry-content",
                            "#description",
                            ".post-content",
                            ".ad-detail__description",
                            ".content",
                        ]
                        best_desc = ""
                        for sel in desc_selectors:
                            node = detail_soup.select_one(sel)
                            if node:
                                txt = node.get_text(separator="\n", strip=True)
                                if txt and len(txt) > len(best_desc):
                                    best_desc = txt

                        # Fallback to paragraphs under main/content area
                        if not best_desc:
                            main_candidates = detail_soup.select(
                                "main, .main, #main, .content, article"
                            )
                            for main_node in main_candidates:
                                paragraphs = main_node.find_all("p")
                                txt = "\n\n".join(
                                    p.get_text(strip=True)
                                    for p in paragraphs
                                    if p.get_text(strip=True)
                                )
                                if txt and len(txt) > len(best_desc):
                                    best_desc = txt

                        # Ultimate fallback: whole page text
                        if not best_desc:
                            best_desc = detail_soup.get_text(separator="\n", strip=True)

                        if len(best_desc) > len(dog_info["full_description"]):
                            dog_info["full_description"] = best_desc

                        # Try to find image URL for the dog
                        try:
                            img_url = self.get_dog_image_url(dog_info["detail_url"])
                            if img_url:
                                dog_info["image_url"] = img_url
                        except Exception:
                            pass

                        if dog_info["full_description"]:
                            self.set_cached_description(
                                dog_info["detail_url"],
                                dog_info["full_description"],
                                name=dog_info["name"],
                            )
                            try:
                                self.stats_inc("reseau-adoption", False)
                            except Exception:
                                pass

            if dog_info["name"] != "Unknown" or dog_info["full_description"]:
                return dog_info
            return None
        except Exception as e:
            self.logger.warning(
                f"Error extracting dog info from reseau-adoption.fr: {e}"
            )
            return None
