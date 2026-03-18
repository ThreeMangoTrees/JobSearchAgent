from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import APP_TIMEZONE
from app.services.company_registry import (
    list_company_configs,
    update_company_run_timestamps,
    write_company_jobs,
    write_company_scrape,
)
from app.services.openai_matcher import OpenAIJobMatcher
from app.services.scraper import CareerSiteScraper

logger = logging.getLogger(__name__)


class CompanySyncScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_run_slot: str = ""
        self._timezone = ZoneInfo(APP_TIMEZONE)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="company-sync-scheduler", daemon=True)
        self._thread.start()
        logger.info("Company sync scheduler started in timezone %s", APP_TIMEZONE)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def run_now(self) -> None:
        self._run_all_companies()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = datetime.now(self._timezone)
            slot = self._slot_key(now)
            if slot and slot != self._last_run_slot:
                logger.info("Starting scheduled company sync for slot %s", slot)
                self._run_all_companies()
                self._last_run_slot = slot
            time.sleep(30)

    def _slot_key(self, now: datetime) -> str:
        if now.minute != 0:
            return ""
        if now.hour not in {0, 12}:
            return ""
        return now.strftime("%Y-%m-%d-%H")

    def _run_all_companies(self) -> None:
        companies = list_company_configs()
        if not companies:
            logger.info("No registered companies found for scheduled sync")
            return

        with ThreadPoolExecutor(max_workers=min(4, len(companies))) as executor:
            futures = [executor.submit(self._sync_company, company.model_dump()) for company in companies]
            for future in futures:
                try:
                    future.result()
                except Exception as exc:
                    logger.exception("Scheduled sync failed: %s", exc)

    def _sync_company(self, company_data: dict) -> None:
        scraper = CareerSiteScraper()
        company_slug = company_data["company_slug"]
        careers_page_url = company_data["careers_page_url"]

        logger.info("Scheduled scrape starting for %s", careers_page_url)
        pages = scraper.scrape_company(careers_page_url)
        scraped_text = scraper.build_text_dump(careers_page_url, pages)
        scraped_at = datetime.utcnow().isoformat()
        write_company_scrape(
            company_slug,
            {
                "company_slug": company_slug,
                "company_name": company_data["company_name"],
                "careers_page_url": careers_page_url,
                "scraped_at": scraped_at,
                "page_count": len(pages),
                "pages": [page.__dict__ for page in pages],
                "scraped_text": scraped_text,
            },
        )
        update_company_run_timestamps(company_slug, scraped_at=scraped_at)

        extraction_thread = threading.Thread(
            target=self._extract_jobs,
            args=(company_data, scraped_text),
            name=f"{company_slug}-extractor",
            daemon=True,
        )
        extraction_thread.start()
        extraction_thread.join()

    def _extract_jobs(self, company_data: dict, scraped_text: str) -> None:
        matcher = OpenAIJobMatcher()
        jobs = matcher.extract_jobs(
            company_url=company_data["careers_page_url"],
            scraped_text=scraped_text,
            extraction_instructions=company_data["extraction_instructions"],
        )
        write_company_jobs(
            company_slug=company_data["company_slug"],
            company_name=company_data["company_name"],
            careers_page_url=company_data["careers_page_url"],
            jobs=jobs,
        )
        update_company_run_timestamps(
            company_data["company_slug"],
            extracted_at=datetime.utcnow().isoformat(),
        )
        logger.info(
            "Stored %s extracted jobs for %s",
            len(jobs),
            company_data["careers_page_url"],
        )


scheduler = CompanySyncScheduler()
