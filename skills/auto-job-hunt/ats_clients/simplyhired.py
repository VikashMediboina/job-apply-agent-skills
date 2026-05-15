"""
SimplyHired job search client.

SimplyHired provides a public JSON search API used by their web app.
No authentication required for basic job listings.

Primary endpoint:
  GET https://www.simplyhired.com/api/job-list
    ?q={query}&l={location}&t={job_type}&pn={page}&sb=date

Usage::

    from ats_clients.simplyhired import SimplyHiredClient

    client = SimplyHiredClient()
    jobs = client.search_jobs("backend engineer", location="remote", limit=25)
"""

from __future__ import annotations

import re
import time
from typing import Optional

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    raise ImportError(
        "Install required packages: pip install requests beautifulsoup4"
    ) from e


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEARCH_URL = "https://www.simplyhired.com/search"
API_URL = "https://www.simplyhired.com/api/job-list"
JOB_BASE_URL = "https://www.simplyhired.com"
RATE_LIMIT_SLEEP = 1.0

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.simplyhired.com/",
}

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize_job(raw: dict) -> dict:
    """Normalize a SimplyHired job to canonical job dict."""
    job_id = str(raw.get("id", raw.get("jobId", "")))
    comp = raw.get("company", {})
    if isinstance(comp, str):
        comp = {"name": comp}

    loc = raw.get("location", {})
    if isinstance(loc, str):
        loc = {"display": loc}

    pay = raw.get("compensation", raw.get("salary", {}))
    if isinstance(pay, str):
        pay = {"display": pay}

    apply_url = raw.get("url", raw.get("jobUrl", raw.get("applyUrl", "")))
    if apply_url and not apply_url.startswith("http"):
        apply_url = JOB_BASE_URL + apply_url

    return {
        "id": f"simplyhired_{job_id}",
        "externalJobId": job_id,
        "title": raw.get("title", raw.get("jobTitle", "")),
        "jobDescription": raw.get("description", raw.get("snippet", "")),
        "jobDescriptionHTML": "",
        "salary": {
            "min": pay.get("min", None),
            "max": pay.get("max", None),
            "currencyCode": "USD",
            "type": pay.get("period", "yearly"),
            "isEstimated": pay.get("estimated", True),
            "display": pay.get("display", ""),
        },
        "employment": {
            "jobTypes": [raw.get("jobType", "Full-time")],
            "workType": "remote"
            if "remote" in loc.get("display", "").lower()
            else "onsite",
            "experienceLevel": "",
            "visaSponsorship": False,
        },
        "location": {
            "formatted": loc.get("display", ""),
            "city": loc.get("city", ""),
            "state": loc.get("state", ""),
            "country": loc.get("country", "US"),
            "remote": "remote" in loc.get("display", "").lower(),
        },
        "posting": {
            "postedDate": raw.get("datePosted", raw.get("date", "")),
            "expired": False,
        },
        "apply": {
            "applyUrl": apply_url,
            "easyApply": False,
            "applicationMethod": "external",
        },
        "company": {
            "name": comp.get("name", ""),
            "industry": raw.get("industry", ""),
            "website": comp.get("url", ""),
        },
        "skills": [],
        "jobSource": {
            "platform": "simplyhired",
            "sourceName": "SimplyHired",
            "sourceType": "job_board",
        },
        "source": "simplyhired",
    }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class SimplyHiredClient:
    """HTTP client for SimplyHired public job search.

    Uses the SimplyHired internal API endpoint (no auth required).

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

    def _search_api(self, params: dict) -> Optional[dict]:
        """Try the JSON API endpoint first."""
        time.sleep(RATE_LIMIT_SLEEP)
        try:
            resp = self._session.get(API_URL, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    return resp.json()
        except Exception:
            pass
        return None

    def _search_html(self, query: str, location: str, page: int) -> list[dict]:
        """Fallback: scrape HTML search results."""
        time.sleep(RATE_LIMIT_SLEEP)
        params = {"q": query, "l": location, "pn": page, "sb": "date"}
        try:
            resp = self._session.get(SEARCH_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            jobs = []
            cards = soup.find_all("article", class_=re.compile(r"SerpJob", re.I))
            for card in cards:
                try:
                    title_el = card.find(
                        ["h2", "h3"], class_=re.compile(r"jobposting-title|title", re.I)
                    )
                    company_el = card.find(
                        "span", class_=re.compile(r"company|employer", re.I)
                    )
                    loc_el = card.find(
                        "span", class_=re.compile(r"location|locality", re.I)
                    )
                    link_el = card.find("a", href=True)

                    title = title_el.get_text(strip=True) if title_el else ""
                    if title:
                        apply_url = link_el["href"] if link_el else ""
                        if apply_url and not apply_url.startswith("http"):
                            apply_url = JOB_BASE_URL + apply_url
                        jobs.append(
                            _normalize_job(
                                {
                                    "title": title,
                                    "company": {
                                        "name": company_el.get_text(strip=True)
                                        if company_el
                                        else ""
                                    },
                                    "location": {
                                        "display": loc_el.get_text(strip=True)
                                        if loc_el
                                        else ""
                                    },
                                    "url": apply_url,
                                }
                            )
                        )
                except Exception:
                    continue
            return jobs
        except Exception:
            return []

    def search_jobs(
        self,
        query: str,
        location: str = "",
        remote: bool = False,
        job_type: str = "",
        limit: int = 25,
        **kwargs,
    ) -> list[dict]:
        """Search SimplyHired for jobs.

        Args:
            query: Job title or keywords.
            location: Location string. Use "Remote" for remote jobs.
            remote: If True, appends "remote" to location.
            job_type: e.g. "full-time", "part-time", "contract".
            limit: Maximum results to return.

        Returns:
            List of normalized job dicts.
        """
        if remote and "remote" not in location.lower():
            location = "Remote" if not location else f"Remote {location}"

        results: list[dict] = []
        page = 1

        while len(results) < limit:
            params = {
                "q": query,
                "l": location,
                "pn": page,
                "sb": "date",
            }
            if job_type:
                params["t"] = job_type

            data = self._search_api(params)
            if data and "jobs" in data:
                batch = [_normalize_job(j) for j in data.get("jobs", [])]
            else:
                batch = self._search_html(query, location, page)

            if not batch:
                break

            results.extend(batch)
            if len(batch) < 20:
                break
            page += 1

        return results[:limit]
