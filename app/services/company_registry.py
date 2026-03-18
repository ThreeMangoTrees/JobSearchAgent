from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from app.config import COMPANY_DATA_DIR
from app.models import CompanyConfig, ExtractedJob

logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
    return normalized or "company"


def company_slug_from_url(company_url: str) -> str:
    parsed = urlparse(company_url if "://" in company_url else f"https://{company_url}")
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    parts = [part for part in host.split(".") if part]
    if len(parts) >= 2:
        return _slugify(parts[-2])
    if parts:
        return _slugify(parts[0])
    return "company"


def company_name_from_url(company_url: str) -> str:
    slug = company_slug_from_url(company_url)
    return " ".join(part.capitalize() for part in slug.split("-")) or "Company"


def company_config_path(company_slug: str) -> Path:
    return COMPANY_DATA_DIR / f"{company_slug}.json"


def company_scrape_path(company_slug: str) -> Path:
    return COMPANY_DATA_DIR / f"{company_slug}-scraped.json"


def company_jobs_path(company_slug: str) -> Path:
    return COMPANY_DATA_DIR / f"{company_slug}-jobs.json"


def list_company_configs() -> list[CompanyConfig]:
    configs: list[CompanyConfig] = []
    for path in sorted(COMPANY_DATA_DIR.glob("*.json")):
        if path.name.endswith("-scraped.json") or path.name.endswith("-jobs.json"):
            continue
        try:
            configs.append(CompanyConfig.model_validate_json(path.read_text(encoding="utf-8")))
        except Exception as exc:
            logger.warning("Failed to load company config from %s: %s", path, exc)
    return sorted(configs, key=lambda item: item.company_name.lower())


def get_company_config(company_slug: str) -> CompanyConfig | None:
    path = company_config_path(company_slug)
    if not path.exists():
        return None
    return CompanyConfig.model_validate_json(path.read_text(encoding="utf-8"))


def save_company_config(careers_page_url: str, extraction_instructions: str) -> CompanyConfig:
    company_slug = company_slug_from_url(careers_page_url)
    existing = get_company_config(company_slug)
    now = datetime.utcnow().isoformat()
    config = CompanyConfig(
        company_slug=company_slug,
        company_name=company_name_from_url(careers_page_url),
        careers_page_url=careers_page_url.strip(),
        extraction_instructions=extraction_instructions.strip(),
        created_at=existing.created_at if existing else now,
        updated_at=now,
        last_scraped_at=existing.last_scraped_at if existing else "",
        last_extracted_at=existing.last_extracted_at if existing else "",
    )
    company_config_path(company_slug).write_text(
        config.model_dump_json(indent=2),
        encoding="utf-8",
    )
    logger.info("Saved company config for %s", careers_page_url)
    return config


def update_company_run_timestamps(company_slug: str, scraped_at: str | None = None, extracted_at: str | None = None) -> None:
    config = get_company_config(company_slug)
    if not config:
        return
    updated = config.model_copy(
        update={
            "updated_at": datetime.utcnow().isoformat(),
            "last_scraped_at": scraped_at or config.last_scraped_at,
            "last_extracted_at": extracted_at or config.last_extracted_at,
        }
    )
    company_config_path(company_slug).write_text(updated.model_dump_json(indent=2), encoding="utf-8")


def write_company_scrape(company_slug: str, payload: dict) -> Path:
    path = company_scrape_path(company_slug)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_company_jobs(company_slug: str, company_name: str, careers_page_url: str, jobs: list[ExtractedJob]) -> Path:
    path = company_jobs_path(company_slug)
    payload = {
        "company_slug": company_slug,
        "company_name": company_name,
        "careers_page_url": careers_page_url,
        "updated_at": datetime.utcnow().isoformat(),
        "jobs": [job.model_dump() for job in jobs],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def read_company_scrape_text(company_slug: str) -> str:
    path = company_scrape_path(company_slug)
    if not path.exists():
        return ""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return str(payload.get("scraped_text", ""))
