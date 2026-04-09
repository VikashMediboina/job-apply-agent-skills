"""
Lever ATS API client.

Lever provides a public Job Postings API that requires no authentication for
reading job listings. Rate limit: 10 requests/second (enforced via sleep).

API base: https://api.lever.co/v0/postings/{site}
Apply:    https://jobs.lever.co/{site}/{posting_id}/apply

Usage::

    from ats_clients.lever import LeverClient

    client = LeverClient()

    # Search across known company sites
    jobs = client.search_jobs("software engineer", location="remote", limit=50)

    # Fetch jobs for a specific company
    stripe_jobs = client.get_jobs("stripe", location="remote")

    # Get a single posting
    job = client.get_job("stripe", "abc123-def456")

    # Submit an application
    result = client.submit_application(
        site="stripe",
        posting_id="abc123-def456",
        answers={
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "+1-555-123-4567",
            "org": "Acme Corp",
            "urls[LinkedIn]": "https://linkedin.com/in/janedoe",
            "urls[GitHub]": "https://github.com/janedoe",
            "comments": "Excited about this opportunity.",
        },
        resume_path="/path/to/resume.pdf",
    )
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional
from pathlib import Path
import urllib.parse

try:
    import requests
    from requests import Response, Session
except ImportError as e:
    raise ImportError(
        "The 'requests' library is required for LeverClient. "
        "Install it with: pip install requests"
    ) from e


# ── Constants ──────────────────────────────────────────────────────────────────

API_BASE = "https://api.lever.co/v0/postings"
APPLY_BASE = "https://jobs.lever.co"
RATE_LIMIT_SLEEP = 0.1  # 10 req/sec per Lever docs

# Known company Lever site slugs (used for multi-site search)
# Ordered with verified-active sites first
KNOWN_SITES: list[str] = [
    "plaid",
    # Legacy slugs — some companies have migrated away from Lever
    "stripe",
    "airbnb",
    "lyft",
    "pinterest",
    "dropbox",
    "square",
    "zendesk",
    "twilio",
    "sendgrid",
    "cloudflare",
    "figma",
    "notion",
    "linear",
    "loom",
    "airtable",
    "brex",
    "ramp",
    "coinbase",
    "robinhood",
    # Extended common tech company slugs
    "vercel",
    "netlify",
    "supabase",
    "retool",
    "segment",
    "mixpanel",
    "amplitude",
    "datadog",
    "pagerduty",
    "confluent",
]

# Job posting URL pattern for Lever
# Accepts standard UUIDs (36 chars) and non-standard ID formats (for flexibility)
LEVER_URL_PATTERN = re.compile(
    r"(?:https?://)?jobs\.lever\.co/([^/]+)/([a-f0-9][a-f0-9-]{2,})"
)


# ── Normalized Job Dict ────────────────────────────────────────────────────────


def _normalize_posting(posting: dict, site: str) -> dict:
    """Normalize a raw Lever posting dict to the standard job dict format.

    Returns a dict with keys:
        title, company, location, url, job_id, site, description,
        categories, commitment, team, tags, source
    """
    categories = posting.get("categories", {})
    lists = posting.get("lists", [])

    # Build plain-text description from the lists structure
    description_parts: list[str] = []
    text_body = posting.get("text", "") or posting.get("descriptionPlain", "")
    if text_body:
        description_parts.append(text_body.strip())
    for lst in lists:
        heading = lst.get("text", "")
        content = lst.get("content", "")
        if heading:
            description_parts.append(f"\n{heading}")
        if content:
            # Strip HTML tags for plain text
            plain = re.sub(r"<[^>]+>", " ", content)
            plain = re.sub(r"\s+", " ", plain).strip()
            description_parts.append(plain)

    description = "\n".join(description_parts).strip()

    posting_id = posting.get("id", "")
    posting_url = posting.get("hostedUrl", "") or f"{APPLY_BASE}/{site}/{posting_id}"

    return {
        "title": posting.get("text", "").strip(),
        "company": site.replace("-", " ").title(),
        "location": categories.get("location", ""),
        "url": posting_url,
        "applyUrl": f"{APPLY_BASE}/{site}/{posting_id}/apply",
        "job_id": posting_id,
        "site": site,
        "description": description,
        "categories": {
            "commitment": categories.get("commitment", ""),
            "department": categories.get("department", ""),
            "location": categories.get("location", ""),
            "team": categories.get("team", ""),
            "allLocations": categories.get("allLocations", []),
        },
        "commitment": categories.get("commitment", ""),
        "team": categories.get("team", ""),
        "department": categories.get("department", ""),
        "tags": posting.get("tags", []),
        "createdAt": posting.get("createdAt", 0),
        "source": "lever",
        "raw": posting,
    }


# ── Client ─────────────────────────────────────────────────────────────────────


class LeverClient:
    """HTTP client for the Lever public Job Postings API.

    The Lever API requires no authentication for reading job postings.
    All methods enforce a 100 ms delay between requests (10 req/sec).

    Args:
        timeout: Request timeout in seconds (default 15).
        session: Optional ``requests.Session`` for connection reuse / mocking.
    """

    def __init__(
        self,
        timeout: int = 15,
        session: Optional[Session] = None,
    ) -> None:
        self.timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "flow-applicator/1.0 (job-automation)",
            }
        )

    # ── Private helpers ────────────────────────────────────────────────────────

    def _get(self, url: str, params: Optional[dict] = None) -> Any:
        """Perform a GET request with rate limiting and return parsed JSON."""
        time.sleep(RATE_LIMIT_SLEEP)
        response: Response = self._session.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def _post_multipart(
        self, url: str, data: dict, files: Optional[dict] = None
    ) -> Any:
        """Perform a POST request with multipart form data."""
        time.sleep(RATE_LIMIT_SLEEP)
        response: Response = self._session.post(
            url, data=data, files=files, timeout=self.timeout
        )
        response.raise_for_status()
        # Lever's apply endpoint may return HTML on success — handle gracefully
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return {"status": "submitted", "statusCode": response.status_code}

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_jobs(
        self,
        site: str,
        location: str = "",
        team: str = "",
        commitment: str = "",
        group: str = "",
        limit: Optional[int] = None,
    ) -> list[dict]:
        """Fetch all job postings for a Lever company site.

        Args:
            site: Company slug (e.g. "stripe", "airbnb").
            location: Filter by location string (case-insensitive substring match).
            team: Filter by team name.
            commitment: Filter by work type (e.g. "Full-time", "Intern").
            group: Group results by field ("team", "location", "commitment").
            limit: Maximum number of results to return (default: all).

        Returns:
            List of normalized job dicts. Empty list if the site has no postings
            or returns a non-200 response.
        """
        url = f"{API_BASE}/{site}"
        params: dict[str, str] = {"mode": "json"}
        if location:
            params["location"] = location
        if team:
            params["team"] = team
        if commitment:
            params["commitment"] = commitment
        if group:
            params["group"] = group

        try:
            data = self._get(url, params=params)
        except Exception:
            return []

        # API returns a list when mode=json
        if not isinstance(data, list):
            return []

        results = [_normalize_posting(p, site) for p in data]
        if limit is not None:
            results = results[:limit]
        return results

    def search_jobs(
        self,
        query: str,
        location: str = "",
        sites: Optional[list[str]] = None,
        limit: int = 25,
    ) -> list[dict]:
        """Search for jobs across multiple known Lever company sites.

        Fetches all postings from each site and filters by keyword match
        against the job title and description (case-insensitive).

        Args:
            query: Search keywords (e.g. "software engineer python").
            location: Optional location filter (e.g. "remote", "San Francisco").
            sites: List of Lever site slugs to search. Defaults to KNOWN_SITES.
            limit: Maximum number of results to return.

        Returns:
            List of matching normalized job dicts, sorted by site.
        """
        if sites is None:
            sites = KNOWN_SITES

        keywords = [kw.lower() for kw in query.split() if kw]
        results: list[dict] = []

        for site in sites:
            if len(results) >= limit:
                break

            postings = self.get_jobs(site, location=location)
            for posting in postings:
                if len(results) >= limit:
                    break

                # Keyword match against title and description
                search_text = f"{posting['title']} {posting['description']}".lower()
                if all(kw in search_text for kw in keywords):
                    results.append(posting)

        return results[:limit]

    def get_job(self, site: str, posting_id: str) -> dict:
        """Fetch a single Lever job posting.

        Args:
            site: Company slug (e.g. "stripe").
            posting_id: UUID of the posting (e.g. "abc123-def456-...").

        Returns:
            Normalized job dict, or empty dict if not found.
        """
        url = f"{API_BASE}/{site}/{posting_id}"
        try:
            data = self._get(url, params={"mode": "json"})
        except Exception:
            return {}

        if not isinstance(data, dict):
            return {}

        return _normalize_posting(data, site)

    def get_application_form(self, site: str, posting_id: str) -> dict:
        """Fetch and parse the application form fields for a Lever posting.

        Lever embeds form field definitions in the posting JSON under
        ``additionalQuestions`` (custom questions added by the employer).

        Args:
            site: Company slug.
            posting_id: UUID of the posting.

        Returns:
            Dict with keys:
                ``posting``   — the normalized job dict
                ``standard``  — list of standard Lever fields always present
                ``custom``    — list of employer-defined additional questions
                ``allFields`` — combined ordered list for form filling
        """
        url = f"{API_BASE}/{site}/{posting_id}"
        try:
            raw = self._get(url, params={"mode": "json"})
        except Exception:
            return {}

        if not isinstance(raw, dict):
            return {}

        posting = _normalize_posting(raw, site)

        # Standard fields always present on every Lever application form
        standard_fields = [
            {"name": "name", "label": "Full Name", "type": "text", "required": True},
            {"name": "email", "label": "Email", "type": "email", "required": True},
            {"name": "phone", "label": "Phone", "type": "text", "required": False},
            {
                "name": "org",
                "label": "Current Company",
                "type": "text",
                "required": False,
            },
            {
                "name": "urls[LinkedIn]",
                "label": "LinkedIn",
                "type": "url",
                "required": False,
            },
            {
                "name": "urls[GitHub]",
                "label": "GitHub",
                "type": "url",
                "required": False,
            },
            {
                "name": "urls[Portfolio]",
                "label": "Portfolio / Website",
                "type": "url",
                "required": False,
            },
            {
                "name": "resume",
                "label": "Resume",
                "type": "file",
                "required": True,
                "accept": [".pdf", ".doc", ".docx"],
            },
            {
                "name": "comments",
                "label": "Additional information",
                "type": "textarea",
                "required": False,
            },
        ]

        # Additional custom questions from the employer
        raw_questions: list[dict] = raw.get("additionalQuestions", []) or []
        custom_fields: list[dict] = []
        for q in raw_questions:
            field: dict[str, Any] = {
                "name": q.get("id", q.get("text", "")[:30]),
                "label": q.get("text", ""),
                "type": _lever_field_type(q.get("type", "text")),
                "required": q.get("required", False),
            }
            if q.get("options"):
                field["options"] = [
                    opt.get("text", opt) if isinstance(opt, dict) else opt
                    for opt in q["options"]
                ]
            custom_fields.append(field)

        return {
            "posting": posting,
            "standard": standard_fields,
            "custom": custom_fields,
            "allFields": standard_fields + custom_fields,
        }

    def submit_application(
        self,
        site: str,
        posting_id: str,
        answers: dict[str, str],
        resume_path: str,
    ) -> dict:
        """Submit an application to a Lever job posting.

        Lever's apply endpoint accepts multipart/form-data at:
            POST https://jobs.lever.co/{site}/{posting_id}/apply

        Standard form fields (use exact names):
            name            — Full name
            email           — Email address
            phone           — Phone number (optional)
            org             — Current employer (optional)
            urls[LinkedIn]  — LinkedIn profile URL (optional)
            urls[GitHub]    — GitHub profile URL (optional)
            urls[Portfolio] — Portfolio / website URL (optional)
            comments        — Cover letter / additional info (optional)

        Args:
            site: Company slug (e.g. "stripe").
            posting_id: UUID of the posting.
            answers: Dict of field_name → value for text fields.
            resume_path: Absolute path to the resume file (PDF/DOC/DOCX).

        Returns:
            Dict with ``status``, ``statusCode``, and optional ``error``.
        """
        url = f"{APPLY_BASE}/{site}/{posting_id}/apply"
        resume_file = Path(resume_path)

        if not resume_file.exists():
            return {
                "status": "error",
                "error": f"Resume file not found: {resume_path}",
            }

        # Build form data (text fields)
        form_data = {k: v for k, v in answers.items() if isinstance(v, str)}

        # Attach resume as multipart file
        suffix = resume_file.suffix.lower()
        mime_types = {
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": (
                "application/vnd.openxmlformats-officedocument"
                ".wordprocessingml.document"
            ),
        }
        mime = mime_types.get(suffix, "application/octet-stream")

        try:
            with resume_file.open("rb") as fh:
                files = {"resume": (resume_file.name, fh, mime)}
                result = self._post_multipart(url, data=form_data, files=files)
        except requests.HTTPError as e:
            return {
                "status": "error",
                "statusCode": e.response.status_code if e.response else None,
                "error": str(e),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

        return result

    def extract_site_and_id_from_url(self, url: str) -> tuple[str, str]:
        """Parse a Lever job URL and return (site, posting_id).

        Handles these URL formats:
            https://jobs.lever.co/{site}/{uuid}
            https://jobs.lever.co/{site}/{uuid}/apply
            https://api.lever.co/v0/postings/{site}/{uuid}

        Args:
            url: The Lever job or apply URL.

        Returns:
            Tuple of (site, posting_id), or ("", "") if parsing fails.
        """
        # Try the canonical jobs.lever.co pattern first
        match = LEVER_URL_PATTERN.search(url)
        if match:
            return match.group(1), match.group(2)

        # Try api.lever.co/v0/postings/{site}/{uuid}
        api_pattern = re.compile(r"api\.lever\.co/v0/postings/([^/]+)/([a-f0-9-]{36})")
        api_match = api_pattern.search(url)
        if api_match:
            return api_match.group(1), api_match.group(2)

        return "", ""


# ── Helpers ────────────────────────────────────────────────────────────────────


def _lever_field_type(lever_type: str) -> str:
    """Map Lever's internal field type string to a standard HTML input type."""
    mapping = {
        "text": "text",
        "textarea": "textarea",
        "dropdown": "select",
        "multiple-choice": "radio",
        "multiple-select": "checkbox",
        "url": "url",
        "email": "email",
        "phone": "tel",
        "number": "number",
        "date": "date",
        "boolean": "checkbox",
    }
    return mapping.get(lever_type.lower(), "text")
