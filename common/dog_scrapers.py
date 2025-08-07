import logging
from typing import List, Dict, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import requests
import json
import time

from common.web import get_page_with_selenium

logger = logging.getLogger(__name__)


def scrape_secondechance(bot) -> List[Dict]:
    """Scrape dogs from secondechance.org Paris region."""
    all_dogs = []
    base_url = "https://www.secondechance.org/animaux/chiens?field_animal_localisation_target_id=2"
    visited_urls = set()
    urls_to_visit = [base_url]

    while urls_to_visit:
        current_url = urls_to_visit.pop(0)
        if current_url in visited_urls:
            continue

        visited_urls.add(current_url)
        logger.info(f"Scraping from secondechance.org: {current_url}")

        dogs, soup = bot.scrape_dogs_page_filtered(current_url)
        if dogs:
            all_dogs.extend(dogs)

        if soup:
            pagination_urls = bot.find_pagination_urls(soup, current_url)
            for url in pagination_urls:
                if url not in visited_urls:
                    urls_to_visit.append(url)

        if len(visited_urls) >= 10:
            break

    return all_dogs


def scrape_chiensadonner(bot) -> List[Dict]:
    """Scrape dogs from chiensadonner.com for all Ile-de-France."""
    all_dogs = []
    base_url = "https://www.chiensadonner.com/annonces/ile-de-france/"
    page_num = 1

    while page_num <= 5:  # Limit to 5 pages
        if page_num == 1:
            current_url = base_url
        else:
            current_url = f"{base_url}page/{page_num}/"

        logger.info(
            f"Scraping chiensadonner page {page_num} for Ile-de-France: {current_url}"
        )
        soup = bot.get_page(current_url)
        if not soup:
            logger.info(
                f"Stopping pagination for Ile-de-France due to an error on page {page_num}."
            )
            break

        dog_elements = soup.select("article.listing-item")
        if not dog_elements:
            if page_num > 1:
                logger.info(
                    f"No more dogs found for Ile-de-France on page {page_num}. Stopping."
                )
            break

        logger.info(
            f"Found {len(dog_elements)} potential dogs on page {page_num} for Ile-de-France"
        )

        for element in dog_elements:
            dog_info = bot.extract_dog_info_chiensadonner(element)
            if dog_info:
                all_dogs.append(dog_info)

        page_num += 1

    return all_dogs


def scrape_crocsmignons(bot) -> List[Dict]:
    """Scrape dogs from latribudescrocsmignons.com."""
    all_dogs = []
    base_url = "https://www.latribudescrocsmignons.com/a-l-adoption/"
    logger.info(f"Scraping from {base_url}")

    try:
        soup = bot.get_page(base_url)
        if not soup:
            return []

        dog_links = []
        link_elements = soup.select("a.elementor-post__thumbnail__link")
        for link in link_elements:
            href = link.get("href")
            if href and "/animal/" in href:
                dog_links.append(href)

        logger.info(f"Found {len(dog_links)} potential dogs")

        for dog_url in dog_links:
            dog_info = bot.extract_dog_info_crocsmignons(dog_url)
            if dog_info:
                all_dogs.append(dog_info)

    except Exception as e:
        logger.error(f"Error scraping latribudescrocsmignons: {e}")

    return all_dogs


def scrape_happydogsforever(bot) -> List[Dict]:
    """Scrape dogs from happydogsforever.com."""
    all_dogs = []
    base_url = "https://www.happydogsforever.com/a-l-adoption"
    logger.info(f"Scraping from {base_url}")

    try:
        html_content = get_page_with_selenium(base_url)
        soup = BeautifulSoup(html_content, "html.parser")
        dog_elements = soup.select("div[data-testid='mesh-container-content']")

        logger.info(f"Found {len(dog_elements)} potential dog sections")

        for element in dog_elements:
            dog_info = bot.extract_dog_info_happydogsforever(element)
            if dog_info:
                all_dogs.append(dog_info)

    except Exception as e:
        logger.error(f"Error scraping happydogsforever: {e}")

    return all_dogs


def scrape_rememberme(bot) -> List[Dict]:
    """Scrape dogs from remembermefrance.org."""
    all_dogs = []
    base_url = "https://www.remembermefrance.org/nos-chiens-a-ladoption/"
    logger.info(f"Scraping from {base_url}")

    soup = bot.get_page(base_url)
    if not soup:
        return []

    dog_elements = soup.select("div.jet-engine-listing-item")
    logger.info(f"Found {len(dog_elements)} potential dogs")

    for element in dog_elements:
        dog_info = bot.extract_dog_info_rememberme(element)
        if dog_info:
            all_dogs.append(dog_info)

    return all_dogs


def scrape_larchedekala(bot) -> List[Dict]:
    """Scrape dogs from larchedekala.fr."""
    all_dogs = []
    base_url = "https://www.larchedekala.fr/nos-animaux-a-ladoption/"
    logger.info(f"Scraping from {base_url}")

    soup = bot.get_page(base_url)
    if not soup:
        return []

    elements = soup.select("div[data-webshop-product]")
    logger.info(f"Found {len(elements)} potential dogs")

    for element in elements:
        try:
            product_data = element["data-webshop-product"]
            product_info = json.loads(product_data)
            if "chien" in product_info.get("name", "").lower():
                detail_url = urljoin(base_url, element.find("a")["href"])
                dog_info = bot.extract_dog_info_larchedekala(detail_url)
                if dog_info:
                    all_dogs.append(dog_info)
        except (KeyError, json.JSONDecodeError) as e:
            logger.warning(f"Could not parse dog data from larchedekala: {e}")

    return all_dogs


def scrape_happytogether(bot) -> List[Dict]:
    """Scrape dogs from happytogether.forumactif.com."""
    all_dogs = []
    forum_sections = {
        "En Roumanie": "/f16-en-roumanie",
        "En Famille d'Accueil": "/f24-en-famille-d-accueil",
    }

    for section_name, section_path in forum_sections.items():
        logger.info(f"\nScraping section: {section_name}")
        forum_url = urljoin("https://happytogether.forumactif.com/", section_path)
        topics = bot.get_forum_topics_happytogether(forum_url)

        for i, topic in enumerate(topics[:10]):  # Limit to first 10 for testing
            logger.info(
                f"Scraping topic {i + 1}/{min(10, len(topics))}: {topic['title']}"
            )
            dog_details = bot.get_topic_details_happytogether(topic["url"])
            if dog_details:
                all_dogs.append(dog_details)

    return all_dogs
