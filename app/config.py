from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
SCRAPED_DATA_DIR = BASE_DIR / "job_sites_data"
COMPANY_DATA_DIR = BASE_DIR / "JobSearchCompanies"
TEMPLATES_DIR = APP_DIR / "templates"
STATIC_DIR = APP_DIR / "static"

load_dotenv(BASE_DIR / ".env")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-in-env")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "vinitkumar.utd@gmail.com")
APP_TIMEZONE = os.getenv("APP_TIMEZONE", "America/Los_Angeles")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "")
DATABASE_URL = os.getenv("DATABASE_URL", "")
DATABASE_ECHO = os.getenv("DATABASE_ECHO", "false").lower() == "true"

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

SCRAPED_DATA_DIR.mkdir(parents=True, exist_ok=True)
COMPANY_DATA_DIR.mkdir(parents=True, exist_ok=True)
