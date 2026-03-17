from __future__ import annotations

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

app = FastAPI(title="Job Search Agent", version="1.0.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

TARGET_ROLE_PATTERNS = (
    "software engineer ii",
    "software engineer iii",
    "software engineer 2",
    "software engineer 3",
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
        },
    )


@app.post("/analyze", response_class=HTMLResponse)
async def analyze_jobs(
    request: Request,
    company_websites: str = Form(...),
    resume: UploadFile = File(...),
    cover_letter: UploadFile | None = File(None),
) -> HTMLResponse:
    try:
        response_payload, stored_files = await _run_analysis(
            company_websites=company_websites,
            resume=resume,
            cover_letter=cover_letter,
        )
    except Exception as exc:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "results": None,
                "error": str(exc),
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "results": response_payload,
            "stored_files": stored_files,
            "error": None,
        },
    )


@app.post("/api/analyze", response_model=MatchResult)
async def analyze_jobs_api(
    company_websites: str = Form(...),
    resume: UploadFile = File(...),
    cover_letter: UploadFile | None = File(None),
) -> MatchResult:
    response_payload, _ = await _run_analysis(
        company_websites=company_websites,
        resume=resume,
        cover_letter=cover_letter,
    )
    return response_payload


async def _run_analysis(
    company_websites: str,
    resume: UploadFile,
    cover_letter: UploadFile | None,
) -> tuple[MatchResult, list[str]]:
    scraper = CareerSiteScraper()
    resume_text = await _save_and_extract_upload(resume)
    cover_letter_text = ""
    if cover_letter and cover_letter.filename:
        cover_letter_text = await _save_and_extract_upload(cover_letter)
    matcher = OpenAIJobMatcher()

    urls = [line.strip() for line in company_websites.splitlines() if line.strip()]
    if not urls:
        raise ValueError("Provide at least one company website.")

    aggregated_matches: list[dict] = []
    stored_files: list[str] = []
    notes: list[str] = []

    for company_url in urls:
        pages = scraper.scrape_company(company_url)
        if not pages:
            notes.append(f"No career pages were scraped for {company_url}.")
            continue

        scraped_text = scraper.build_text_dump(company_url, pages)
        file_path = write_scraped_content(company_url, scraped_text)
        stored_files.append(str(file_path))

        try:
            result = matcher.match_jobs(
                resume_text=resume_text,
                cover_letter_text=cover_letter_text,
                company_url=company_url,
                scraped_text=scraped_text,
            )
        except Exception as exc:
            notes.append(f"{company_url}: OpenAI matching failed: {exc}")
            continue

        aggregated_matches.extend(
            match.model_dump()
            for match in result.matches
            if _is_target_role(match.title)
        )
        if result.notes:
            notes.append(f"{company_url}: {result.notes}")

    return MatchResult(matches=aggregated_matches, notes="\n".join(notes)), stored_files


async def _save_and_extract_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "upload.txt").suffix or ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(await upload.read())
        temp_path = Path(temp_file.name)
    try:
        return extract_text_from_upload(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _is_target_role(title: str) -> bool:
    normalized = " ".join(title.lower().split())
    return any(pattern in normalized for pattern in TARGET_ROLE_PATTERNS)
