from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import OPENAI_API_KEY, OPENAI_MODEL
from app.models import MatchResult

logger = logging.getLogger(__name__)


class OpenAIJobMatcher:
    def __init__(self) -> None:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set.")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ValueError(
                "The 'openai' package is not installed. Run 'pip install -r requirements.txt'."
            ) from exc
        self.client = OpenAI(api_key=OPENAI_API_KEY)
        logger.info("OpenAI client initialized with model %s", OPENAI_MODEL)

    def match_jobs(
        self,
        resume_text: str,
        cover_letter_text: str,
        company_url: str,
        scraped_text: str,
        preferred_location: str = "",
    ) -> MatchResult:
        logger.info(
            "Submitting OpenAI match request for %s with resume length %s, cover letter length %s, scraped text length %s, preferred location %s",
            company_url,
            len(resume_text),
            len(cover_letter_text),
            len(scraped_text),
            preferred_location or "<none>",
        )
        response = self.client.responses.create(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are a recruiting assistant. Read the scraped careers text and "
                        "identify jobs that match the candidate resume. Only use roles that "
                        "actually appear in the provided scraped text. Restrict results to "
                        "software engineering roles such as 'Senior Software Engineer', "
                        "'Software Engineer II', or 'Software Engineer III', including close "
                        "naming variants such as 'Software Engineer 2', 'Software Engineer 3', "
                        "'SWE II', 'SWE III', 'Software Developer II', 'Software Developer III', "
                        "'Software Engineer C++', 'Software Engineer Android', or 'Software "
                        "Engineer iOS'. Exclude internships, staff/principal/lead/manager roles, and non-software "
                        "engineering jobs. Always return the job location exactly as stated in the posting when "
                        "available, otherwise return 'Unknown'. If a preferred location is provided, only return "
                        "roles that match that location or clearly indicate remote compatibility with it. If a job "
                        "ID is missing, infer a stable posting identifier from the posting URL or title."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Company website: {company_url}\n\n"
                        f"Preferred location filter: {preferred_location or 'None'}\n\n"
                        f"Resume:\n{resume_text}\n\n"
                        f"Cover letter:\n{cover_letter_text}\n\n"
                        f"Scraped careers data:\n{scraped_text}"
                    ),
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "job_match_result",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "matches": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "job_id": {"type": "string"},
                                        "title": {"type": "string"},
                                        "location": {"type": "string"},
                                        "company_url": {"type": "string"},
                                        "source_url": {"type": "string"},
                                        "reason": {"type": "string"},
                                    },
                                    "required": [
                                        "job_id",
                                        "title",
                                        "location",
                                        "company_url",
                                        "source_url",
                                        "reason",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                            "notes": {"type": "string"},
                        },
                        "required": ["matches", "notes"],
                        "additionalProperties": False,
                    },
                }
            },
        )
        logger.info("Received OpenAI response for %s", company_url)
        parsed = MatchResult.model_validate(json.loads(response.output_text))
        logger.info("Parsed %s match(es) from OpenAI response for %s", len(parsed.matches), company_url)
        return parsed


def extract_text_from_upload(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    logger.info("Extracting text from upload %s with suffix %s", file_path.name, suffix or "<none>")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise ValueError(
                "PDF support requires 'pypdf'. Run 'pip install -r requirements.txt'."
            ) from exc
        reader = PdfReader(str(file_path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        logger.info("Extracted %s characters from PDF %s", len(text), file_path.name)
        return text
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise ValueError(
                "DOCX support requires 'python-docx'. Run 'pip install -r requirements.txt'."
            ) from exc
        document = Document(str(file_path))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs).strip()
        logger.info("Extracted %s characters from DOCX %s", len(text), file_path.name)
        return text
    text = file_path.read_text(encoding="utf-8", errors="ignore").strip()
    logger.info("Extracted %s characters from text file %s", len(text), file_path.name)
    return text
