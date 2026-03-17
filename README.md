# Job Search Agent

A FastAPI backend that:

1. accepts company websites, a resume, and an optional cover letter,
2. scrapes career-related pages from each company site,
3. stores scraped text in local `.txt` files,
4. sends the scraped data plus candidate documents to OpenAI for matching,
5. renders matching job IDs on a web page.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env` or your shell environment.

## Run

```bash
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Notes

- Scraping is heuristic. Some career sites render jobs with JavaScript or external ATS platforms, so you may need to extend the scraper for specific companies.
- Scraped files are written to `app/data/scraped_data/`.
- The OpenAI integration uses the Responses API. OpenAI recommends Responses for new projects, and structured outputs can be defined with `text.format` JSON schema support in Responses.
