from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import STATIC_DIR, TEMPLATES_DIR
from app.models import MatchResult
from app.services.openai_matcher import OpenAIJobMatcher, extract_text_from_upload
from app.services.scraper import CareerSiteScraper
from app.services.storage import write_scraped_content

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Job Search Agent", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

TARGET_ROLE_PATTERNS = (
    "senior software engineer",
    "software engineer ii",
    "software engineer iii",
    "software engineer 2",
    "software engineer 3",
    "software engineer c++",
    "software engineer android",
    "software engineer ios",
    "swe ii",
    "swe iii",
    "swe 2",
    "swe 3",
    "software developer ii",
    "software developer iii",
    "software developer 2",
    "software developer 3",
)


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "results": None,
            "error": None,
            "preferred_location": "",
        },
    )


@app.post("/analyze", response_class=HTMLResponse)
async def analyze_jobs(
    request: Request,
    company_websites: str = Form(...),
    preferred_location: str = Form(""),
    resume: UploadFile = File(...),
    cover_letter: UploadFile | None = File(None),
) -> HTMLResponse:
    logger.info("Received UI request for /analyze")
    try:
        response_payload, stored_files = await _run_analysis(
            company_websites=company_websites,
            preferred_location=preferred_location,
            resume=resume,
            cover_letter=cover_letter,
        )
    except Exception as exc:
        logger.exception("UI request failed: %s", exc)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "results": None,
                "error": str(exc),
                "preferred_location": preferred_location,
            },
            status_code=400,
        )

    logger.info(
        "UI request completed successfully with %s matching jobs and %s stored files",
        len(response_payload.matches),
        len(stored_files),
    )
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "results": response_payload,
            "stored_files": stored_files,
            "error": None,
            "preferred_location": preferred_location,
        },
    )


@app.post("/api/analyze", response_model=MatchResult)
async def analyze_jobs_api(
    company_websites: str = Form(...),
    preferred_location: str = Form(""),
    resume: UploadFile = File(...),
    cover_letter: UploadFile | None = File(None),
) -> MatchResult:
    logger.info("Received API request for /api/analyze")
    response_payload, _ = await _run_analysis(
        company_websites=company_websites,
        preferred_location=preferred_location,
        resume=resume,
        cover_letter=cover_letter,
    )
    logger.info("API request completed successfully with %s matching jobs", len(response_payload.matches))
    return response_payload


async def _run_analysis(
    company_websites: str,
    preferred_location: str,
    resume: UploadFile,
    cover_letter: UploadFile | None,
) -> tuple[MatchResult, list[str]]:
    logger.info("Starting analysis pipeline")
    scraper = CareerSiteScraper()
    logger.info("Extracting text from resume upload: %s", resume.filename or "<unnamed>")
    resume_text = await _save_and_extract_upload(resume)
    cover_letter_text = ""
    if cover_letter and cover_letter.filename:
        logger.info("Extracting text from cover letter upload: %s", cover_letter.filename)
        cover_letter_text = await _save_and_extract_upload(cover_letter)
    else:
        logger.info("No cover letter upload provided")
    logger.info("Initializing OpenAI matcher")
    matcher = OpenAIJobMatcher()

    urls = [line.strip() for line in company_websites.splitlines() if line.strip()]
    if not urls:
        raise ValueError("Provide at least one company website.")
    logger.info("Parsed %s company website(s) from form input", len(urls))
    location_filters = _parse_location_filters(preferred_location)
    if location_filters:
        logger.info("Applying location filter(s): %s", ", ".join(location_filters))
    else:
        logger.info("No location filter provided")

    aggregated_matches: list[dict] = []
    stored_files: list[str] = []
    notes: list[str] = []

    for company_url in urls:
        logger.info("Scraping company website: %s", company_url)
        pages = scraper.scrape_company(company_url)
        logger.info("Scraping finished for %s with %s page(s)", company_url, len(pages))
        if not pages:
            notes.append(f"No career pages were scraped for {company_url}.")
            logger.warning("No career pages scraped for %s", company_url)
            continue

        logger.info("Building text dump for %s", company_url)
        scraped_text = scraper.build_text_dump(company_url, pages)
        file_path = write_scraped_content(company_url, scraped_text)
        stored_files.append(str(file_path))
        logger.info("Stored scraped text for %s at %s", company_url, file_path)

        try:
            logger.info("Sending scraped content to OpenAI matcher for %s", company_url)
            result = matcher.match_jobs(
                resume_text=resume_text,
                cover_letter_text=cover_letter_text,
                company_url=company_url,
                scraped_text=scraped_text,
                preferred_location=preferred_location,
            )
        except Exception as exc:
            notes.append(f"{company_url}: OpenAI matching failed: {exc}")
            logger.exception("OpenAI matching failed for %s: %s", company_url, exc)
            continue

        filtered_matches = [
            match.model_dump()
            for match in result.matches
            if _is_target_role(match.title) and _matches_location(match.location, location_filters)
        ]
        aggregated_matches.extend(
            filtered_matches
        )
        logger.info(
            "OpenAI returned %s matches for %s, %s remained after title filtering",
            len(result.matches),
            company_url,
            len(filtered_matches),
        )
        if result.notes:
            notes.append(f"{company_url}: {result.notes}")
            logger.info("Matcher notes for %s: %s", company_url, result.notes)

    logger.info(
        "Analysis pipeline complete with %s total matching jobs and %s stored file(s)",
        len(aggregated_matches),
        len(stored_files),
    )
    return MatchResult(matches=aggregated_matches, notes="\n".join(notes)), stored_files


async def _save_and_extract_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "upload.txt").suffix or ".txt"
    logger.info("Saving uploaded file %s to a temporary location", upload.filename or "<unnamed>")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(await upload.read())
        temp_path = Path(temp_file.name)
    try:
        extracted_text = extract_text_from_upload(temp_path)
        logger.info(
            "Extracted %s characters from uploaded file %s",
            len(extracted_text),
            upload.filename or "<unnamed>",
        )
        return extracted_text
    finally:
        temp_path.unlink(missing_ok=True)
        logger.info("Removed temporary upload file %s", temp_path)


def _is_target_role(title: str) -> bool:
    normalized = " ".join(title.lower().split())
    return any(pattern in normalized for pattern in TARGET_ROLE_PATTERNS)


def _parse_location_filters(preferred_location: str) -> list[str]:
    return [
        token.strip().lower()
        for chunk in preferred_location.splitlines()
        for token in chunk.split(",")
        if token.strip()
    ]


def _matches_location(job_location: str, location_filters: list[str]) -> bool:
    if not location_filters:
        return True

    normalized_location = " ".join(job_location.lower().split())
    if not normalized_location:
        return False

    if any(location_filter in normalized_location for location_filter in location_filters):
        return True

    if "remote" in normalized_location:
        return True

    return False
