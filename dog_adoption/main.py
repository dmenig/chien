from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

import schedule

# Support both package execution (python -m dog_adoption.main) and direct script
# execution (python dog_adoption/main.py) by providing import fallbacks.
try:  # Package context
    from .core import CoreMixin
    from .secondechance import SecondeChanceMixin
    from .chiensadonner import ChiensADonnerMixin
    from .crocsmignons import CrocsMignonsMixin
    from .happydogsforever import HappyDogsForeverMixin
    from .rememberme import RememberMeMixin
    from .larchedekala import LarcheDeKalaMixin
    from .happytogether import HappyTogetherMixin
except ImportError:  # Direct script context
    import os
    import sys

    sys.path.append(os.path.dirname(__file__))
    from core import CoreMixin
    from secondechance import SecondeChanceMixin
    from chiensadonner import ChiensADonnerMixin
    from crocsmignons import CrocsMignonsMixin
    from happydogsforever import HappyDogsForeverMixin
    from rememberme import RememberMeMixin
    from larchedekala import LarcheDeKalaMixin
    from happytogether import HappyTogetherMixin


class DogAdoptionBot(
    CoreMixin,
    SecondeChanceMixin,
    ChiensADonnerMixin,
    CrocsMignonsMixin,
    LarcheDeKalaMixin,
    RememberMeMixin,
    HappyDogsForeverMixin,
    HappyTogetherMixin,
):
    def __init__(self, base_url: str = "https://www.secondechance.org"):
        CoreMixin.__init__(self, base_url=base_url)

    def scrape_all_sources(self) -> List[Dict]:
        all_dogs: List[Dict] = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_source = {
                executor.submit(self.scrape_secondechance): "secondechance",
                executor.submit(self.scrape_chiensadonner): "chiensadonner",
                executor.submit(self.scrape_crocsmignons): "crocsmignons",
                executor.submit(self.scrape_larchedekala): "larchedekala",
                executor.submit(self.scrape_rememberme): "rememberme",
                executor.submit(self.scrape_happydogsforever): "happydogsforever",
                executor.submit(self.scrape_happytogether): "happytogether",
            }
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    dogs = future.result()
                    all_dogs.extend(dogs)
                    self.logger.info("Found %d dogs from %s", len(dogs), source)
                except Exception as exc:
                    self.logger.error(f"{source} generated an exception: {exc}")
        self.logger.info("Total dogs scraped from all sources: %d", len(all_dogs))
        unique_dogs = self._deduplicate_dogs(all_dogs)
        self._score_dogs_concurrently(unique_dogs)
        unique_dogs.sort(key=lambda x: x.get("score", 0), reverse=True)
        self.logger.info("Total unique dogs from all sources: %d", len(unique_dogs))
        return unique_dogs

    def _deduplicate_dogs(self, dogs: List[Dict]) -> List[Dict]:
        unique_dogs: List[Dict] = []
        seen_dogs = set()
        for dog in dogs:
            dog_key = (dog.get("name", "").lower(), dog.get("detail_url", ""))
            if dog_key not in seen_dogs:
                seen_dogs.add(dog_key)
                unique_dogs.append(dog)
        return unique_dogs

    def _score_dogs_concurrently(self, dogs: List[Dict]):
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_dog = {
                executor.submit(self.score_dog_with_gemini, dog): dog for dog in dogs
            }
            for future in as_completed(future_to_dog):
                dog = future_to_dog[future]
                try:
                    scoring_result = future.result()
                    dog.update(scoring_result)
                except Exception as exc:
                    self.logger.error(
                        f"Dog {dog.get('name')} generated an exception during scoring: {exc}"
                    )
                    dog["score"] = -1
                    dog["score_details"] = ["Scoring failed"]

    def start_scheduler(self):
        schedule.every().day.at("09:00").do(self.run_daily_scrape)

    def run_daily_scrape(self):
        self.logger.info("Starting daily dog scraping job")
        dogs = self.scrape_all_sources()
        if dogs:
            for dog in dogs:
                dogs.sort(key=lambda x: x.get("score", 0), reverse=True)
            self.save_data(dogs)
            print(f"\n🐕 FOUND {len(dogs)} DOGS IN PARIS REGION")
            print("📊 Ranked by apartment suitability & cat compatibility:")
            print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            excellent_dogs = [dog for dog in dogs if dog.get("score", 0) >= 50][:20]
            if not excellent_dogs:
                print("\nNo dogs scored 80 or higher in this run.")
            for i, dog in enumerate(excellent_dogs, 1):
                score = dog.get("score", 0)
                name = dog.get("name", "Unknown")
                score_indicator = "🟢 EXCELLENT"
                print(f"\n{i}. {name} - {score_indicator} ({score}/100)")
                print(f"   Score breakdown: {', '.join(dog.get('score_details', []))}")
                print(f"   🔗 {dog.get('detail_url', 'No URL')}")
                if dog.get("image_url"):
                    print(f"   🖼️ Image: {dog['image_url']}")
        else:
            print("\n⚠️  No dogs found")
            print("💡 Try checking the site manually or expand search to other regions")
        self.logger.info("Daily scraping job completed")
        # Print cache stats collected during scraping
        try:
            self.print_cache_stats()
        except Exception:
            pass


def main():
    bot = DogAdoptionBot()
    bot.run_daily_scrape()
    # Uncomment to start daily scheduler
    # bot.start_scheduler()


if __name__ == "__main__":
    main()
