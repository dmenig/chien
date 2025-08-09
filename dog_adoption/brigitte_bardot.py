from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup


class BrigitteBardotMixin:
    def scrape_brigitte_bardot(self) -> List[Dict]:
        """Scrape the Fondation Brigitte Bardot adoption listing for medium-size dogs.
        The listing often contains dog summary blocks; for each block we try to
        extract a name, detail URL and a full description (or fallback to the
        block text).
        """
        self.logger.info("Scraping from fondationbrigittebardot.fr")
        all_dogs: List[Dict] = []
        url = "https://adoption.fondationbrigittebardot.fr/adopter-un-chien.php?a=chien-de-taille-moyenne"
        try:
            soup = self.get_page(url)
            if not soup:
                return all_dogs

            # The listing uses a grid with dog cards under <div id="grid">.
            # Each card has classes like "all box col2" and contains a
            # link to a detail page (href contains "chien_a_adopter.php?id=").
            dog_cards = []
            grid = soup.select_one("#grid")
            if grid:
                # select direct card containers
                dog_cards = grid.select("div.all.box, div.box")
            else:
                # fallback: find any box-like elements
                dog_cards = soup.select("div.all.box, div.box, div.box-content")

            for element in dog_cards:
                try:
                    dog_info = self.extract_dog_info_brigitte_bardot(element)
                    if dog_info:
                        # Only include if we have a detail url or a clear name
                        if (
                            not dog_info.get("detail_url")
                            and dog_info.get("name") == "Unknown"
                        ):
                            continue
                        # Avoid obvious duplicates by detail_url
                        duplicate = False
                        for existing in all_dogs:
                            if existing.get("detail_url") and existing.get(
                                "detail_url"
                            ) == dog_info.get("detail_url"):
                                duplicate = True
                                break
                        if not duplicate:
                            all_dogs.append(dog_info)
                except Exception as e:
                    self.logger.warning(f"Error processing BB element: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Error scraping fondationbrigittebardot.fr: {e}")
        self.logger.info(
            f"Scraped {len(all_dogs)} dogs from fondationbrigittebardot.fr"
        )
        return all_dogs

    def extract_dog_info_brigitte_bardot(self, element_or_soup) -> Optional[Dict]:
        try:
            dog_info: Dict = {
                "name": "Unknown",
                "detail_url": "",
                "full_description": "",
                "scraped_date": datetime.now().isoformat(),
                "source": "fondationbrigittebardot.fr",
            }

            # If a string URL was passed, fetch that page
            if isinstance(element_or_soup, str):
                detail_url = element_or_soup
                dog_info["detail_url"] = detail_url
                cached = self.get_cached_description(detail_url)
                if cached:
                    dog_info["full_description"] = cached
                    dog_info["name"] = (
                        self.get_cached_name(detail_url) or dog_info["name"]
                    )
                    try:
                        self.stats_inc("brigittebardot", True)
                    except Exception:
                        pass
                    return dog_info
                soup = self.get_page(detail_url)
                if soup:
                    dog_info["full_description"] = soup.get_text(
                        separator="\n", strip=True
                    )
                    title = soup.find("title")
                    if title:
                        dog_info["name"] = (
                            title.get_text(strip=True).split("|")[0].strip()
                        )
                        self.set_cached_description(
                            detail_url,
                            dog_info["full_description"],
                            name=dog_info["name"],
                        )
                    return dog_info
                return None

            element = element_or_soup
            # Name: search for heading inside element
            name_elem = None
            for tag in ["h1", "h2", "h3", "h4"]:
                name_elem = element.find(tag)
                if name_elem and name_elem.get_text(strip=True):
                    break
            if name_elem:
                name_text = name_elem.get_text(strip=True)
                # strip age in parentheses if present
                if "(" in name_text:
                    dog_info["name"] = name_text.split("(")[0].strip()
                    # try to capture age inside parentheses
                    try:
                        age_part = name_text.split("(")[1].split(")")[0].strip()
                        dog_info["age"] = age_part
                    except Exception:
                        pass
                else:
                    dog_info["name"] = name_text

            # Detail link if present
            # Prefer the specific detail link that contains "chien_a_adopter.php"
            link = None
            for a in element.find_all("a", href=True):
                if "chien_a_adopter.php" in a["href"]:
                    link = a
                    break
            if not link:
                link = element.find("a", href=True)
            if link:
                href = link["href"]
                if href.startswith("http"):
                    dog_info["detail_url"] = href
                else:
                    dog_info["detail_url"] = urljoin(
                        "https://adoption.fondationbrigittebardot.fr", href
                    )

            # Try cache first for detail URL; we'll still fetch detail page to get
            # richer description and media if needed.
            if dog_info["detail_url"]:
                cached_desc = self.get_cached_description(dog_info["detail_url"])
                cached_name = self.get_cached_name(dog_info["detail_url"])
                if cached_desc:
                    dog_info["full_description"] = cached_desc
                    if cached_name:
                        dog_info["name"] = cached_name
                    try:
                        self.stats_inc("brigittebardot", True)
                    except Exception:
                        pass

                # Fetch the detail page to get the full description
                detail_soup = (
                    self.get_page(dog_info["detail_url"])
                    if dog_info["detail_url"]
                    else None
                )
                if detail_soup:
                    # Prefer meta og:description then meta description
                    og_desc = detail_soup.find("meta", property="og:description")
                    meta_desc = detail_soup.find("meta", attrs={"name": "description"})
                    if og_desc and og_desc.get("content"):
                        full_text = og_desc.get("content").strip()
                    elif meta_desc and meta_desc.get("content"):
                        full_text = meta_desc.get("content").strip()
                    else:
                        # Try to find a main description block
                        selectors = [
                            ".post-content",
                            ".content",
                            ".entry",
                            "#content",
                            ".main-page",
                        ]
                        full_text = ""
                        for sel in selectors:
                            node = detail_soup.select_one(sel)
                            if node:
                                txt = node.get_text(separator="\n", strip=True)
                                if txt and len(txt) > len(full_text):
                                    full_text = txt
                        if not full_text:
                            full_text = detail_soup.get_text(separator="\n", strip=True)

                    if full_text:
                        # prefer fetched full_text when it's richer than cached or element text
                        if len(full_text) > len(dog_info.get("full_description", "")):
                            dog_info["full_description"] = full_text
                        if dog_info.get("name") == "Unknown":
                            title = detail_soup.find("title")
                            if title:
                                dog_info["name"] = (
                                    title.get_text(strip=True).split("|")[0].strip()
                                )
                        self.set_cached_description(
                            dog_info["detail_url"],
                            dog_info["full_description"],
                            name=dog_info["name"],
                        )
                        try:
                            self.stats_inc("brigittebardot", False)
                        except Exception:
                            pass

                    # Media handling disabled

            # If still missing a full description, fallback to element text
            if not dog_info.get("full_description"):
                text = element.get_text(separator="\n", strip=True)
                dog_info["full_description"] = text

            if dog_info["name"] != "Unknown" or dog_info["full_description"]:
                return dog_info
            return None
        except Exception as e:
            self.logger.warning(
                f"Error extracting dog info from brigitte bardot site: {e}"
            )
            return None
