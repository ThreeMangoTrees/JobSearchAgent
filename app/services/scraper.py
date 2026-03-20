from __future__ import annotations

import json
import logging
import re
from collections import deque
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.models import ExtractedJob

logger = logging.getLogger(__name__)

CAREER_KEYWORDS = (
    "career",
    "careers",
    "job",
    "jobs",
    "opening",
    "openings",
    "position",
    "positions",
    "join-us",
    "work-with-us",
)

COMMON_CAREER_PATHS = (
    "/careers",
    "/jobs",
    "/careers/jobs",
    "/join-us",
    "/company/careers",
)

US_STATE_CODES = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}


@dataclass
class ScrapedPage:
    url: str
    title: str
    text: str


class CareerSiteScraper:
    def __init__(self, timeout: int = 20, max_pages: int = 12) -> None:
        self.timeout = timeout
        self.max_pages = max_pages
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (compatible; JobSearchAgent/1.0; "
                    "+https://example.local/jobsearchagent)"
                )
            }
        )

    def scrape_company(self, company_url: str) -> list[ScrapedPage]:
        normalized_url = self._normalize_url(company_url)
        logger.info("Normalized company URL %s -> %s", company_url, normalized_url)
        if self._is_robinhood_careers_url(normalized_url):
            logger.info("Using Robinhood-specific scraper for %s", normalized_url)
            robinhood_page = self._scrape_robinhood_open_roles(normalized_url)
            if robinhood_page:
                return [robinhood_page]
            logger.info("Falling back to generic scraper for %s after Robinhood-specific scrape returned no jobs", normalized_url)
        if self._is_rippling_careers_url(normalized_url):
            logger.info("Using Rippling-specific scraper for %s", normalized_url)
            rippling_page = self._scrape_rippling_open_roles(normalized_url)
            return [rippling_page] if rippling_page else []

        discovered = self._discover_career_urls(normalized_url)
        logger.info("Discovered %s candidate career page(s) for %s", len(discovered), normalized_url)
        pages: list[ScrapedPage] = []

        for url in discovered[: self.max_pages]:
            logger.info("Scraping candidate page %s", url)
            page = self._scrape_page(url)
            if page and len(page.text) > 200:
                pages.append(page)
                logger.info("Accepted scraped page %s with %s characters", url, len(page.text))
            else:
                logger.info("Skipped page %s because content was missing or too short", url)

        return pages

    def build_text_dump(self, company_url: str, pages: list[ScrapedPage]) -> str:
        blocks = [f"Company website: {company_url}", f"Pages scraped: {len(pages)}", ""]
        for index, page in enumerate(pages, start=1):
            blocks.extend(
                [
                    f"=== PAGE {index} ===",
                    f"URL: {page.url}",
                    f"TITLE: {page.title}",
                    page.text,
                    "",
                ]
            )
        return "\n".join(blocks)

    def extract_company_jobs(self, company_url: str, scraped_text: str) -> list[ExtractedJob] | None:
        normalized_url = self._normalize_url(company_url)
        if self._is_robinhood_careers_url(normalized_url):
            return self._extract_robinhood_jobs_from_text_dump(scraped_text)
        return None

    def _discover_career_urls(self, company_url: str) -> list[str]:
        queue: deque[str] = deque()
        seen: set[str] = set()
        discovered: list[str] = []

        for path in COMMON_CAREER_PATHS:
            queue.append(urljoin(company_url, path))
        queue.append(company_url)

        while queue and len(discovered) < self.max_pages:
            current = queue.popleft()
            if current in seen:
                continue
            seen.add(current)
            logger.info("Checking potential career URL %s", current)

            response = self._get(current)
            if not response:
                logger.info("No usable HTML response for %s", current)
                continue

            if self._looks_like_career_url(current) or self._looks_like_career_page(response.text):
                discovered.append(current)
                logger.info("Marked %s as a career-related page", current)

            for link in self._extract_candidate_links(current, response.text):
                if link not in seen:
                    queue.append(link)

        if not discovered:
            discovered.append(company_url)

        return discovered

    def _scrape_page(self, url: str) -> ScrapedPage | None:
        response = self._get(url)
        if not response:
            logger.info("Skipping page scrape for %s because fetch failed", url)
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else url
        text = "\n".join(
            line.strip()
            for line in soup.get_text(separator="\n").splitlines()
            if line.strip()
        )
        text = re.sub(r"\n{3,}", "\n\n", text)
        logger.info("Extracted %s characters of text from %s", len(text), url)
        return ScrapedPage(url=url, title=title, text=text)

    def _extract_candidate_links(self, base_url: str, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        base_host = urlparse(base_url).netloc
        candidates: list[str] = []

        for anchor in soup.find_all("a", href=True):
            href = urljoin(base_url, anchor["href"])
            parsed = urlparse(href)
            if parsed.scheme not in {"http", "https"}:
                continue
            if parsed.netloc != base_host:
                continue

            anchor_text = " ".join(anchor.stripped_strings).lower()
            combined = f"{href.lower()} {anchor_text}"
            if any(keyword in combined for keyword in CAREER_KEYWORDS):
                candidates.append(href)

        deduped: list[str] = []
        seen: set[str] = set()
        for link in candidates:
            if link not in seen:
                seen.add(link)
                deduped.append(link)
        return deduped[: self.max_pages]

    def _looks_like_career_url(self, url: str) -> bool:
        lowered = url.lower()
        return any(keyword in lowered for keyword in CAREER_KEYWORDS)

    def _looks_like_career_page(self, html: str) -> bool:
        sample = html[:8000].lower()
        tokens = ("careers", "open roles", "open positions", "job openings", "job search")
        return any(token in sample for token in tokens)

    def _normalize_url(self, url: str) -> str:
        stripped = url.strip()
        if not stripped.startswith(("http://", "https://")):
            stripped = f"https://{stripped}"
        return stripped.rstrip("/")

    def _is_rippling_careers_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc.endswith("rippling.com") and "/careers" in parsed.path.lower()

    def _is_robinhood_careers_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.netloc.endswith("robinhood.com") and "careers" in parsed.netloc

    def _scrape_robinhood_open_roles(self, company_url: str) -> ScrapedPage | None:
        jobs = self._fetch_robinhood_jobs()
        if not jobs:
            logger.info("Robinhood-specific scrape found no matching jobs")
            return None

        text = self._build_robinhood_jobs_text_dump(jobs)
        return ScrapedPage(
            url="https://boards-api.greenhouse.io/v1/boards/robinhood/jobs?content=true",
            title="Robinhood Open Roles - Engineering in US Locations",
            text=text,
        )

    def _fetch_robinhood_jobs(self) -> list[dict]:
        response_payload = self._get_json("https://boards-api.greenhouse.io/v1/boards/robinhood/jobs?content=true")
        if not response_payload:
            return []

        jobs = response_payload.get("jobs", [])
        filtered_jobs = self._filter_robinhood_jobs(jobs)
        logger.info(
            "Filtered Robinhood jobs down to %s US engineering role-location entries from %s raw entries",
            len(filtered_jobs),
            len(jobs),
        )
        return filtered_jobs

    def _filter_robinhood_jobs(self, jobs: list[dict]) -> list[dict]:
        filtered_jobs: list[dict] = []

        for job in jobs:
            department_names = [
                str(department.get("name", "")).strip()
                for department in job.get("departments", [])
                if str(department.get("name", "")).strip()
            ]
            if not any("engineering" in department.lower() for department in department_names):
                continue

            locations = self._extract_robinhood_us_locations(job)
            if not locations:
                continue

            title = str(job.get("title", "")).strip()
            absolute_url = str(job.get("absolute_url", "")).strip()
            job_id = str(job.get("id", "")).strip()
            department = ", ".join(department_names)

            for location in locations:
                filtered_jobs.append(
                    {
                        "id": job_id,
                        "title": title,
                        "department": department,
                        "location_name": location,
                        "url": absolute_url,
                    }
                )

        filtered_jobs.sort(key=lambda item: (item["title"].lower(), item["location_name"].lower(), item["id"]))
        return filtered_jobs

    def _extract_robinhood_us_locations(self, job: dict) -> list[str]:
        raw_locations: list[str] = []

        primary_location = str(job.get("location", {}).get("name", "")).strip()
        if primary_location:
            raw_locations.extend(part.strip() for part in primary_location.split(";") if part.strip())

        for office in job.get("offices", []):
            location_name = str(office.get("location", "") or office.get("name", "")).strip()
            if location_name:
                raw_locations.extend(part.strip() for part in location_name.split(";") if part.strip())

        normalized_locations: list[str] = []
        seen: set[str] = set()
        for location in raw_locations:
            cleaned = re.sub(r"\s+", " ", location).strip(" ,")
            if not cleaned or not self._is_us_location(cleaned):
                continue
            if cleaned in seen:
                continue
            seen.add(cleaned)
            normalized_locations.append(cleaned)

        return normalized_locations

    def _is_us_location(self, location: str) -> bool:
        normalized = location.strip()
        lowered = normalized.lower()
        if lowered in {"remote", "remote - us", "us remote", "united states", "united states remote"}:
            return True
        if "united states" in lowered or lowered.endswith(", usa") or lowered.endswith(", us"):
            return True

        match = re.search(r",\s*([A-Z]{2})(?:\b|$)", normalized)
        if match and match.group(1) in US_STATE_CODES:
            return True

        return False

    def _build_robinhood_jobs_text_dump(self, jobs: list[dict]) -> str:
        lines = [
            "Robinhood open roles",
            "Source: Greenhouse Job Board API",
            "Applied filters:",
            "- Departments: any department containing 'Engineering'",
            "- Locations: United States / US office locations",
            f"Matching role-location entries: {len(jobs)}",
            "",
        ]

        if not jobs:
            lines.append("No Robinhood jobs matched the requested filters.")
            return "\n".join(lines)

        for index, job in enumerate(jobs, start=1):
            lines.extend(
                [
                    f"Role {index}",
                    f"Job ID: {job['id']}",
                    f"Title: {job['title']}",
                    f"Department: {job['department']}",
                    f"Location: {job['location_name']}",
                    f"Source URL: {job['url']}",
                    "",
                ]
            )

        return "\n".join(lines)

    def _extract_robinhood_jobs_from_text_dump(self, scraped_text: str) -> list[ExtractedJob] | None:
        if "Robinhood open roles" not in scraped_text or "Source: Greenhouse Job Board API" not in scraped_text:
            return None

        pattern = re.compile(
            r"Job ID:\s*(?P<job_id>.+?)\n"
            r"Title:\s*(?P<title>.+?)\n"
            r"Department:\s*(?P<department>.+?)\n"
            r"Location:\s*(?P<location>.+?)\n"
            r"Source URL:\s*(?P<source_url>.+?)(?:\n|$)"
        )
        jobs: list[ExtractedJob] = []
        for match in pattern.finditer(scraped_text):
            jobs.append(
                ExtractedJob(
                    job_id=match.group("job_id").strip(),
                    location=match.group("location").strip(),
                    role_name=match.group("title").strip(),
                )
            )
        return jobs

    def _scrape_rippling_open_roles(self, company_url: str) -> ScrapedPage | None:
        open_roles_url = f"{self._normalize_url(company_url).split('/careers', 1)[0]}/careers/open-roles"
        response = self._get(open_roles_url)
        if not response:
            logger.info("Rippling-specific scrape failed because fetch failed for %s", open_roles_url)
            return None

        payload = self._extract_rippling_next_data(response.text)
        if not payload:
            logger.info("Rippling-specific scrape failed because __NEXT_DATA__ was not found")
            return None

        jobs_payload = payload.get("props", {}).get("pageProps", {}).get("jobs", {})
        jobs = jobs_payload.get("items", [])
        filtered_jobs = self._filter_rippling_jobs(jobs)
        logger.info(
            "Filtered Rippling jobs down to %s Engineering role location entries from %s raw entries",
            len(filtered_jobs),
            len(jobs),
        )
        text = self._build_rippling_jobs_text_dump(filtered_jobs)
        return ScrapedPage(
            url=open_roles_url,
            title="Rippling Open Roles - Engineering in US Cities",
            text=text,
        )

    def _extract_rippling_next_data(self, html: str) -> dict | None:
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">\s*(.*?)\s*</script>',
            html,
            flags=re.DOTALL,
        )
        if not match:
            return None

        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            logger.warning("Failed to decode Rippling __NEXT_DATA__: %s", exc)
            return None

    def _filter_rippling_jobs(self, jobs: list[dict]) -> list[dict]:
        filtered_jobs: list[dict] = []

        for job in jobs:
            department_name = job.get("department", {}).get("name", "").strip().lower()
            if department_name != "engineering":
                continue

            for location in job.get("locations", []):
                if location.get("countryCode") != "US":
                    continue
                city = (location.get("city") or "").strip()
                if not city:
                    continue

                filtered_jobs.append(
                    {
                        "id": job.get("id", ""),
                        "title": job.get("name", "").strip(),
                        "url": job.get("url", "").strip(),
                        "department": job.get("department", {}).get("name", "").strip(),
                        "location_name": (location.get("name") or "").strip(),
                        "city": city,
                        "state": (location.get("state") or location.get("stateCode") or "").strip(),
                        "workplace_type": (location.get("workplaceType") or "").strip(),
                    }
                )

        filtered_jobs.sort(key=lambda item: (item["title"].lower(), item["city"].lower(), item["state"].lower()))
        return filtered_jobs

    def _build_rippling_jobs_text_dump(self, jobs: list[dict]) -> str:
        lines = [
            "Rippling open roles",
            "Applied filters:",
            "- Department: Engineering",
            "- Locations: United States entries with a city value only",
            f"Matching role-location entries: {len(jobs)}",
            "",
        ]

        if not jobs:
            lines.append("No Rippling jobs matched the requested filters.")
            return "\n".join(lines)

        for index, job in enumerate(jobs, start=1):
            lines.extend(
                [
                    f"Role {index}",
                    f"Job ID: {job['id']}",
                    f"Title: {job['title']}",
                    f"Department: {job['department']}",
                    f"Location: {job['location_name']}",
                    f"City: {job['city']}",
                    f"State: {job['state']}",
                    f"Workplace Type: {job['workplace_type']}",
                    f"Source URL: {job['url']}",
                    "",
                ]
            )

        return "\n".join(lines)

    def _get_json(self, url: str) -> dict | None:
        try:
            logger.info("Fetching JSON URL %s", url)
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("JSON request failed for %s: %s", url, exc)
            return None

    def _get(self, url: str) -> requests.Response | None:
        try:
            logger.info("Fetching URL %s", url)
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            if "text/html" not in response.headers.get("Content-Type", ""):
                logger.info("Ignoring non-HTML response from %s", url)
                return None
            return response
        except requests.RequestException as exc:
            logger.warning("Request failed for %s: %s", url, exc)
            return None
