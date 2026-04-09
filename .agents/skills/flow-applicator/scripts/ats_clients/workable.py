"""
Workable ATS API client.

Workable exposes two public APIs for job listings:

1. jobs.workable.com global job board (no auth, no CSRF needed for GET):
   GET  https://jobs.workable.com/api/v1/jobs?q={query}&limit={n}
   Returns: {"totalSize": N, "jobs": [...], "nextPageToken": "..."}
   This is the PRIMARY public search endpoint.

2. Company SPI v3 (requires company Bearer token, 401 without it):
   GET  https://{subdomain}.workable.com/spi/v3/jobs?state=published
   GET  https://{subdomain}.workable.com/spi/v3/jobs/{shortcode}
   GET  https://{subdomain}.workable.com/spi/v3/jobs/{shortcode}/application_form

Candidate submission (company auth required):
  POST https://{subdomain}.workable.com/spi/v3/candidates

Job listing page URLs:
  https://apply.workable.com/{company}/j/{shortcode}
  https://{sub}.workable.com/j/{shortcode}
"""

import base64
import time
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlencode

try:
    import requests
except ImportError as e:
    raise ImportError("Install requests: pip install requests") from e

# ---------------------------------------------------------------------------
# Known Workable company subdomains
# ---------------------------------------------------------------------------

KNOWN_SUBDOMAINS: list[str] = [
    "zendesk",
    "postman",
    "semrush",
    "hubspot",
    "typeform",
    "intercom",
    "zapier",
    "buffer",
    "mailchimp",
    "wistia",
    "hotjar",
    "mixpanel",
    "segment",
    "heap",
    "amplitude",
    "pendo",
    "fullstory",
    "looker",
    "domo",
    "chartio",
    "brex",
    "figma",
    "notion",
    "loom",
    "airtable",
    "gusto",
    "lattice",
    "rippling",
    "deel",
    "remote",
]

# ---------------------------------------------------------------------------
# Rate-limit helper
# ---------------------------------------------------------------------------

_RATE_LIMIT_SLEEP = 0.3  # seconds between requests


def _sleep() -> None:
    time.sleep(_RATE_LIMIT_SLEEP)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize_job(raw: dict, subdomain: str) -> dict:
    """Convert a raw Workable job dict to the standard normalized format."""
    location_obj = raw.get("location", {})
    location_str = location_obj.get("city", "")
    if location_obj.get("region"):
        location_str = f"{location_str}, {location_obj['region']}".strip(", ")
    if location_obj.get("country"):
        location_str = f"{location_str}, {location_obj['country']}".strip(", ")

    shortcode = raw.get("shortcode", raw.get("id", ""))
    url = (
        raw.get("url")
        or raw.get("application_url")
        or (f"https://apply.workable.com/{subdomain}/j/{shortcode}")
    )

    return {
        "title": raw.get("title", ""),
        "company": raw.get("company", {}).get("name", subdomain),
        "location": location_str or raw.get("location_str", ""),
        "url": url,
        "job_id": f"workable_{subdomain}_{shortcode}",
        "shortcode": shortcode,
        "subdomain": subdomain,
        "description": raw.get("description", raw.get("full_description", "")),
        "department": raw.get("department", ""),
        "remote": bool(raw.get("remote", location_obj.get("telecommuting", False))),
        "employment_type": raw.get("employment_type", ""),
        "experience": raw.get("experience", ""),
        "education": raw.get("education", ""),
        "state": raw.get("state", "published"),
        "created_at": raw.get("created_at", ""),
        "published_on": raw.get("published_on", ""),
        "source": "workable",
    }


# ---------------------------------------------------------------------------
# WorkableClient
# ---------------------------------------------------------------------------


class WorkableClient:
    """
    Client for the Workable SPI v3 API.

    Usage (job listing — no auth needed):
        client = WorkableClient()
        jobs = client.get_jobs("zapier", location="Remote", remote=True)

    Usage (candidate submission — requires Bearer token):
        client = WorkableClient(api_token="your_company_token")
        result = client.submit_application("zapier", "AB1234", answers, "/path/to/resume.pdf")
    """

    BASE_TEMPLATE = "https://{subdomain}.workable.com/spi/v3"
    APPLY_URL_TEMPLATE = "https://apply.workable.com/{subdomain}/j/{shortcode}"

    def __init__(
        self,
        api_token: Optional[str] = None,
        timeout: int = 15,
        rate_limit_sleep: float = _RATE_LIMIT_SLEEP,
    ) -> None:
        self.api_token = api_token
        self.timeout = timeout
        self.rate_limit_sleep = rate_limit_sleep

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "JobSearchBot/1.0 (automated job search)",
            }
        )
        if api_token:
            self._session.headers["Authorization"] = f"Bearer {api_token}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base(self, subdomain: str) -> str:
        return self.BASE_TEMPLATE.format(subdomain=subdomain)

    def _get(self, url: str, params: Optional[dict] = None) -> dict | list:
        _sleep()
        resp = self._session.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _post(self, url: str, json_body: dict) -> dict:
        _sleep()
        resp = self._session.post(url, json=json_body, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Public API — job listings
    # ------------------------------------------------------------------

    def get_jobs(
        self,
        subdomain: str,
        location: str = "",
        remote: bool = False,
        department: str = "",
        limit: int = 50,
    ) -> list[dict]:
        """
        Fetch published jobs from one Workable subdomain via the SPI v3 API.

        GET https://{subdomain}.workable.com/spi/v3/jobs
        Params: state=published, limit, offset, location, remote, department

        NOTE: Most company boards are private (returns 401/403/404).
        Returns [] for all auth/not-found errors — use search_jobs() for
        public global search via jobs.workable.com instead.

        Returns a list of normalized job dicts.
        """
        url = f"{self._base(subdomain)}/jobs"
        params: dict = {"state": "published", "limit": min(limit, 100)}
        if location:
            params["location"] = location
        if remote:
            params["remote"] = "true"
        if department:
            params["department"] = department

        try:
            data = self._get(url, params=params)
        except requests.HTTPError as exc:
            # 401/403/404 means subdomain requires auth or doesn't exist
            if exc.response is not None and exc.response.status_code in (401, 403, 404):
                return []
            raise

        jobs_raw = data.get("jobs", data) if isinstance(data, dict) else data
        return [_normalize_job(j, subdomain) for j in jobs_raw if isinstance(j, dict)]

    def search_jobs(
        self,
        query: str,
        location: str = "",
        subdomains: Optional[list[str]] = None,
        remote: bool = False,
        limit: int = 25,
    ) -> list[dict]:
        """
        Search for jobs using the public jobs.workable.com global board.

        Primary: GET https://jobs.workable.com/api/v1/jobs?q={query}&limit={n}
        Returns up to `limit` normalized job dicts.

        If `subdomains` is provided, falls back to iterating those subdomains
        via get_jobs() instead (company SPI — mostly private, use for known
        authenticated subdomains only).
        """
        if subdomains is not None:
            return self._search_by_subdomains(
                query=query,
                location=location,
                subdomains=subdomains,
                remote=remote,
                limit=limit,
            )

        # Use the public jobs.workable.com board API
        return self._search_public_board(
            query=query,
            location=location,
            remote=remote,
            limit=limit,
        )

    def _search_public_board(
        self,
        query: str,
        location: str = "",
        remote: bool = False,
        limit: int = 25,
    ) -> list[dict]:
        """
        Search the public jobs.workable.com job board.

        GET https://jobs.workable.com/api/v1/jobs?q={query}&limit={n}
        Response: {"totalSize": N, "jobs": [...], "nextPageToken": "..."}
        """
        params: dict = {"q": query, "limit": min(limit, 100)}
        if location:
            params["location"] = location
        if remote:
            params["workplace"] = "remote"

        url = "https://jobs.workable.com/api/v1/jobs"
        try:
            _sleep()
            resp = self._session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        raw_jobs = data.get("jobs", [])
        results = []
        for raw in raw_jobs:
            if not isinstance(raw, dict):
                continue
            company_obj = raw.get("company", {})
            company_name = (
                company_obj.get("title", "")
                if isinstance(company_obj, dict)
                else str(company_obj)
            )
            # Extract subdomain from URL if available
            job_url = raw.get("url", "")
            subdomain = ""
            if job_url:
                sub, _ = self.extract_subdomain_and_code_from_url(job_url)
                subdomain = sub

            location_obj = raw.get("location", {})
            if isinstance(location_obj, dict):
                loc_parts = [
                    location_obj.get("city", ""),
                    location_obj.get("region", ""),
                    location_obj.get("country", ""),
                ]
                location_str = ", ".join(p for p in loc_parts if p)
            else:
                location_str = str(location_obj) if location_obj else ""

            workplace = raw.get("workplace", "")
            is_remote = workplace in ("remote", "hybrid") or raw.get("remote", False)

            results.append(
                {
                    "title": raw.get("title", ""),
                    "company": company_name,
                    "location": location_str,
                    "url": job_url,
                    "job_id": f"workable_{raw.get('id', '')}",
                    "shortcode": "",
                    "subdomain": subdomain,
                    "description": raw.get("description", ""),
                    "department": raw.get("department", ""),
                    "remote": is_remote,
                    "employment_type": raw.get(
                        "employmentType", raw.get("employment_type", "")
                    ),
                    "experience": raw.get("experience", ""),
                    "education": raw.get("education", ""),
                    "state": raw.get("state", "published"),
                    "created_at": raw.get("created", raw.get("created_at", "")),
                    "published_on": raw.get("updated", raw.get("published_on", "")),
                    "source": "workable",
                }
            )

        return results[:limit]

    def _search_by_subdomains(
        self,
        query: str,
        location: str = "",
        subdomains: Optional[list[str]] = None,
        remote: bool = False,
        limit: int = 25,
    ) -> list[dict]:
        """
        Search by iterating specific company subdomains via SPI v3.
        Mostly private — use only for subdomains where you have auth.
        """
        targets = subdomains if subdomains is not None else KNOWN_SUBDOMAINS
        query_lower = query.lower()
        query_terms = [t.strip() for t in query_lower.split() if t.strip()]

        results: list[tuple[int, dict]] = []

        for subdomain in targets:
            try:
                jobs = self.get_jobs(subdomain, location=location, remote=remote)
            except Exception:
                continue

            for job in jobs:
                title_lower = job.get("title", "").lower()
                desc_lower = job.get("description", "").lower()

                score = sum(
                    2 if t in title_lower else (1 if t in desc_lower else 0)
                    for t in query_terms
                )
                if score > 0:
                    results.append((score, job))

            if len(results) >= limit * 3:
                break

        seen: set[str] = set()
        deduped: list[dict] = []
        for _score, job in sorted(results, key=lambda x: x[0], reverse=True):
            jid = job["job_id"]
            if jid not in seen:
                seen.add(jid)
                deduped.append(job)
            if len(deduped) >= limit:
                break

        return deduped

    def get_job(self, subdomain: str, shortcode: str) -> dict:
        """
        Fetch full job details for a single posting.

        GET https://{subdomain}.workable.com/spi/v3/jobs/{shortcode}
        Returns a normalized job dict with full description.
        """
        url = f"{self._base(subdomain)}/jobs/{shortcode}"
        data = self._get(url)
        return _normalize_job(data, subdomain)

    def get_application_form(self, subdomain: str, shortcode: str) -> dict:
        """
        Fetch the application form schema for a job.

        GET https://{subdomain}.workable.com/spi/v3/jobs/{shortcode}/application_form

        Returns a dict with:
            {
                "form_fields": [...],   # list of field dicts
                "questions": [...],     # custom screening questions
            }

        Each field dict has: key, label, type, required, choices (optional).
        """
        url = f"{self._base(subdomain)}/jobs/{shortcode}/application_form"
        data = self._get(url)

        # Normalize field structures for consistency with flow engine
        form_fields = []
        for field in data.get("form_fields", []):
            form_fields.append(
                {
                    "key": field.get("key", ""),
                    "label": field.get("label", field.get("key", "")),
                    "type": field.get("type", "input"),
                    "required": bool(field.get("required", False)),
                    "choices": field.get("choices", []),
                    "max_length": field.get("max_length"),
                }
            )

        questions = []
        for q in data.get("questions", []):
            questions.append(
                {
                    "id": q.get("id", ""),
                    "body": q.get("body", ""),
                    "type": q.get("type", "short_text"),
                    "required": bool(q.get("required", False)),
                    "choices": q.get("choices", []),
                }
            )

        return {
            "subdomain": subdomain,
            "shortcode": shortcode,
            "form_fields": form_fields,
            "questions": questions,
            "raw": data,
        }

    # ------------------------------------------------------------------
    # Public API — candidate submission
    # ------------------------------------------------------------------

    def submit_application(
        self,
        subdomain: str,
        shortcode: str,
        answers: dict,
        resume_path: Optional[str] = None,
    ) -> dict:
        """
        Submit a job application via the Workable candidates API.

        Requires `api_token` set on the client (company Bearer token).

        POST https://{subdomain}.workable.com/spi/v3/candidates

        `answers` should contain:
            {
                "name": "Full Name",
                "email": "email@example.com",
                "phone": "+1-555-0000",
                "linkedin": "https://linkedin.com/in/...",
                "portfolio": "https://...",
                "summary": "Cover letter / summary text",
                "questions": [
                    {"question_key": "q_123", "answer": "My answer"}
                ],
                "education": [...],   # optional
                "experience": [...],  # optional
            }

        If `resume_path` is provided, it will be base64-encoded and included
        in the payload. The Workable API accepts:
            candidate.resume_url  — public HTTPS URL to resume
            candidate.resume      — base64-encoded resume (fallback)

        Returns the API response dict (created candidate record).
        """
        if not self.api_token:
            raise ValueError(
                "api_token is required for candidate submission. "
                "Set WorkableClient(api_token='your_token')."
            )

        # Build candidate payload
        candidate: dict = {
            "name": answers.get("name", ""),
            "email": answers.get("email", ""),
            "phone": answers.get("phone", ""),
            "summary": answers.get("summary", ""),
            "social_profiles": [],
        }

        if answers.get("linkedin"):
            candidate["social_profiles"].append(
                {"type": "linkedin", "url": answers["linkedin"]}
            )
        if answers.get("portfolio"):
            candidate["social_profiles"].append(
                {"type": "portfolio", "url": answers["portfolio"]}
            )
        if answers.get("github"):
            candidate["social_profiles"].append(
                {"type": "github", "url": answers["github"]}
            )

        # Resume: prefer URL, fall back to base64
        if answers.get("resume_url"):
            candidate["resume_url"] = answers["resume_url"]
        elif resume_path:
            resume_bytes = Path(resume_path).read_bytes()
            candidate["resume"] = base64.b64encode(resume_bytes).decode("utf-8")
            candidate["resume_filename"] = Path(resume_path).name

        # Custom screening question answers
        if answers.get("questions"):
            candidate["answers"] = [
                {"question_key": qa["question_key"], "answer": qa["answer"]}
                for qa in answers["questions"]
            ]

        payload = {
            "sourced": True,
            "shortcode": shortcode,
            "candidate": candidate,
        }

        url = f"{self._base(subdomain)}/candidates"
        try:
            return self._post(url, payload)
        except requests.HTTPError as exc:
            return {
                "error": str(exc),
                "status_code": exc.response.status_code if exc.response else None,
                "body": exc.response.text if exc.response else "",
                "submitted": False,
            }

    # ------------------------------------------------------------------
    # URL parsing
    # ------------------------------------------------------------------

    def extract_subdomain_and_code_from_url(self, url: str) -> tuple[str, str]:
        """
        Parse a Workable job URL and return (subdomain, shortcode).

        Handles:
          https://apply.workable.com/{company}/j/{shortcode}
          https://{sub}.workable.com/j/{shortcode}
          https://{sub}.workable.com/jobs/{shortcode}
          https://apply.workable.com/companies/{company}/jobs/{shortcode}

        Returns ("", "") if the URL cannot be parsed.
        """
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        path = parsed.path.rstrip("/")

        # Pattern 1: apply.workable.com/{company}/j/{shortcode}
        m = re.match(r"^/([^/]+)/j/([^/]+)$", path)
        if m and "apply.workable.com" in host:
            return m.group(1), m.group(2)

        # Pattern 2: apply.workable.com/companies/{company}/jobs/{shortcode}
        m = re.match(r"^/companies/([^/]+)/jobs/([^/]+)$", path)
        if m and "apply.workable.com" in host:
            return m.group(1), m.group(2)

        # Pattern 3: {sub}.workable.com/j/{shortcode}
        m = re.match(r"^([^.]+)\.workable\.com$", host)
        if m:
            subdomain = m.group(1)
            # Exclude "apply" itself
            if subdomain != "apply":
                path_m = re.match(r"^/(?:j|jobs)/([^/]+)$", path)
                if path_m:
                    return subdomain, path_m.group(1)

        return "", ""

    # ------------------------------------------------------------------
    # Convenience: detect if a URL belongs to Workable
    # ------------------------------------------------------------------

    @staticmethod
    def is_workable_url(url: str) -> bool:
        """Return True if the URL is a Workable job or apply URL."""
        return bool(
            re.search(r"(apply\.workable\.com|\.workable\.com)", url, re.IGNORECASE)
        )
