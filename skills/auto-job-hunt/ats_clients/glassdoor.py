"""
Glassdoor job search client.

Glassdoor provides job listings via their public search interface. This client
uses the Glassdoor GDAPI (no auth for basic job listings) as well as HTML
fallback scraping.

Primary endpoints:
  GET https://www.glassdoor.com/graph (GraphQL)
  GET https://www.glassdoor.com/Job/jobs.htm?sc.keyword={query}&locT=C&locId=1&jobType=all

For the GraphQL endpoint, a minimal payload fetches job listings without
requiring authentication.

Usage::

    from ats_clients.glassdoor import GlassdoorClient

    client = GlassdoorClient()
    jobs = client.search_jobs("product manager", location="San Francisco, CA", limit=25)
"""

from __future__ import annotations

import re
import json
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

SEARCH_URL = "https://www.glassdoor.com/Job/jobs.htm"
GRAPHQL_URL = "https://www.glassdoor.com/graph"
RATE_LIMIT_SLEEP = 2.0  # Glassdoor is aggressive with bot detection

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.glassdoor.com/",
}

GRAPHQL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Content-Type": "application/json",
    "gd-csrf-token": "fetch",
    "Referer": "https://www.glassdoor.com/Job/jobs.htm",
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize_job(raw: dict) -> dict:
    """Normalize a Glassdoor job dict to canonical format."""
    job_id = str(raw.get("jobListingId", raw.get("id", "")))

    salary = raw.get("salary", raw.get("payPeriodAdjustedPay", {}))
    if isinstance(salary, (int, float)):
        salary = {}

    loc = raw.get("location", raw.get("locationName", ""))
    if isinstance(loc, dict):
        loc_display = loc.get("cityName", "") + (
            ", " + loc.get("stateName", "") if loc.get("stateName") else ""
        )
    else:
        loc_display = str(loc)

    apply_url = raw.get("jobViewUrl", raw.get("applyUrl", raw.get("url", "")))
    if apply_url and not apply_url.startswith("http"):
        apply_url = "https://www.glassdoor.com" + apply_url

    employer = raw.get("employer", raw.get("company", {}))
    if isinstance(employer, str):
        employer = {"name": employer}

    return {
        "id": f"glassdoor_{job_id}",
        "externalJobId": job_id,
        "title": raw.get("jobTitleText", raw.get("title", "")),
        "jobDescription": raw.get("jobDescription", raw.get("description", "")),
        "jobDescriptionHTML": "",
        "salary": {
            "min": salary.get("p10", None) if isinstance(salary, dict) else None,
            "max": salary.get("p90", None) if isinstance(salary, dict) else None,
            "currencyCode": salary.get("currencyCode", "USD")
            if isinstance(salary, dict)
            else "USD",
            "type": "yearly",
            "isEstimated": True,
        },
        "employment": {
            "jobTypes": [raw.get("employmentType", "Full-time")],
            "workType": "remote" if raw.get("isRemote", False) else "onsite",
            "experienceLevel": "",
            "visaSponsorship": False,
        },
        "location": {
            "formatted": loc_display,
            "city": loc.get("cityName", "") if isinstance(loc, dict) else "",
            "state": loc.get("stateName", "") if isinstance(loc, dict) else "",
            "country": loc.get("countryCode", "US") if isinstance(loc, dict) else "US",
            "remote": raw.get("isRemote", False) or "remote" in loc_display.lower(),
        },
        "posting": {
            "postedDate": raw.get("listedAt", raw.get("discoveredDate", "")),
            "expired": False,
        },
        "apply": {
            "applyUrl": apply_url,
            "easyApply": raw.get("easyApply", False),
            "applicationMethod": "external",
        },
        "company": {
            "name": employer.get("name", employer.get("shortName", ""))
            if isinstance(employer, dict)
            else str(employer),
            "industry": employer.get("industryName", "")
            if isinstance(employer, dict)
            else "",
            "website": employer.get("website", "")
            if isinstance(employer, dict)
            else "",
            "rating": employer.get("ratings", {}).get("overallRating")
            if isinstance(employer, dict)
            else None,
        },
        "skills": [],
        "jobSource": {
            "platform": "glassdoor",
            "sourceName": "Glassdoor",
            "sourceType": "job_board",
        },
        "source": "glassdoor",
    }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GlassdoorClient:
    """Client for Glassdoor job search.

    Uses Glassdoor's GraphQL API and HTML fallback. Rate limits enforced.

    Args:
        timeout: Request timeout in seconds.
        session: Optional requests.Session.
    """

    def __init__(
        self,
        timeout: int = 25,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update(HEADERS)

    def _get_csrf_token(self) -> Optional[str]:
        """Fetch homepage to get CSRF token for GraphQL calls."""
        try:
            resp = self._session.get("https://www.glassdoor.com", timeout=self.timeout)
            # Extract CSRF from cookie
            csrf = self._session.cookies.get("gdId", "")
            if not csrf:
                # Try extracting from page
                match = re.search(r'"token"\s*:\s*"([^"]+)"', resp.text)
                csrf = match.group(1) if match else "fetch"
            return csrf
        except Exception:
            return "fetch"

    def _graphql_search(self, query: str, location: str, page: int = 0) -> list[dict]:
        """Search via Glassdoor GraphQL endpoint."""
        try:
            csrf = self._get_csrf_token()
            headers = {**GRAPHQL_HEADERS, "gd-csrf-token": csrf or "fetch"}
            payload = {
                "operationName": "JobSearchResultsQuery",
                "variables": {
                    "keyword": query,
                    "locationId": 1,
                    "locationTypeId": 1,
                    "numJobsToShow": 30,
                    "pageCursor": None if page == 0 else str(page * 30),
                    "filterParams": [],
                },
                "query": """
                    query JobSearchResultsQuery(
                        $keyword: String, $locationId: Int, $numJobsToShow: Int,
                        $pageCursor: String, $filterParams: [FilterParams]
                    ) {
                        jobListings(
                            contextHolder: {
                                searchParams: {
                                    keyword: $keyword,
                                    locationId: $locationId,
                                    numPerPage: $numJobsToShow,
                                    pageCursor: $pageCursor,
                                    filterParams: $filterParams
                                }
                            }
                        ) {
                            jobListingSeoLinks { linkItems { position url } }
                            jobListings {
                                jobListingId
                                jobTitleText
                                locationName
                                jobViewUrl
                                isRemote
                                listedAt
                                employer {
                                    name shortName industryName
                                    ratings { overallRating }
                                }
                                description
                                employmentType
                                payPeriodAdjustedPay { p10 p90 currencyCode }
                            }
                        }
                    }
                """,
            }
            time.sleep(RATE_LIMIT_SLEEP)
            resp = self._session.post(
                GRAPHQL_URL,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                listings = (
                    data.get("data", {}).get("jobListings", {}).get("jobListings", [])
                )
                return [_normalize_job(j) for j in listings]
        except Exception:
            pass
        return []

    def _html_search(self, query: str, location: str) -> list[dict]:
        """Fallback: parse Glassdoor HTML search results."""
        time.sleep(RATE_LIMIT_SLEEP)
        params = {"sc.keyword": query, "locT": "C", "locId": 1, "jobType": "all"}
        if location:
            params["sc.keyword"] = f"{query} {location}"
        try:
            resp = self._session.get(SEARCH_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "html.parser")
            # Extract structured job data from page scripts
            scripts = soup.find_all("script", type="application/ld+json")
            jobs = []
            for script in scripts:
                try:
                    data = json.loads(script.string or "")
                    if isinstance(data, dict) and data.get("@type") == "JobPosting":
                        jobs.append(
                            _normalize_job(
                                {
                                    "jobTitleText": data.get("title", ""),
                                    "description": data.get("description", ""),
                                    "employer": {
                                        "name": data.get("hiringOrganization", {}).get(
                                            "name", ""
                                        )
                                    },
                                    "locationName": data.get("jobLocation", [{}])[0]
                                    .get("address", {})
                                    .get("addressLocality", ""),
                                    "listedAt": data.get("datePosted", ""),
                                    "jobViewUrl": data.get("url", ""),
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
        limit: int = 25,
        **kwargs,
    ) -> list[dict]:
        """Search Glassdoor for jobs.

        Args:
            query: Job title or keywords.
            location: Location string.
            remote: If True, include remote filter.
            limit: Maximum results to return.

        Returns:
            List of normalized job dicts.
        """
        results: list[dict] = []
        page = 0

        while len(results) < limit:
            batch = self._graphql_search(query, location, page)
            if not batch:
                batch = self._html_search(query, location)
                results.extend(batch)
                break

            results.extend(batch)
            if len(batch) < 30:
                break
            page += 1

        # Filter for remote if requested
        if remote:
            results = [
                j
                for j in results
                if j["location"]["remote"]
                or "remote" in j["location"]["formatted"].lower()
            ] or results

        return results[:limit]
