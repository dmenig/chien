import json
import logging
import importlib.util
import os

# Load modules directly from files to avoid importing the package (which triggers other scrapers)
BASE_DIR = os.path.dirname(__file__)
CORE_PATH = os.path.join(BASE_DIR, "core.py")
RESEAU_PATH = os.path.join(BASE_DIR, "reseau_adoption.py")


def load_module_from_path(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


core_mod = load_module_from_path("core", CORE_PATH)
reseau_mod = load_module_from_path("reseau_adoption", RESEAU_PATH)


class TestBot(core_mod.CoreMixin, reseau_mod.ReseauAdoptionMixin):
    def __init__(self):
        core_mod.CoreMixin.__init__(self)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bot = TestBot()
    dogs = bot.scrape_reseauadoption()
    summary = {
        "count": len(dogs),
        "sample": [
            {"name": d.get("name"), "detail_url": d.get("detail_url")}
            for d in dogs[:10]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
