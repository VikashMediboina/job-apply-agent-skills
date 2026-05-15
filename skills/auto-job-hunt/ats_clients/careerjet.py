"""
CareerJet job search client.

CareerJet provides a free public XML/JSON API for job search.
No API key required for basic access; optional affiliate ID increases limits.

API Documentation: https://www.careerjet.com/partners/api/

Endpoint:
  GET http://public.api.careerjet.net/search
    ?keywords={query}&location={location}&affid={affid}&user_ip=1.2.3.4
    &url=https://www.example.com&sort=date&pagesize={n}&page={p}

The API returns JSON with job listings.

Usage::

    from ats_clients.careerjet import CareerJetClient

    client = CareerJetClient()
    jobs = client.search_jobs("data scientist", location="New York", limit=25)
"""

from __future__ import annotations

import time
from typing import Optional

try:
    import requests
except ImportError as e:
    raise ImportError("Install requests: pip install requests") from e


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_URL = "http://public.api.careerjet.net/search"
RATE_LIMIT_SLEEP = 0.5

# Required by CareerJet API — use a generic placeholder
DEFAULT_USER_IP = "1.2.3.4"
DEFAULT_URL = "https://www.careerjet.com"

HEADERS = {
    "User-Agent": "job-hunt-automation/1.0",
    "Accept": "application/json",
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize_job(raw: dict) -> dict:
    """Normalize a CareerJet API job to canonical format."""
    job_id = str(raw.get("id", raw.get("url", "")[-20:]))

    return {
        "id": f"careerjet_{job_id}",
        "externalJobId": job_id,
        "title": raw.get("title", ""),
        "jobDescription": raw.get("description", raw.get("locations", "")),
        "jobDescriptionHTML": "",
        "salary": {
            "min": None,
            "max": None,
            "currencyCode": "USD",
            "type": "yearly",
            "isEstimated": False,
            "display": raw.get("salary", ""),
        },
        "employment": {
            "jobTypes": ["Full-time"],
            "workType": "remote"
            if "remote" in raw.get("locations", "").lower()
            else "onsite",
            "experienceLevel": "",
            "visaSponsorship": False,
        },
        "location": {
            "formatted": raw.get("locations", ""),
            "city": "",
            "state": "",
            "country": "US",
            "remote": "remote" in raw.get("locations", "").lower(),
        },
        "posting": {
            "postedDate": raw.get("date", ""),
            "expired": False,
        },
        "apply": {
            "applyUrl": raw.get("url", ""),
            "easyApply": False,
            "applicationMethod": "external",
        },
        "company": {
            "name": raw.get("company", ""),
            "industry": "",
            "website": "",
        },
        "skills": [],
        "jobSource": {
            "platform": "careerjet",
            "sourceName": "CareerJet",
            "sourceType": "job_board",
        },
        "source": "careerjet",
    }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class CareerJetClient:
    """Client for CareerJet public jobs API.

    Uses the free CareerJet Partner API (no auth key required).

    Args:
        affid: Optional affiliate ID (increases rate limits).
        timeout: Request timeout in seconds.
        session: Optional requests.Session.
    """

    def __init__(
        self,
        affid: str = "0",
        timeout: int = 20,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.affid = affid
        self.timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update(HEADERS)

    def search_jobs(
        self,
        query: str,
        location: str = "",
        remote: bool = False,
        limit: int = 25,
        **kwargs,
    ) -> list[dict]:
        """Search CareerJet for jobs.

        Args:
            query: Job title or keywords.
            location: Location string (e.g. "New York, NY").
            remote: If True, append "remote" to query.
            limit: Maximum results to return.

        Returns:
            List of normalized job dicts.
        """
        if remote and "remote" not in query.lower():
            query = f"{query} remote"

        results: list[dict] = []
        page = 1
        page_size = min(20, limit)  # CareerJet max pagesize

        while len(results) < limit:
            params = {
                "keywords": query,
                "location": location,
                "affid": self.affid,
                "user_ip": DEFAULT_USER_IP,
                "url": DEFAULT_URL,
                "sort": "date",
                "pagesize": page_size,
                "page": page,
            }

            time.sleep(RATE_LIMIT_SLEEP)
            try:
                resp = self._session.get(API_URL, params=params, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                break

            if data.get("type") != "JOBS":
                break

            jobs_raw = data.get("jobs", [])
            if not jobs_raw:
                break

            for raw in jobs_raw:
                if len(results) >= limit:
                    break
                results.append(_normalize_job(raw))

            total = data.get("hits", 0)
            if len(results) >= total or len(results) >= limit:
                break
            page += 1

        return results[:limit]
