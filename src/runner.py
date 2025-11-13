thonimport argparse
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, List

# Ensure the src directory is on sys.path so implicit namespace packages work
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

try:
    from extractors.behance_parser import BehanceScraper
    from outputs.exporters import ExportManager, ExportFormatError
except ImportError as exc:
    raise ImportError(
        "Failed to import project modules. "
        "Make sure you're running this script from the project root:\n"
        "  python src/runner.py --keyword 'graphic designer'"
    ) from exc

DEFAULT_CONFIG_PATH = os.path.join(CURRENT_DIR, "config", "settings.example.json")

def configure_logging(verbosity: int) -> None:
    """Configure root logger based on verbosity level."""
    level = logging.INFO
    if verbosity >= 2:
        level = logging.DEBUG
    elif verbosity <= 0:
        level = logging.WARNING

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

def load_settings(path: str) -> Dict[str, Any]:
    """Load JSON settings file; fall back to sensible defaults if missing or invalid."""
    defaults: Dict[str, Any] = {
        "behance_base_url": "https://www.behance.net",
        "delay_range": [1.0, 3.0],
        "max_pages": 5,
        "default_keyword": "graphic designer",
        "default_max_profiles": 50,
        "output_dir": "data",
    }

    if not os.path.exists(path):
        logging.warning("Settings file not found at %s, using built-in defaults.", path)
        return defaults

    try:
        with open(path, "r", encoding="utf-8") as f:
            user_settings = json.load(f)
        if not isinstance(user_settings, dict):
            raise ValueError("Root JSON element must be an object.")
    except Exception as exc:  # noqa: BLE001
        logging.error("Failed to read settings from %s: %s", path, exc)
        logging.info("Falling back to built-in defaults.")
        return defaults

    merged = {**defaults, **user_settings}
    logging.debug("Loaded settings: %s", merged)
    return merged

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Behance Freelancers Search Scraper (Fast and cheap)",
    )
    parser.add_argument(
        "--keyword",
        "-k",
        type=str,
        help="Keyword to search for freelancers (e.g. 'graphic designer').",
    )
    parser.add_argument(
        "--max-profiles",
        "-n",
        type=int,
        help="Maximum number of freelancer profiles to scrape.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=str,
        help="Directory to store output files. Defaults to config value.",
    )
    parser.add_argument(
        "--formats",
        "-f",
        type=str,
        default="json",
        help=(
            "Comma-separated list of output formats. "
            "Supported: json,csv,excel,html (e.g. 'json,csv,excel')."
        ),
    )
    parser.add_argument(
        "--config",
        "-c",
        type=str,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the settings JSON file.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=1,
        help="Increase verbosity (-v info, -vv debug, no -v warnings).",
    )
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    configure_logging(args.verbose)

    settings = load_settings(args.config)

    keyword = args.keyword or settings.get("default_keyword") or "graphic designer"
    max_profiles = args.max_profiles or int(settings.get("default_max_profiles", 50))
    output_dir = args.output_dir or settings.get("output_dir", "data")

    delay_range = settings.get("delay_range", [1.0, 3.0])
    if (
        not isinstance(delay_range, (list, tuple))
        or len(delay_range) != 2
        or not all(isinstance(x, (int, float)) for x in delay_range)
    ):
        logging.warning("Invalid delay_range in settings; using default [1.0, 3.0].")
        delay_range = [1.0, 3.0]

    behance_base_url = settings.get("behance_base_url", "https://www.behance.net")
    max_pages = int(settings.get("max_pages", 5))

    logging.info("Starting Behance scrape for keyword '%s'", keyword)
    scraper = BehanceScraper(
        base_url=behance_base_url,
        delay_range=(float(delay_range[0]), float(delay_range[1])),
        max_pages=max_pages,
    )

    try:
        profiles: List[Dict[str, Any]] = scraper.run(
            keyword=keyword,
            max_profiles=max_profiles,
        )
    except Exception as exc:  # noqa: BLE001
        logging.exception("Unexpected error during scraping: %s", exc)
        return 1

    logging.info("Scraping complete. Collected %d profiles.", len(profiles))

    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    safe_keyword = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in keyword)
    base_filename = f"behance_freelancers_{safe_keyword}_{timestamp}"

    formats = [fmt.strip().lower() for fmt in args.formats.split(",") if fmt.strip()]
    if not formats:
        formats = ["json"]

    exporter = ExportManager(output_dir=output_dir)

    try:
        exporter.export(records=profiles, formats=formats, base_filename=base_filename)
    except ExportFormatError as exc:
        logging.error("Export failed due to unsupported format: %s", exc)
        return 2
    except Exception as exc:  # noqa: BLE001
        logging.exception("Unexpected error during export: %s", exc)
        return 3

    logging.info("All done. Files written under '%s'.", os.path.abspath(output_dir))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())