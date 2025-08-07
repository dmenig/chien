import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


def get_page_with_selenium(url: str) -> str:
    """
    Fetch page content with Selenium for dynamic content.
    """
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        print(f"Loading page: {url}")
        driver.get(url)
        # Wait for initial content to load
        time.sleep(3)

        # Scroll to load all content
        last_height = driver.execute_script("return document.body.scrollHeight")
        scroll_count = 0
        while True:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height or scroll_count > 5:
                break
            last_height = new_height
            scroll_count += 1

        # Wait a bit more for any remaining content to load
        time.sleep(2)

        return driver.page_source
    finally:
        driver.quit()
