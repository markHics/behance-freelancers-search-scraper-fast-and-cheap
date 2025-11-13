thonimport hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from .utils_time import sleep_with_jitter

logger = logging.getLogger(__name__)

@dataclass
class BehanceScraperConfig:
    base_url: str
    delay_range: Tuple[float, float]
    max_pages: int
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )

class BehanceScraper:
    """
    Scrapes freelancer profile information from Behance search results.

    This implementation is intentionally resilient: it focuses on robust parsing
    rather than relying on brittle, deeply nested CSS paths. If the HTML
    layout changes, the scraper will still return well-formed records, just
    with more missing fields.
    """

    def __init__(
        self,
        base_url: str = "https://www.behance.net",
        delay_range: Tuple[float, float] = (1.0, 3.0),
        max_pages: int = 5,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.config = BehanceScraperConfig(
            base_url=base_url.rstrip("/"),
            delay_range=delay_range,
            max_pages=max_pages,
        )
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.config.user_agent})

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def run(self, keyword: str, max_profiles: int = 100) -> List[Dict[str, Any]]:
        """
        Scrape up to `max_profiles` freelancer profiles that match the keyword.
        """
        profiles: List[Dict[str, Any]] = []
        seen_urls: Set[str] = set()

        for profile_url in self._iterate_profile_urls(keyword):
            if profile_url in seen_urls:
                continue
            seen_urls.add(profile_url)

            logger.info("Scraping profile %d/%d: %s", len(profiles) + 1, max_profiles, profile_url)
            try:
                profile_data = self._scrape_profile(profile_url)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to scrape profile %s: %s", profile_url, exc)
                continue

            if profile_data:
                profiles.append(profile_data)

            if len(profiles) >= max_profiles:
                logger.info("Reached requested max_profiles=%d", max_profiles)
                break

        return profiles

    # --------------------------------------------------------------------- #
    # Search helpers
    # --------------------------------------------------------------------- #

    def _iterate_profile_urls(self, keyword: str) -> Iterable[str]:
        """
        Iterate over profile URLs found in search result pages.

        Behance search URLs may change over time. We use a generic query
        parameter based search endpoint targeting users/freelancers.
        """
        encoded = quote(keyword)
        for page in range(1, self.config.max_pages + 1):
            search_url = (
                f"{self.config.base_url}/search/users"
                f"?search={encoded}&tracking_source=typeahead_search_direction"
                f"&page={page}"
            )
            logger.info("Fetching search results page %d: %s", page, search_url)
            html = self._fetch(search_url)
            if not html:
                logger.warning("Empty response for search page %d, stopping.", page)
                break

            urls = list(self._parse_search_page_for_profiles(html))
            if not urls:
                logger.info("No more profiles found on page %d, stopping.", page)
                break

            for url in urls:
                yield url

            # Be polite between pages
            sleep_with_jitter(*self.config.delay_range)

    def _fetch(self, url: str) -> Optional[str]:
        """Fetch a page, returning the HTML string or None on failure."""
        try:
            resp = self.session.get(url, timeout=20)
            if resp.status_code != 200:
                logger.warning("Non-200 response %s for url %s", resp.status_code, url)
                return None
            return resp.text
        except requests.RequestException as exc:
            logger.warning("Network error fetching %s: %s", url, exc)
            return None

    def _parse_search_page_for_profiles(self, html: str) -> Iterable[str]:
        """
        Parse a search page to extract profile URLs.

        We look for anchor tags that appear to reference user profiles.
        """
        soup = BeautifulSoup(html, "lxml")

        # Behance typically uses /{username} pattern for profiles.
        anchors = soup.find_all("a", href=True)
        seen: Set[str] = set()

        for a in anchors:
            href = a["href"]
            # Normalize href to absolute URL
            full_url = urljoin(self.config.base_url + "/", href)

            # Basic heuristic: URL path has exactly one non-empty segment -> /username
            parsed = urlparse(full_url)
            segments = [s for s in parsed.path.split("/") if s]
            if len(segments) != 1:
                continue

            # Filter obvious non-profile paths
            if segments[0].lower() in {"search", "collections", "galleries"}:
                continue

            if full_url not in seen:
                seen.add(full_url)
                logger.debug("Discovered profile URL: %s", full_url)
                yield full_url

    # --------------------------------------------------------------------- #
    # Profile scraping
    # --------------------------------------------------------------------- #

    def _scrape_profile(self, url: str) -> Dict[str, Any]:
        """
        Scrape a single profile page and return a structured dictionary.
        """
        html = self._fetch(url)
        if not html:
            raise RuntimeError("Empty response when fetching profile")

        soup = BeautifulSoup(html, "lxml")

        username = self._extract_username_from_url(url)
        display_name = self._extract_display_name(soup)
        location = self._extract_location(soup)
        country = self._extract_country(location)
        availability = self._extract_availability(soup)
        categories = self._extract_categories(soup)
        projects = self._extract_projects(soup)
        reviews = self._extract_reviews(soup)
        completed_projects = len(projects)

        profile_id = self._generate_stable_id(url)

        profile = {
            "id": profile_id,
            "username": username,
            "displayName": display_name,
            "url": url,
            "location": location,
            "country": country,
            "isAvailableForFreelanceServices": availability,
            "categories": categories,
            "completed_projects": completed_projects,
            "reviews": reviews,
            "profile_image": self._extract_profile_image(soup),
            "projects": projects,
        }

        logger.debug("Scraped profile data for %s: %s", url, profile)
        return profile

    # --------------------------------------------------------------------- #
    # Field extractors
    # --------------------------------------------------------------------- #

    @staticmethod
    def _extract_username_from_url(url: str) -> str:
        path = urlparse(url).path
        segments = [s for s in path.split("/") if s]
        return segments[-1] if segments else ""

    @staticmethod
    def _generate_stable_id(url: str) -> int:
        # Behance exposes numeric IDs in embedded data, but to keep this scraper
        # robust across layout changes we generate a deterministic hash-based ID.
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return int(digest[:9], 16)

    @staticmethod
    def _clean_text(text: Optional[str]) -> str:
        if not text:
            return ""
        return " ".join(text.split())

    def _extract_display_name(self, soup: BeautifulSoup) -> str:
        # Try structured data first
        name_tag = soup.find(attrs={"itemprop": "name"})
        if name_tag:
            return self._clean_text(name_tag.get_text())

        # Fallback to <h1> in header
        h1 = soup.find("h1")
        if h1:
            return self._clean_text(h1.get_text())

        # Fallback to <title>
        if soup.title and soup.title.string:
            title_text = soup.title.string.split("|")[0]
            return self._clean_text(title_text)

        return ""

    def _extract_location(self, soup: BeautifulSoup) -> str:
        # Common patterns: itemprop="addressLocality" or classes like "Location"
        loc_tag = soup.find(attrs={"itemprop": "addressLocality"})
        if loc_tag:
            return self._clean_text(loc_tag.get_text())

        for cls in ("Location", "e-location", "UserInfo-location"):
            elem = soup.find(class_=cls)
            if elem:
                return self._clean_text(elem.get_text())

        # Try small text in header area
        header = soup.find("header")
        if header:
            smalls = header.find_all("span")
            for sp in smalls:
                text = self._clean_text(sp.get_text())
                if "," in text and len(text.split()) <= 5:
                    return text

        return ""

    def _extract_country(self, location: str) -> str:
        if not location:
            return ""
        # Assume country appears after the last comma
        parts = [p.strip() for p in location.split(",") if p.strip()]
        return parts[-1] if parts else ""

    def _extract_availability(self, soup: BeautifulSoup) -> bool:
        # Look for a piece of text that clearly indicates availability
        phrases = [
            "Available for freelance",
            "Available for work",
            "Freelance available",
            "Accepting new projects",
        ]
        body_text = soup.get_text(separator=" ", strip=True)
        lower = body_text.lower()
        for phrase in phrases:
            if phrase.lower() in lower:
                return True
        return False

    def _extract_categories(self, soup: BeautifulSoup) -> List[str]:
        categories: List[str] = []

        # Heuristic: category pills or tags near the top of the profile
        for cls in ("Specialties-specialty", "UserInfo-specialties", "js-speciality"):
            elements = soup.find_all(class_=cls)
            for el in elements:
                text = self._clean_text(el.get_text())
                if text and text not in categories:
                    categories.append(text)

        # Fallback: look for links under a "Fields" or "Specialties" heading
        headings = soup.find_all(["h2", "h3"])
        for h in headings:
            heading_text = self._clean_text(h.get_text()).lower()
            if "fields" in heading_text or "specialties" in heading_text:
                container = h.find_next("ul") or h.find_next("div")
                if not container:
                    continue
                for a in container.find_all("a"):
                    text = self._clean_text(a.get_text())
                    if text and text not in categories:
                        categories.append(text)
                break

        return categories

    def _extract_profile_image(self, soup: BeautifulSoup) -> str:
        # Many profiles have og:image meta tags
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            return og_image["content"]

        # Fallback: avatar image in header
        for cls in ("Avatar-image", "UserInfo-avatar", "Profile-avatar"):
            img = soup.find("img", class_=cls)
            if img and img.get("src"):
                return img["src"]

        return ""

    def _extract_projects(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        projects: List[Dict[str, Any]] = []

        # Look for project grid items
        project_cards = soup.select("a.Project-cover, a.js-project-cover, a.project-cover")
        seen_urls: Set[str] = set()

        for card in project_cards:
            href = card.get("href")
            if not href:
                continue
            url = urljoin(self.config.base_url + "/", href)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            name = ""
            title_el = card.get("title") or card.get("aria-label")
            if title_el:
                name = self._clean_text(title_el)
            else:
                # fall back to descendant title text
                title_tag = card.find("span") or card.find("div")
                if title_tag:
                    name = self._clean_text(title_tag.get_text())

            img = card.find("img")
            cover = img.get("src") if img and img.get("src") else ""

            project_id = self._generate_stable_id(url)

            projects.append(
                {
                    "id": project_id,
                    "name": name,
                    "url": url,
                    "cover_image": cover,
                }
            )

        return projects

    def _extract_reviews(self, soup: BeautifulSoup) -> List[str]:
        reviews: List[str] = []

        # Behance may embed testimonials / reviews in different widgets.
        # We look for sections with headings that mention "Review".
        candidate_sections = []

        for heading in soup.find_all(["h2", "h3"]):
            text = self._clean_text(heading.get_text()).lower()
            if "review" in text or "testimonial" in text:
                section = heading.find_parent("section") or heading.parent
                if section and section not in candidate_sections:
                    candidate_sections.append(section)

        for section in candidate_sections:
            for p in section.find_all("p"):
                text = self._clean_text(p.get_text())
                if text and len(text.split()) >= 4:  # avoid tiny fragments
                    reviews.append(text)

        # De-duplicate while preserving order
        seen: Set[str] = set()
        unique_reviews: List[str] = []
        for r in reviews:
            if r in seen:
                continue
            seen.add(r)
            unique_reviews.append(r)

        return unique_reviews