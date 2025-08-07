from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup


class SecondeChanceMixin:
    def build_filtered_url(self, broader_search: bool = False) -> str:
        base_url = f"{self.base_url}/animal/adopter-un-chien"
        params = [
            "species=1",
        ]
        if broader_search:
            for region in self.search_regions:
                params.append(f"regions[]={region}")
            self.logger.info("Using broader search across multiple regions")
        else:
            params.append("region=2")
            for dept in self.paris_departments:
                params.append(f"departments[]={dept}")
        filtered_url = f"{base_url}?{'&'.join(params)}"
        self.logger.info(f"Using filtered URL: {filtered_url}")
        return filtered_url

    def scrape_secondechance(self) -> List[Dict]:
        all_dogs: List[Dict] = []
        filtered_url = self.build_filtered_url()
        visited_urls = set()
        urls_to_visit = [filtered_url]
        while urls_to_visit:
            current_url = urls_to_visit.pop(0)
            if current_url in visited_urls:
                continue
            visited_urls.add(current_url)
            self.logger.info(f"Scraping from secondechance.org: {current_url}")
            dogs, soup = self.scrape_dogs_page_filtered(current_url)
            if dogs:
                all_dogs.extend(dogs)
            if soup:
                pagination_urls = self.find_pagination_urls(soup, current_url)
                for url in pagination_urls:
                    if url not in visited_urls:
                        urls_to_visit.append(url)
            if len(visited_urls) >= 10:
                break
        return all_dogs

    def scrape_dogs_page_filtered(self, url: str) -> Tuple[List[Dict], Optional[BeautifulSoup]]:
        soup = self.get_page(url)
        if not soup:
            return [], None
        dogs: List[Dict] = []
        dog_links: List[str] = []
        all_links = soup.find_all("a", href=True)
        for link in all_links:
            href = link.get("href", "")
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
        if dog_links:
            for dog_url in dog_links:
                dog_soup = self.get_page(dog_url)
                if dog_soup:
                    title = dog_soup.find("title")
                    name = title.get_text().strip() if title else "Unknown"
                    content = dog_soup.get_text()
                    dog_info = {
                        "name": name.split("-")[0].strip() if "-" in name else name,
                        "full_description": content,
                        "detail_url": dog_url,
                    }
                    if dog_info["name"]:
                        dogs.append(dog_info)
        if not dogs:
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
        pagination_urls: List[str] = []
        pagination_divs = soup.select("div.pagination")
        if pagination_divs:
            for div in pagination_divs:
                links = div.select("a")
                for link in links:
                    href = link.get("href")
                    if href and "page" in href and "?" in href:
                        if not href.startswith("http"):
                            href = urljoin(base_url, href)
                        pagination_urls.append(href)
        return pagination_urls


