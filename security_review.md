# Security Review

Date: 2026-03-20
Scope: Static code review of the FastAPI application in this repository.

## Findings

### 1. High: Public analysis endpoints allow SSRF and internal network probing

The public `/analyze` and `/api/analyze` endpoints accept arbitrary `company_websites` input with no authentication or allowlist, pass that input into `_resolve_company_urls()`, and then fetch those URLs server-side through the scraper. An attacker can use this to make the server request internal or cloud-only endpoints if they are reachable from the runtime environment.

Relevant code:

- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L101)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L146)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L405)
- [app/services/scraper.py](/Users/vinitkumar/Documents/JobSearchAgent/app/services/scraper.py#L114)
- [app/services/scraper.py](/Users/vinitkumar/Documents/JobSearchAgent/app/services/scraper.py#L252)
- [app/services/scraper.py](/Users/vinitkumar/Documents/JobSearchAgent/app/services/scraper.py#L534)

Impact:

- Server-side requests to internal hosts or metadata services
- Internal network enumeration from the application environment
- Abuse of the app as a fetch proxy

### 2. High: Public analysis flow can be abused for cost amplification and third-party data forwarding

Anyone can upload files and force the server to scrape multiple sites and send the extracted content plus the uploaded resume and cover letter to OpenAI. There is no authentication, quota, rate limit, or request bounding on URL count or content size in this flow.

Relevant code:

- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L101)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L146)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L336)
- [app/services/openai_matcher.py](/Users/vinitkumar/Documents/JobSearchAgent/app/services/openai_matcher.py#L42)
- [app/services/openai_matcher.py](/Users/vinitkumar/Documents/JobSearchAgent/app/services/openai_matcher.py#L129)

Impact:

- Unbounded third-party API spend
- Abuse-driven load on scraping and parsing paths
- Forwarding of user-uploaded content to an external provider without access controls

### 3. High: Admin session security depends on a default secret

The app falls back to `SESSION_SECRET = "change-me-in-env"` and trusts the session cookie for admin authentication by checking the stored `admin_email`. If this default is used in any deployed environment, forging an authenticated admin session becomes realistic.

Relevant code:

- [app/config.py](/Users/vinitkumar/Documents/JobSearchAgent/app/config.py#L19)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L42)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L268)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L428)
- [app/templates/admin_login.html](/Users/vinitkumar/Documents/JobSearchAgent/app/templates/admin_login.html#L85)

Impact:

- Forged session cookies if the default secret is used
- Administrative access without completing the intended OAuth flow

### 4. Medium: File upload handling allows memory and CPU exhaustion

Uploaded files are read fully into memory with `await upload.read()` and then parsed without file-size, page-count, or complexity limits. Because the endpoint is public, an attacker can repeatedly submit oversized or parser-hostile files to consume memory and CPU.

Relevant code:

- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L417)
- [app/services/openai_matcher.py](/Users/vinitkumar/Documents/JobSearchAgent/app/services/openai_matcher.py#L184)

Impact:

- Memory exhaustion
- CPU exhaustion during PDF or DOCX parsing
- Service instability under repeated abusive requests

### 5. Medium: Internal errors are exposed to users

The UI returns `str(exc)` directly in several error paths, and OpenAI matching failures are surfaced in user-visible notes. This can leak operational details such as dependency names, parser behavior, remote fetch failures, and external service errors to unauthenticated callers.

Relevant code:

- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L117)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L124)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L303)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L311)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L374)
- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L385)

Impact:

- Information disclosure useful for reconnaissance
- Easier debugging of attacks by remote users

### 6. Medium: Session cookie hardening is incomplete

`SessionMiddleware` is configured only with `secret_key`. The code does not explicitly require secure cookies with `https_only`, does not tighten the cookie lifetime, and does not document deployment assumptions that would guarantee equivalent protection elsewhere.

Relevant code:

- [app/main.py](/Users/vinitkumar/Documents/JobSearchAgent/app/main.py#L42)

Impact:

- Increased risk of session exposure on non-HTTPS deployments
- Longer-than-necessary persistence of admin sessions

## Open Questions

- This review did not verify deployment-specific protections such as TLS termination, proxy configuration, ingress restrictions, WAF rules, or rate limiting.
- This was a static code review only. No live exploitation or runtime validation was performed.

## Recommended Remediation Order

1. Restrict or remove arbitrary user-supplied scrape targets. Enforce a strict allowlist or require admin-managed company URLs only.
2. Protect public analysis endpoints with authentication, rate limiting, request size limits, and URL-count limits.
3. Fail fast on startup if `SESSION_SECRET` is unset or left at the default placeholder value.
4. Harden session cookie settings, including secure transport requirements and narrower cookie lifetime.
5. Add upload size and parser safety limits for PDF, DOCX, and text processing.
6. Replace user-facing raw exception messages with generic errors and keep detailed diagnostics in server logs only.

## Review Notes

- This document reflects the security review results captured on 2026-03-20.
- No code changes were made as part of the review itself.
