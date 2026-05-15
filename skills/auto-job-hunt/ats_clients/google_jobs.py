"""
Google Jobs search client.

Google for Jobs aggregates job listings from all over the web and can be
accessed via:

1. SerpAPI (requires API key) — most reliable
2. Jooble API (free tier available) — aggregates from Google Jobs
3. Direct Google Jobs URL parsing via requests/BeautifulSoup

This client uses a tiered approach:
  - If SERPAPI_KEY env var is set → use SerpAPI Google Jobs endpoint
  - Otherwise → scrape the Google Jobs JSON embedded in search results

API Docs:
  SerpAPI: https://serpapi.com/google-jobs-api
  Endpoint: https://serpapi.com/search.json?engine=google_jobs&q={query}&location={location}

Alternative (no key):
  Google Jobs embed: https://www.google.com/search?q={query}+jobs&ibp=htl;jobs
  Returns JSON-LD structured data in the HTML.

Usage::

    from ats_clients.google_jobs import GoogleJobsClient
    import os

    # With SerpAPI key (optional)
    os.environ["SERPAPI_KEY"] = "your_key_here"

    client = GoogleJobsClient()
    jobs = client.search_jobs("machine learning engineer", location="remote", limit=25)
"""

from __future__ import annotations

import json
import os
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

SERPAPI_URL = "https://serpapi.com/search.json"
GOOGLE_JOBS_URL = "https://www.google.com/search"
RATE_LIMIT_SLEEP = 1.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.google.com/",
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize_serpapi_job(raw: dict) -> dict:
    """Normalize a SerpAPI Google Jobs result to canonical format."""
    job_id = raw.get("job_id", raw.get("id", ""))
    highlights = raw.get("job_highlights", [])

    extensions = raw.get("detected_extensions", {})
    salary_str = extensions.get("salary", "")
    is_remote = extensions.get("work_from_home", False)

    apply_options = raw.get("apply_options", [])
    apply_url = (
        apply_options[0].get("link", "") if apply_options else raw.get("share_link", "")
    )

    return {
        "id": f"google_jobs_{job_id}",
        "externalJobId": job_id,
        "title": raw.get("title", ""),
        "jobDescription": raw.get("description", ""),
        "jobDescriptionHTML": "",
        "salary": {
            "min": None,
            "max": None,
            "currencyCode": "USD",
            "type": "yearly",
            "isEstimated": False,
            "display": salary_str,
        },
        "employment": {
            "jobTypes": extensions.get("schedule_type", ["Full-time"])
            if isinstance(extensions.get("schedule_type"), list)
            else [extensions.get("schedule_type", "Full-time")],
            "workType": "remote" if is_remote else "onsite",
            "experienceLevel": "",
            "visaSponsorship": False,
        },
        "location": {
            "formatted": raw.get("location", ""),
            "city": "",
            "state": "",
            "country": "US",
            "remote": is_remote or "remote" in raw.get("location", "").lower(),
        },
        "posting": {
            "postedDate": raw.get("detected_extensions", {}).get("posted_at", ""),
            "expired": False,
        },
        "apply": {
            "applyUrl": apply_url,
            "easyApply": False,
            "applicationMethod": "external",
        },
        "company": {
            "name": raw.get("company_name", ""),
            "industry": raw.get("company_type", ""),
            "website": raw.get("thumbnail", ""),
        },
        "skills": [],
        "jobSource": {
            "platform": "google_jobs",
            "sourceName": "Google Jobs",
            "sourceType": "job_aggregator",
        },
        "source": "google_jobs",
    }


def _normalize_jsonld_job(raw: dict, source_url: str = "") -> dict:
    """Normalize a JSON-LD JobPosting to canonical format."""
    loc = raw.get("jobLocation", [{}])
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    address = loc.get("address", {})
    if isinstance(address, str):
        address = {"addressLocality": address}

    salary = raw.get("baseSalary", {})
    salary_value = salary.get("value", {}) if isinstance(salary, dict) else {}

    hiring_org = raw.get("hiringOrganization", {})

    return {
        "id": f"google_jobs_{hash(raw.get('url', raw.get('title', '')))}",
        "externalJobId": "",
        "title": raw.get("title", ""),
        "jobDescription": raw.get("description", ""),
        "jobDescriptionHTML": "",
        "salary": {
            "min": salary_value.get("minValue"),
            "max": salary_value.get("maxValue"),
            "currencyCode": salary.get("currency", "USD")
            if isinstance(salary, dict)
            else "USD",
            "type": "yearly",
            "isEstimated": False,
        },
        "employment": {
            "jobTypes": raw.get("employmentType", "Full-time")
            if isinstance(raw.get("employmentType"), list)
            else [raw.get("employmentType", "Full-time")],
            "workType": "remote"
            if raw.get("jobLocationType") == "TELECOMMUTE"
            else "onsite",
            "experienceLevel": "",
            "visaSponsorship": False,
        },
        "location": {
            "formatted": address.get("addressLocality", "")
            + (
                ", " + address.get("addressRegion", "")
                if address.get("addressRegion")
                else ""
            ),
            "city": address.get("addressLocality", ""),
            "state": address.get("addressRegion", ""),
            "country": address.get("addressCountry", "US"),
            "remote": raw.get("jobLocationType") == "TELECOMMUTE",
        },
        "posting": {
            "postedDate": raw.get("datePosted", ""),
            "expired": False,
        },
        "apply": {
            "applyUrl": raw.get("url", source_url),
            "easyApply": False,
            "applicationMethod": "external",
        },
        "company": {
            "name": hiring_org.get("name", "") if isinstance(hiring_org, dict) else "",
            "industry": "",
            "website": hiring_org.get("sameAs", "")
            if isinstance(hiring_org, dict)
            else "",
        },
        "skills": [],
        "jobSource": {
            "platform": "google_jobs",
            "sourceName": "Google Jobs",
            "sourceType": "job_aggregator",
        },
        "source": "google_jobs",
    }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GoogleJobsClient:
    """Client for Google Jobs search.

    Uses SerpAPI if SERPAPI_KEY env var is set, otherwise falls back to
    parsing JSON-LD structured data from Google search results.

    Args:
        serpapi_key: SerpAPI key (overrides SERPAPI_KEY env var).
        timeout: Request timeout in seconds.
        session: Optional requests.Session.
    """

    def __init__(
        self,
        serpapi_key: Optional[str] = None,
        timeout: int = 25,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.serpapi_key = serpapi_key or os.environ.get("SERPAPI_KEY", "")
        self.timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update(HEADERS)

    def _serpapi_search(self, query: str, location: str, start: int = 0) -> list[dict]:
        """Search via SerpAPI Google Jobs endpoint."""
        if not self.serpapi_key:
            return []
        time.sleep(RATE_LIMIT_SLEEP)
        params = {
            "engine": "google_jobs",
            "q": query,
            "api_key": self.serpapi_key,
            "start": start,
        }
        if location:
            params["location"] = location
        try:
            resp = self._session.get(SERPAPI_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return [_normalize_serpapi_job(j) for j in data.get("jobs_results", [])]
        except Exception:
            return []

    def _google_search_scrape(self, query: str, location: str) -> list[dict]:
        """Fallback: parse Google Jobs results from search page JSON-LD."""
        time.sleep(RATE_LIMIT_SLEEP)
        search_query = f"{query} jobs"
        if location:
            search_query += f" {location}"
        params = {
            "q": search_query,
            "ibp": "htl;jobs",
            "hl": "en",
            "gl": "us",
        }
        try:
            resp = self._session.get(
                GOOGLE_JOBS_URL, params=params, timeout=self.timeout
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            jobs = []
            # Parse JSON-LD job postings
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                    if isinstance(data, list):
                        for item in data:
                            if item.get("@type") == "JobPosting":
                                jobs.append(_normalize_jsonld_job(item, resp.url))
                    elif isinstance(data, dict) and data.get("@type") == "JobPosting":
                        jobs.append(_normalize_jsonld_job(data, resp.url))
                except Exception:
                    continue

            # Also try parsing embedded JSON data from page scripts
            if not jobs:
                for script in soup.find_all("script"):
                    try:
                        text = script.string or ""
                        if "JobPosting" in text or "jobTitle" in text:
                            # Find JSON objects in script
                            matches = re.findall(r'\{[^{}]*"title"[^{}]*\}', text)
                            for match in matches[:10]:
                                try:
                                    obj = json.loads(match)
                                    if obj.get("title"):
                                        jobs.append(_normalize_jsonld_job(obj))
                                except Exception:
                                    continue
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
        limit: int = 25,
        **kwargs,
    ) -> list[dict]:
        """Search Google Jobs for listings.

        Args:
            query: Job title or keywords.
            location: Location string.
            remote: If True, append "remote" to query.
            limit: Maximum results to return.

        Returns:
            List of normalized job dicts.
        """
        if remote and "remote" not in query.lower():
            query = f"{query} remote"

        results: list[dict] = []

        if self.serpapi_key:
            # Use SerpAPI with pagination
            start = 0
            while len(results) < limit:
                batch = self._serpapi_search(query, location, start)
                if not batch:
                    break
                results.extend(batch)
                if len(batch) < 10:
                    break
                start += 10
        else:
            # Fallback to HTML scraping
            batch = self._google_search_scrape(query, location)
            results.extend(batch)

        return results[:limit]
