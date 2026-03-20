from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from authlib.integrations.starlette_client import OAuth, OAuthError
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import (
    ADMIN_EMAIL,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    SESSION_SECRET,
    STATIC_DIR,
    TEMPLATES_DIR,
)
from app.models import MatchResult
from app.services.company_registry import (
    company_slug_from_url,
    list_company_configs,
    read_company_scrape_text,
    save_company_config,
)
from app.services.company_scheduler import scheduler
from app.services.openai_matcher import OpenAIJobMatcher, extract_text_from_upload
from app.services.scraper import CareerSiteScraper
from app.services.storage import write_scraped_content

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Job Search Agent", version="1.0.0")
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
oauth = OAuth()

if GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

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


@app.on_event("startup")
def startup_event() -> None:
    scheduler.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    scheduler.stop()


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "results": None,
            "error": None,
            "preferred_location": "",
            "company_websites": "",
            "registered_company_count": len(list_company_configs()),
        },
    )


@app.post("/analyze", response_class=HTMLResponse)
async def analyze_jobs(
    request: Request,
    company_websites: str = Form(""),
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
                "company_websites": company_websites,
                "registered_company_count": len(list_company_configs()),
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
            "preferred_location": preferred_location,
            "company_websites": company_websites,
            "registered_company_count": len(list_company_configs()),
        },
    )


@app.post("/api/analyze", response_model=MatchResult)
async def analyze_jobs_api(
    company_websites: str = Form(""),
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
    return response_payload


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "admin_login.html",
        {
            "request": request,
            "error": None,
            "message": None,
            "admin_email": ADMIN_EMAIL,
            "google_oauth_enabled": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        },
    )


@app.get("/admin/login/google")
async def admin_login_google(request: Request) -> Response:
    google = oauth.create_client("google")
    if google is None:
        return templates.TemplateResponse(
            "admin_login.html",
            {
                "request": request,
                "error": (
                    "Google login is not configured. Set GOOGLE_CLIENT_ID, "
                    "GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI in .env."
                ),
                "message": None,
                "admin_email": ADMIN_EMAIL,
                "google_oauth_enabled": False,
            },
            status_code=400,
        )

    redirect_uri = GOOGLE_REDIRECT_URI.strip() or str(request.url_for("admin_google_callback"))
    return await google.authorize_redirect(request, redirect_uri)


@app.get("/admin/auth/google/callback", response_class=HTMLResponse, name="admin_google_callback")
async def admin_google_callback(request: Request) -> Response:
    google = oauth.create_client("google")
    if google is None:
        return templates.TemplateResponse(
            "admin_login.html",
            {
                "request": request,
                "error": (
                    "Google login is not configured. Set GOOGLE_CLIENT_ID, "
                    "GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI in .env."
                ),
                "message": None,
                "admin_email": ADMIN_EMAIL,
                "google_oauth_enabled": False,
            },
            status_code=400,
        )

    try:
        token = await google.authorize_access_token(request)
    except OAuthError as exc:
        logger.exception("Google OAuth callback failed: %s", exc)
        return templates.TemplateResponse(
            "admin_login.html",
            {
                "request": request,
                "error": f"Google sign-in failed: {exc.error or 'authentication error'}",
                "message": None,
                "admin_email": ADMIN_EMAIL,
                "google_oauth_enabled": True,
            },
            status_code=400,
        )

    userinfo = token.get("userinfo") or {}
    email = str(userinfo.get("email", "")).strip().lower()
    email_verified = bool(userinfo.get("email_verified"))
    expected_email = ADMIN_EMAIL.strip().lower()

    if not email or not email_verified:
        request.session.clear()
        return templates.TemplateResponse(
            "admin_login.html",
            {
                "request": request,
                "error": "Google did not return a verified email address for this account.",
                "message": None,
                "admin_email": ADMIN_EMAIL,
                "google_oauth_enabled": True,
            },
            status_code=403,
        )

    if expected_email and email != expected_email:
        request.session.clear()
        return templates.TemplateResponse(
            "admin_login.html",
            {
                "request": request,
                "error": f"{email} is not authorized for admin access.",
                "message": None,
                "admin_email": ADMIN_EMAIL,
                "google_oauth_enabled": True,
            },
            status_code=403,
        )

    request.session["admin_email"] = email
    request.session["admin_name"] = str(userinfo.get("name", "")).strip()
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/logout")
async def admin_logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/admin/login", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request) -> Response:
    if not _is_admin_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "companies": list_company_configs(),
            "error": None,
            "message": None,
        },
    )


@app.post("/admin/companies", response_class=HTMLResponse)
async def admin_save_company(
    request: Request,
    careers_page_url: str = Form(...),
    extraction_instructions: str = Form(...),
) -> Response:
    if not _is_admin_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=303)

    try:
        save_company_config(careers_page_url, extraction_instructions)
    except Exception as exc:
        return templates.TemplateResponse(
            "admin_dashboard.html",
            {
                "request": request,
                "companies": list_company_configs(),
                "error": str(exc),
                "message": None,
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        "admin_dashboard.html",
        {
            "request": request,
            "companies": list_company_configs(),
            "error": None,
            "message": "Company instructions saved.",
        },
    )


@app.post("/admin/sync-now")
async def admin_sync_now(request: Request) -> RedirectResponse:
    if not _is_admin_authenticated(request):
        return RedirectResponse(url="/admin/login", status_code=303)
    scheduler.run_now()
    return RedirectResponse(url="/admin", status_code=303)


async def _run_analysis(
    company_websites: str,
    preferred_location: str,
    resume: UploadFile,
    cover_letter: UploadFile | None,
) -> tuple[MatchResult, list[str]]:
    logger.info("Starting analysis pipeline")
    scraper = CareerSiteScraper()
    resume_text = await _save_and_extract_upload(resume)
    cover_letter_text = ""
    if cover_letter and cover_letter.filename:
        cover_letter_text = await _save_and_extract_upload(cover_letter)

    matcher = OpenAIJobMatcher()
    urls = _resolve_company_urls(company_websites)
    location_filters = _parse_location_filters(preferred_location)

    aggregated_matches: list[dict] = []
    stored_files: list[str] = []
    notes: list[str] = []

    for company_url in urls:
        logger.info("Running analysis for %s", company_url)
        scraped_text, scraped_file_path = _load_or_scrape_company(scraper, company_url)
        if not scraped_text:
            notes.append(f"No career pages were scraped for {company_url}.")
            continue
        if scraped_file_path:
            stored_files.append(str(scraped_file_path))

        try:
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
        aggregated_matches.extend(filtered_matches)
        if result.notes:
            notes.append(f"{company_url}: {result.notes}")

    return MatchResult(matches=aggregated_matches, notes="\n".join(notes)), stored_files


def _load_or_scrape_company(scraper: CareerSiteScraper, company_url: str) -> tuple[str, Path | None]:
    company_slug = company_slug_from_url(company_url)
    stored_text = read_company_scrape_text(company_slug)
    if stored_text:
        logger.info("Using stored scheduled scrape for %s", company_url)
        return stored_text, None

    pages = scraper.scrape_company(company_url)
    if not pages:
        return "", None
    scraped_text = scraper.build_text_dump(company_url, pages)
    return scraped_text, write_scraped_content(company_url, scraped_text)


def _resolve_company_urls(company_websites: str) -> list[str]:
    typed_urls = [line.strip() for line in company_websites.splitlines() if line.strip()]
    if typed_urls:
        return typed_urls

    registered_urls = [company.careers_page_url for company in list_company_configs()]
    if registered_urls:
        return registered_urls

    raise ValueError("Provide company websites or register companies from the admin page first.")


async def _save_and_extract_upload(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "upload.txt").suffix or ".txt"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(await upload.read())
        temp_path = Path(temp_file.name)
    try:
        return extract_text_from_upload(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _is_admin_authenticated(request: Request) -> bool:
    admin_email = request.session.get("admin_email", "").strip().lower()
    if not admin_email:
        return False
    if ADMIN_EMAIL and admin_email != ADMIN_EMAIL.strip().lower():
        return False
    return True


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
