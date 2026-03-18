from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from app.config import SCRAPED_DATA_DIR

logger = logging.getLogger(__name__)


def slugify(value: str) -> str:
    normalized = re.sub(r"https?://", "", value.strip(), flags=re.IGNORECASE)
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-")
    return normalized or "Company"


def company_name_from_url(company_url: str) -> str:
    parsed = urlparse(company_url if "://" in company_url else f"https://{company_url}")
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    parts = [part for part in host.split(".") if part]
    if len(parts) >= 2:
        company_name = parts[-2]
    elif parts:
        company_name = parts[0]
    else:
        company_name = "Company"

    slugified_name = slugify(company_name)
    return "-".join(segment.capitalize() for segment in slugified_name.split("-") if segment) or "Company"


def build_scraped_file_path(company_url: str) -> Path:
    company_name = company_name_from_url(company_url)
    return SCRAPED_DATA_DIR / f"{company_name}-Job_search.txt"


def write_scraped_content(company_url: str, content: str) -> Path:
    file_path = build_scraped_file_path(company_url)
    legacy_file_path = SCRAPED_DATA_DIR / f"{slugify(company_url)}.txt"

    file_path.unlink(missing_ok=True)
    if legacy_file_path != file_path:
        legacy_file_path.unlink(missing_ok=True)

    file_path.write_text(content, encoding="utf-8")
    logger.info("Wrote scraped content for %s to %s", company_url, file_path)
    return file_path


def read_scraped_content(file_path: Path) -> str:
    logger.info("Reading scraped content from %s", file_path)
    return file_path.read_text(encoding="utf-8")
