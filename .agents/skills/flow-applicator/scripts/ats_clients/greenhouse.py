"""
Greenhouse Job Board API client.

Provides:
  - Public job board search (no auth required)
  - Application form introspection
  - Application submission via multipart form

Greenhouse API docs:
  https://developers.greenhouse.io/job-board.html

Rate limiting: 0.5s between requests (~2 req/sec).
No API key needed for reading public job boards.
Application submission uses the public Job Board API endpoint.
"""

from __future__ import annotations

import json
import mimetypes
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Optional


# ── Known tech company Greenhouse board tokens ─────────────────────
# These are the company "slug" identifiers used in Greenhouse URLs:
#   https://boards.greenhouse.io/{board_token}/jobs/{job_id}

KNOWN_BOARD_TOKENS: list[str] = [
    "airbnb",
    "stripe",
    "databricks",
    "openai",
    "anthropic",
    "figma",
    "notion",
    "linear",
    "vercel",
    "github",
    "gitlab",
    "cloudflare",
    "hashicorp",
    "datadog",
    "snowflakecomputing",  # Snowflake's actual slug
    "confluent",
    "elastic",
    "twilio",
    "hubspot",
    "coinbase",
    "lyft",
    "doordash",
    "robinhood",
    "plaid",
    "brex",
    "ramp",
    "scale",
    "airtable",
    "retool",
    "segment",
    "mixpanel",
    "amplitude",
    "asana",
    "intercom",
    "zendesk",
    "okta",
    "pagerduty",
    "digitalocean",
    "mongodb",
]

# Base URL for the Greenhouse Job Board API
_BOARDS_API_BASE = "https://boards-api.greenhouse.io/v1/boards"
# Base URL for the human-readable board pages
_BOARDS_BASE = "https://boards.greenhouse.io"

# Seconds to wait between API requests (stay well under rate limits)
_REQUEST_DELAY = 0.5


# ── HTTP helpers ───────────────────────────────────────────────────


def _get_json(url: str, timeout: int = 15) -> Any:
    """Fetch a URL and parse its JSON response.

    Raises:
        RuntimeError: On HTTP errors or JSON parse failures.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": (
                    "Mozilla/5.0 (compatible; JobApplicationBot/1.0; "
                    "+https://github.com/anthropics/flow-applicator)"
                ),
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error fetching {url}: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from {url}: {exc}") from exc


def _normalize_job(raw: dict, board_token: str, board_name: str = "") -> dict:
    """Normalize a raw Greenhouse job dict to a standard schema.

    Standard keys:
      title, company, location, url, job_id, board_token,
      description, departments, offices, updated_at, source
    """
    job_id = str(raw.get("id", ""))
    title = raw.get("title", "")
    location_obj = raw.get("location", {})
    location = (
        location_obj.get("name", "")
        if isinstance(location_obj, dict)
        else str(location_obj)
    )
    absolute_url = raw.get("absolute_url", "")
    if not absolute_url and job_id:
        absolute_url = f"{_BOARDS_BASE}/{board_token}/jobs/{job_id}"

    # Company name from board_name if not embedded in the job
    company = board_name or board_token

    # Extract plain-text description (content field is HTML)
    content_html = raw.get("content", "")
    description = re.sub(r"<[^>]+>", " ", content_html).strip() if content_html else ""

    # Departments / offices (lists of {id, name} dicts)
    depts = [d.get("name", "") for d in raw.get("departments", [])]
    offices = [o.get("name", "") for o in raw.get("offices", [])]

    return {
        "title": title,
        "company": company,
        "location": location,
        "url": absolute_url,
        "job_id": job_id,
        "board_token": board_token,
        "description": description,
        "departments": depts,
        "offices": offices,
        "updated_at": raw.get("updated_at", ""),
        "source": "greenhouse",
        # Pass-through raw for downstream processing if needed
        "_raw": raw,
    }


# ── Main client ───────────────────────────────────────────────────


class GreenhouseClient:
    """Client for the Greenhouse Job Board API.

    Provides read access to public job boards (no authentication required)
    and supports submitting applications via the public Job Board API.

    Example::

        client = GreenhouseClient()
        jobs = client.search_public_boards(
            query="software engineer",
            location="remote",
            boards=["stripe", "airbnb"],
        )
        for job in jobs:
            print(job["title"], job["company"], job["url"])
    """

    def __init__(self, request_delay: float = _REQUEST_DELAY) -> None:
        self._delay = request_delay
        self._last_request_time: float = 0.0

    # ── Rate limiting ──────────────────────────────────────────────

    def _rate_limit(self) -> None:
        """Enforce a minimum delay between requests."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)
        self._last_request_time = time.monotonic()

    def _fetch(self, url: str) -> Any:
        """Rate-limited JSON fetch."""
        self._rate_limit()
        return _get_json(url)

    # ── Board-level search ─────────────────────────────────────────

    def search_jobs(
        self,
        query: str,
        location: str = "",
        limit: int = 25,
        board_token: str = "",
    ) -> list[dict]:
        """Search a single Greenhouse board's public JSON feed.

        Because Greenhouse has no global search API, this fetches all jobs
        from the specified board and filters by keyword/location locally.

        Args:
            query:       Keyword(s) to match against job title and description.
            location:    Optional location string to filter against (case-insensitive).
            limit:       Maximum number of results to return.
            board_token: The Greenhouse board token (company slug) to search.
                         If empty, searches all boards in KNOWN_BOARD_TOKENS.

        Returns:
            List of normalized job dicts.
        """
        if not board_token:
            return self.search_public_boards(
                query=query, location=location, boards=KNOWN_BOARD_TOKENS, limit=limit
            )

        url = f"{_BOARDS_API_BASE}/{board_token}/jobs?content=true"
        try:
            data = self._fetch(url)
        except RuntimeError:
            return []

        jobs_raw = data.get("jobs", [])
        # Retrieve company name from meta if available
        company = data.get("meta", {}).get("company_name", board_token)
        results: list[dict] = []

        q_lower = query.lower()
        loc_lower = location.lower()

        for raw in jobs_raw:
            job = _normalize_job(raw, board_token, company)

            # Keyword match — check title and description
            title_lower = job["title"].lower()
            desc_lower = job["description"].lower()
            if q_lower and q_lower not in title_lower and q_lower not in desc_lower:
                # Try individual words for broader matching
                words = q_lower.split()
                if not any(w in title_lower or w in desc_lower for w in words):
                    continue

            # Location match (if requested)
            if loc_lower:
                job_loc_lower = job["location"].lower()
                if loc_lower not in job_loc_lower and loc_lower not in ("any", ""):
                    # Allow "remote" to match "anywhere" / empty location
                    if not (
                        loc_lower in ("remote",)
                        and (
                            "remote" in job_loc_lower
                            or "anywhere" in job_loc_lower
                            or not job["location"]
                        )
                    ):
                        continue

            results.append(job)
            if len(results) >= limit:
                break

        return results

    def search_public_boards(
        self,
        query: str,
        location: str = "",
        boards: Optional[list[str]] = None,
        limit: int = 25,
    ) -> list[dict]:
        """Search across multiple known Greenhouse company boards.

        Iterates the provided (or default) list of board tokens, fetching
        each board's public JSON feed and filtering results by keyword and
        location locally. Results are deduplicated by job_id.

        Args:
            query:    Keyword(s) to match against title/description.
            location: Optional location filter (e.g. "remote", "New York").
            boards:   List of board tokens to search. Defaults to KNOWN_BOARD_TOKENS.
            limit:    Maximum total results to collect across all boards.

        Returns:
            List of normalized job dicts, up to ``limit`` entries.
        """
        if boards is None:
            boards = KNOWN_BOARD_TOKENS

        all_results: list[dict] = []
        seen_ids: set[str] = set()

        for board_token in boards:
            if len(all_results) >= limit:
                break

            url = f"{_BOARDS_API_BASE}/{board_token}/jobs?content=true"
            try:
                data = self._fetch(url)
            except RuntimeError:
                # Skip boards that are unavailable / private
                continue

            jobs_raw = data.get("jobs", [])
            company = data.get("meta", {}).get("company_name", board_token)
            q_lower = query.lower()
            loc_lower = location.lower()

            for raw in jobs_raw:
                if len(all_results) >= limit:
                    break

                job = _normalize_job(raw, board_token, company)
                job_id = job["job_id"]

                if job_id in seen_ids:
                    continue

                # Keyword filter
                title_lower = job["title"].lower()
                desc_lower = job["description"].lower()
                if q_lower:
                    words = q_lower.split()
                    if not any(w in title_lower or w in desc_lower for w in words):
                        continue

                # Location filter
                if loc_lower and loc_lower not in ("any",):
                    job_loc_lower = job["location"].lower()
                    if loc_lower not in job_loc_lower:
                        if not (
                            loc_lower in ("remote",)
                            and (
                                "remote" in job_loc_lower
                                or "anywhere" in job_loc_lower
                                or not job["location"]
                            )
                        ):
                            continue

                seen_ids.add(job_id)
                all_results.append(job)

        return all_results

    # ── Job detail & form introspection ───────────────────────────

    def get_job_application_form(self, job_id: str, board_token: str) -> dict:
        """Fetch the application form questions for a specific job.

        Uses the ``?questions=true`` parameter to include custom questions.

        Args:
            job_id:      Greenhouse numeric job ID.
            board_token: Company board token (slug).

        Returns:
            Full job object including ``questions`` list.

        Raises:
            RuntimeError: If the job is not found or the API returns an error.
        """
        url = f"{_BOARDS_API_BASE}/{board_token}/jobs/{job_id}?questions=true"
        return self._fetch(url)

    # ── Application submission ─────────────────────────────────────

    def submit_application(
        self,
        job_id: str,
        board_token: str,
        answers: dict[str, Any],
        resume_path: str,
    ) -> dict:
        """Submit a job application via the Greenhouse Job Board API.

        Builds a multipart/form-data POST request with candidate fields,
        question answers, and the resume file attachment.

        The Greenhouse endpoint:
          POST https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}

        Core fields expected by Greenhouse (all str unless noted):
          first_name, last_name, email, phone, resume (file), cover_letter (file),
          linkedin_profile_url, website, question_{id} (custom question answers)

        Args:
            job_id:      Greenhouse numeric job ID.
            board_token: Company board token (slug).
            answers:     Dict mapping field names / question IDs to answer values.
                         Use keys like ``first_name``, ``email``, ``question_12345``.
            resume_path: Absolute path to the PDF resume to attach.

        Returns:
            Parsed JSON response from Greenhouse (typically
            ``{"id": ..., "success": true}`` or error details).

        Raises:
            RuntimeError: On HTTP errors or if the resume file is missing.
            FileNotFoundError: If ``resume_path`` does not exist.
        """
        resume_file = Path(resume_path)
        if not resume_file.exists():
            raise FileNotFoundError(f"Resume not found: {resume_path}")

        url = f"{_BOARDS_API_BASE}/{board_token}/jobs/{job_id}"

        # Build multipart form-data manually using Python stdlib
        boundary = "----FlowApplicatorBoundary7f3a9b2c"

        def _part_text(name: str, value: str) -> bytes:
            """Encode a text field as a multipart part."""
            return (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n'
                f"\r\n"
                f"{value}\r\n"
            ).encode("utf-8")

        def _part_file(name: str, filepath: Path) -> bytes:
            """Encode a binary file as a multipart part."""
            mime_type, _ = mimetypes.guess_type(filepath.name)
            mime_type = mime_type or "application/octet-stream"
            file_data = filepath.read_bytes()
            header = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filepath.name}"\r\n'
                f"Content-Type: {mime_type}\r\n"
                f"\r\n"
            ).encode("utf-8")
            return header + file_data + b"\r\n"

        parts: list[bytes] = []

        # Standard Greenhouse fields
        gh_field_map = {
            "first_name": answers.get("first_name", answers.get("firstName", "")),
            "last_name": answers.get("last_name", answers.get("lastName", "")),
            "email": answers.get("email", ""),
            "phone": answers.get("phone", ""),
            "linkedin_profile_url": answers.get(
                "linkedin_profile_url",
                answers.get("linkedin", answers.get("linkedIn", "")),
            ),
            "website": answers.get(
                "website", answers.get("portfolio", answers.get("github", ""))
            ),
        }

        for field_name, value in gh_field_map.items():
            if value:
                parts.append(_part_text(field_name, str(value)))

        # Resume file (required)
        parts.append(_part_file("resume", resume_file))

        # Cover letter (optional)
        cover_letter_path = answers.get("cover_letter_path", "")
        if cover_letter_path:
            cl_file = Path(cover_letter_path)
            if cl_file.exists():
                parts.append(_part_file("cover_letter", cl_file))

        # Custom question answers — keys formatted as "question_{id}"
        for key, value in answers.items():
            if key.startswith("question_") and value:
                parts.append(_part_text(key, str(value)))

        # Close boundary
        closing = f"--{boundary}--\r\n".encode("utf-8")
        body = b"".join(parts) + closing

        self._rate_limit()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
                "User-Agent": ("Mozilla/5.0 (compatible; JobApplicationBot/1.0)"),
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw_response = resp.read()
                try:
                    return json.loads(raw_response.decode("utf-8"))
                except json.JSONDecodeError:
                    return {
                        "success": resp.status in (200, 201),
                        "status": resp.status,
                        "raw": raw_response.decode("utf-8", errors="replace"),
                    }
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise RuntimeError(
                f"Greenhouse submission failed (HTTP {exc.code}): {error_body}"
            ) from exc

    # ── URL parsing ────────────────────────────────────────────────

    def extract_board_token_from_url(self, url: str) -> tuple[str, str]:
        """Extract the board_token and job_id from a Greenhouse job URL.

        Supports formats:
          - https://boards.greenhouse.io/{board_token}/jobs/{job_id}
          - https://boards.greenhouse.io/{board_token}/jobs/{job_id}?gh_jid=...
          - https://job-boards.greenhouse.io/{board_token}/jobs/{job_id}
          - https://app.greenhouse.io/accounts/{account}/jobs/{job_id}
            (internal format — board_token cannot be reliably determined)

        Args:
            url: Full Greenhouse job URL.

        Returns:
            Tuple of (board_token, job_id). Either may be an empty string
            if it cannot be determined from the URL.

        Example::

            token, job_id = client.extract_board_token_from_url(
                "https://boards.greenhouse.io/stripe/jobs/5987654"
            )
            # -> ("stripe", "5987654")
        """
        parsed = urllib.parse.urlparse(url)
        path = parsed.path  # e.g. /stripe/jobs/5987654

        # Pattern: /{board_token}/jobs/{job_id}
        m = re.match(r"^/([^/]+)/jobs/(\d+)/?", path)
        if m:
            return m.group(1), m.group(2)

        # Pattern: /jobs/{job_id} (board token in query string gh_src or subdomain)
        m = re.match(r"^/jobs/(\d+)/?", path)
        if m:
            job_id = m.group(1)
            # Try to infer board token from subdomain
            host_parts = parsed.hostname.split(".") if parsed.hostname else []
            if len(host_parts) > 3:
                board_token = host_parts[0]
            else:
                board_token = ""
            return board_token, job_id

        # Fallback: scan path segments for a numeric ID
        segments = [s for s in path.split("/") if s]
        board_token = ""
        job_id = ""
        for i, seg in enumerate(segments):
            if seg == "jobs" and i + 1 < len(segments):
                raw_id = segments[i + 1]
                if raw_id.isdigit():
                    job_id = raw_id
                if i > 0:
                    board_token = segments[i - 1]
                break

        return board_token, job_id
