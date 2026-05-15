"""
ZipRecruiter job search client.

ZipRecruiter exposes a public JSON endpoint used by their job board embed
widgets. No API key or authentication required for basic job listings.

Public endpoint:
  GET https://api.ziprecruiter.com/jobs/v1
    ?search={query}&location={location}&radius_miles=25&days_ago=7
    &jobs_per_page=20&page=1&refine_by_salary={min_salary}

Also supports the newer consumer search:
  GET https://www.ziprecruiter.com/jobs-search?search={query}&location={location}
  (JSON response when Accept: application/json)

Usage::

    from ats_clients.ziprecruiter import ZipRecruiterClient

    client = ZipRecruiterClient()
    jobs = client.search_jobs("data engineer", location="remote", limit=25)
"""

from __future__ import annotations

import time
import urllib.parse
from typing import Optional

try:
    import requests
except ImportError as e:
    raise ImportError("Install requests: pip install requests") from e


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_URL = "https://api.ziprecruiter.com/jobs/v1"
SEARCH_URL = "https://www.ziprecruiter.com/jobs-search"
RATE_LIMIT_SLEEP = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.ziprecruiter.com/",
}

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize_job(raw: dict) -> dict:
    """Normalize a ZipRecruiter job to canonical job dict."""
    job_id = str(raw.get("id", raw.get("job_id", "")))
    salary = raw.get("salary_interval", "")
    salary_min = raw.get("salary_min_annual", None) or raw.get("salary_min", None)
    salary_max = raw.get("salary_max_annual", None) or raw.get("salary_max", None)

    location_parts = raw.get("location", "")
    city = raw.get("city", "")
    state = raw.get("state", "")

    return {
        "id": f"ziprecruiter_{job_id}",
        "externalJobId": job_id,
        "title": raw.get("name", raw.get("title", "")),
        "jobDescription": raw.get("snippet", raw.get("description", "")),
        "jobDescriptionHTML": raw.get("description_html", ""),
        "salary": {
            "min": salary_min,
            "max": salary_max,
            "currencyCode": "USD",
            "type": "yearly" if "annual" in salary.lower() else salary,
            "isEstimated": raw.get("salary_estimated", False),
        },
        "employment": {
            "jobTypes": [raw.get("employment_type", "Full-time")],
            "workType": "remote" if raw.get("remote", False) else "onsite",
            "experienceLevel": "",
            "visaSponsorship": False,
        },
        "location": {
            "formatted": location_parts or f"{city}, {state}".strip(", "),
            "city": city,
            "state": state,
            "country": raw.get("country", "US"),
            "remote": raw.get("remote", False),
        },
        "posting": {
            "postedDate": raw.get("posted_time", raw.get("date_posted", "")),
            "expired": False,
        },
        "apply": {
            "applyUrl": raw.get("url", raw.get("job_url", "")),
            "easyApply": raw.get("easy_apply", False),
            "applicationMethod": "external",
        },
        "company": {
            "name": raw.get("hiring_company", {}).get(
                "name", raw.get("company_name", "")
            ),
            "industry": raw.get("category", ""),
            "website": raw.get("hiring_company", {}).get("url", ""),
        },
        "skills": [],
        "jobSource": {
            "platform": "ziprecruiter",
            "sourceName": "ZipRecruiter",
            "sourceType": "job_board",
        },
        "source": "ziprecruiter",
    }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ZipRecruiterClient:
    """HTTP client for ZipRecruiter public job search.

    Uses the ZipRecruiter public jobs API endpoint. No authentication required.

    Args:
        timeout: Request timeout in seconds.
        session: Optional requests.Session.
    """

    def __init__(
        self,
        timeout: int = 20,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update(HEADERS)

    def _get(self, url: str, params: dict) -> Optional[dict]:
        """Perform a rate-limited GET and return parsed JSON."""
        time.sleep(RATE_LIMIT_SLEEP)
        try:
            resp = self._session.get(url, params=params, timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            return None

    def search_jobs(
        self,
        query: str,
        location: str = "",
        days_ago: int = 7,
        remote: bool = False,
        limit: int = 25,
        **kwargs,
    ) -> list[dict]:
        """Search ZipRecruiter for jobs.

        Args:
            query: Job title or keywords.
            location: Location string (e.g. "Boston, MA"). Use "Remote" or
                      leave empty combined with remote=True for remote jobs.
            days_ago: Only return jobs posted within this many days.
            remote: If True, set location to "Remote" automatically.
            limit: Maximum results to return.

        Returns:
            List of normalized job dicts.
        """
        if remote and not location:
            location = "Remote"

        results: list[dict] = []
        page = 1
        per_page = min(20, limit)  # ZipRecruiter max is 20 per page

        while len(results) < limit:
            params = {
                "search": query,
                "location": location,
                "days_ago": days_ago,
                "jobs_per_page": per_page,
                "page": page,
            }

            data = self._get(API_URL, params)
            if not data:
                # Fallback to consumer search endpoint
                data = self._get(
                    SEARCH_URL,
                    {"search": query, "location": location},
                )
                if not data:
                    break

            jobs_raw = data.get("jobs", data.get("results", []))
            if not jobs_raw:
                break

            for raw in jobs_raw:
                if len(results) >= limit:
                    break
                results.append(_normalize_job(raw))

            total = data.get("total_jobs", data.get("count", 0))
            if len(results) >= total or len(results) >= limit:
                break
            page += 1

        return results[:limit]
