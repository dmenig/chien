from datetime import datetime
from typing import Dict, List
from urllib.parse import urljoin

from bs4 import BeautifulSoup


class HappyTogetherMixin:
    def scrape_happytogether(self) -> List[Dict]:
        self.logger.info("Scraping from happytogether.forumactif.com")
        all_dogs: List[Dict] = []
        forum_sections = {
            "En Roumanie": "/f16-en-roumanie",
            "En Famille d'Accueil": "/f24-en-famille-d-accueil",
        }
        base_url = "https://happytogether.forumactif.com"
        for section_name, section_path in forum_sections.items():
            self.logger.info(f"Scraping section: {section_name}")
            forum_url = urljoin(base_url, section_path)
            topics = self.get_forum_topics_happytogether(forum_url)
            for i, topic in enumerate(topics[:10]):
                self.logger.info(
                    f"Scraping topic {i + 1}/{min(10, len(topics))}: {topic['title']}"
                )
                dog_details = self.get_topic_details_happytogether(topic["url"])
                if dog_details:
                    dog_details["source"] = "happytogether.forumactif.com"
                    all_dogs.append(dog_details)
        self.logger.info(
            f"Scraped {len(all_dogs)} dogs from happytogether.forumactif.com"
        )
        return all_dogs

    # NOTE: Do not override the selenium renderer from CoreMixin here to avoid recursion.
    # Use CoreMixin.get_page_with_selenium directly via method resolution order.

    def get_forum_topics_happytogether(self, forum_url):
        try:
            html_content = self.get_page_with_selenium(forum_url)
            soup = BeautifulSoup(html_content, "html.parser")
            topics: List[Dict] = []
            topic_elements = soup.select("ul.topiclist li.row")
            for element in topic_elements:
                topic_link = element.select_one("a.topictitle")
                if topic_link:
                    topic_url = urljoin(
                        "https://happytogether.forumactif.com", topic_link.get("href")
                    )
                    topic_title = topic_link.get_text().strip()
                    last_post_elem = element.select_one(".lastpost")
                    last_post_info = ""
                    if last_post_elem:
                        last_post_info = last_post_elem.get_text().strip()
                    topics.append(
                        {
                            "title": topic_title,
                            "url": topic_url,
                            "last_post": last_post_info,
                            "scraped_date": datetime.now().isoformat(),
                        }
                    )
            self.logger.info(f"Found {len(topics)} topics in forum")
            return topics
        except Exception as e:
            self.logger.error(f"Error getting forum topics: {e}")
            return []

    def get_topic_details_happytogether(self, topic_url):
        try:
            # Use cached description if available to avoid re-rendering via Selenium
            cached_desc = self.get_cached_description(topic_url)
            if cached_desc:
                try:
                    self.stats_inc("happytogether", True)
                except Exception:
                    pass
                soup = BeautifulSoup("", "html.parser")
                title = "Unknown"
                dog_info = {
                    "name": self.extract_dog_name_happytogether(title, cached_desc),
                    "breed": self.extract_breed_happytogether(cached_desc),
                    "age": self.extract_age_happytogether(cached_desc),
                    "gender": self.extract_gender_happytogether(cached_desc),
                    "size": self.extract_size_happytogether(cached_desc),
                    "description": cached_desc[:1000],
                    "full_description": cached_desc,
                    "detail_url": topic_url,
                    "scraped_date": datetime.now().isoformat(),
                }
                return dog_info

            html_content = self.get_page_with_selenium(topic_url)
            soup = BeautifulSoup(html_content, "html.parser")
            title_elem = soup.select_one("h1.page-title, h1.topic-title, h1")
            title = title_elem.get_text().strip() if title_elem else "Unknown"
            content_area = soup.select_one(".post, .content, .post-content, .message")
            full_description = ""
            if content_area:
                full_description = content_area.get_text(separator="\n", strip=True)
            else:
                full_description = soup.get_text(separator="\n", strip=True)
            dog_info = {
                "name": self.extract_dog_name_happytogether(title, full_description),
                "breed": self.extract_breed_happytogether(full_description),
                "age": self.extract_age_happytogether(full_description),
                "gender": self.extract_gender_happytogether(full_description),
                "size": self.extract_size_happytogether(full_description),
                "description": full_description[:1000],
                "full_description": full_description,
                "detail_url": topic_url,
                "scraped_date": datetime.now().isoformat(),
            }
            if full_description:
                self.set_cached_description(
                    topic_url, full_description, name=dog_info["name"]
                )
                try:
                    self.stats_inc("happytogether", False)
                except Exception:
                    pass
            return dog_info
        except Exception as e:
            self.logger.error(f"Error getting topic details: {e}")
            return None

    def extract_dog_name_happytogether(self, title, description):
        if title and " - " in title:
            return title.split(" - ")[0].strip()
        return title or "Unknown"

    def extract_breed_happytogether(self, description):
        breed_keywords = [
            "berger",
            "labrador",
            "golden",
            "chihuahua",
            "bouledogue",
            "carlin",
            "caniche",
            "cavalier",
            "retriever",
            "husky",
        ]
        description_lower = description.lower()
        for keyword in breed_keywords:
            if keyword in description_lower:
                start = description_lower.find(keyword)
                if start > -1:
                    end = min(start + 50, len(description))
                    return description[start:end].strip()
        return ""

    def extract_age_happytogether(self, description):
        import re

        age_patterns = [
            r"(\d+)\s*ans?",
            r"(\d+)\s*mois",
            r"né\s*en\s*(\d{4})",
            r"née\s*en\s*(\d{4})",
        ]
        description_lower = description.lower()
        for pattern in age_patterns:
            match = re.search(pattern, description_lower)
            if match:
                return match.group(0)
        return ""

    def extract_gender_happytogether(self, description):
        description_lower = description.lower()
        if "mâle" in description_lower or "male" in description_lower:
            return "Mâle"
        elif "femelle" in description_lower or "femelle" in description_lower:
            return "Femelle"
        return ""

    def extract_size_happytogether(self, description):
        description_lower = description.lower()
        if "petit" in description_lower:
            return "Petit"
        elif "moyen" in description_lower:
            return "Moyen"
        elif "grand" in description_lower:
            return "Grand"
        return ""
