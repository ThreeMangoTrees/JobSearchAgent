from __future__ import annotations

import re
from pathlib import Path

from app.config import SCRAPED_DATA_DIR


def slugify(value: str) -> str:
    normalized = re.sub(r"https?://", "", value.strip(), flags=re.IGNORECASE)
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return normalized or "company"


def write_scraped_content(company_url: str, content: str) -> Path:
    file_path = SCRAPED_DATA_DIR / f"{slugify(company_url)}.txt"
    file_path.write_text(content, encoding="utf-8")
    return file_path


def read_scraped_content(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8")
