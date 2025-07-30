import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
import sys


def get_full_page_html():
    """
    Fetches the full HTML of https://www.latribudescrocsmignons.com/a-l-adoption
    by scrolling to the bottom of the page to load all content.
    """
    url = "https://www.latribudescrocsmignons.com/a-l-adoption"

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.get(url)
        # Wait for the initial page to load
        time.sleep(5)

        # Scroll to the bottom of the page to load all dogs
        last_height = driver.execute_script("return document.body.scrollHeight")
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)  # Wait for new content to load
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        return driver.page_source
    finally:
        driver.quit()


if __name__ == "__main__":
    html_content = get_full_page_html()
    if html_content:
        print(html_content)
    else:
        print("Failed to fetch page content.")
