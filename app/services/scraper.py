from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

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
        discovered = self._discover_career_urls(normalized_url)
        pages: list[ScrapedPage] = []

        for url in discovered[: self.max_pages]:
            page = self._scrape_page(url)
            if page and len(page.text) > 200:
                pages.append(page)

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

            response = self._get(current)
            if not response:
                continue

            if self._looks_like_career_url(current) or self._looks_like_career_page(response.text):
                discovered.append(current)

            for link in self._extract_candidate_links(current, response.text):
                if link not in seen:
                    queue.append(link)

        if not discovered:
            discovered.append(company_url)

        return discovered

    def _scrape_page(self, url: str) -> ScrapedPage | None:
        response = self._get(url)
        if not response:
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

    def _get(self, url: str) -> requests.Response | None:
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            if "text/html" not in response.headers.get("Content-Type", ""):
                return None
            return response
        except requests.RequestException:
            return None
