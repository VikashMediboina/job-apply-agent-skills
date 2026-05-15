"""
Monster job search client.

Monster exposes a public JSON search API at their main search endpoint.
No authentication required for basic job listings.

Primary endpoint:
  GET https://www.monster.com/jobs/search
    ?q={query}&where={location}&sort=date&tm=7&pg={page}

Monster also has an older but functional public API:
  GET https://api.monster.com/jobs/search/?q={query}&where={location}

Usage::

    from ats_clients.monster import MonsterClient

    client = MonsterClient()
    jobs = client.search_jobs("software engineer", location="remote", limit=25)
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

SEARCH_URL = "https://www.monster.com/jobs/search"
API_V2_URL = "https://job-openings.monster.com"
RATE_LIMIT_SLEEP = 1.2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.monster.com/",
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize_job(raw: dict) -> dict:
    """Normalize a Monster job to canonical job dict."""
    job_id = str(raw.get("id", raw.get("jobId", raw.get("mstrJobId", ""))))
    loc = raw.get("location", {})
    if isinstance(loc, str):
        loc = {"display": loc}

    pay = raw.get("salary", raw.get("compensation", {}))
    if isinstance(pay, str):
        pay = {"display": pay}

    apply_url = raw.get("jobUrl", raw.get("applyUrl", raw.get("url", "")))

    return {
        "id": f"monster_{job_id}",
        "externalJobId": job_id,
        "title": raw.get("title", raw.get("jobTitle", "")),
        "jobDescription": raw.get("description", raw.get("snippet", "")),
        "jobDescriptionHTML": "",
        "salary": {
            "min": pay.get("min", None) if isinstance(pay, dict) else None,
            "max": pay.get("max", None) if isinstance(pay, dict) else None,
            "currencyCode": "USD",
            "type": "yearly",
            "isEstimated": True,
            "display": pay.get("display", "") if isinstance(pay, dict) else str(pay),
        },
        "employment": {
            "jobTypes": [raw.get("jobType", raw.get("employmentType", "Full-time"))],
            "workType": "remote"
            if "remote" in loc.get("display", "").lower()
            else "onsite",
            "experienceLevel": raw.get("experienceLevel", ""),
            "visaSponsorship": False,
        },
        "location": {
            "formatted": loc.get("display", loc.get("formatted", "")),
            "city": loc.get("city", ""),
            "state": loc.get("state", ""),
            "country": loc.get("country", "US"),
            "remote": "remote" in loc.get("display", "").lower(),
        },
        "posting": {
            "postedDate": raw.get("datePosted", raw.get("postedDate", "")),
            "expired": False,
        },
        "apply": {
            "applyUrl": apply_url,
            "easyApply": False,
            "applicationMethod": "external",
        },
        "company": {
            "name": raw.get("company", {}).get("name", raw.get("companyName", ""))
            if isinstance(raw.get("company"), dict)
            else raw.get("company", raw.get("companyName", "")),
            "industry": raw.get("industry", raw.get("occupationalCategory", "")),
            "website": raw.get("company", {}).get("url", "")
            if isinstance(raw.get("company"), dict)
            else "",
        },
        "skills": raw.get("skills", []),
        "jobSource": {
            "platform": "monster",
            "sourceName": "Monster",
            "sourceType": "job_board",
        },
        "source": "monster",
    }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class MonsterClient:
    """HTTP client for Monster.com job search.

    Scrapes Monster's public search page (no auth required).

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

    def _fetch_search_page(self, query: str, location: str, page: int) -> list[dict]:
        """Fetch and parse Monster search results page."""
        time.sleep(RATE_LIMIT_SLEEP)
        params = {
            "q": query,
            "where": location,
            "pg": page,
            "sort": "date",
            "tm": 7,  # last 7 days
        }
        try:
            resp = self._session.get(SEARCH_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()

            # Try JSON response first
            ct = resp.headers.get("content-type", "")
            if "json" in ct:
                data = resp.json()
                return [
                    _normalize_job(j)
                    for j in data.get("jobResults", data.get("jobs", []))
                ]

            # Parse HTML
            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract JSON-LD structured data
            json_lds = soup.find_all("script", type="application/ld+json")
            jobs = []
            for script in json_lds:
                try:
                    import json

                    data = json.loads(script.string or "")
                    if isinstance(data, list):
                        for item in data:
                            if item.get("@type") == "JobPosting":
                                jobs.append(_normalize_job(self._from_jsonld(item)))
                    elif isinstance(data, dict) and data.get("@type") == "JobPosting":
                        jobs.append(_normalize_job(self._from_jsonld(data)))
                except Exception:
                    continue

            if not jobs:
                # Fallback: parse visible job cards
                cards = soup.find_all(
                    ["div", "article"],
                    class_=re.compile(r"job-result|job-card|searchResult", re.I),
                )
                for card in cards:
                    try:
                        title_el = card.find(
                            ["h2", "h3", "a"], class_=re.compile(r"title", re.I)
                        )
                        company_el = card.find(
                            class_=re.compile(r"company|employer", re.I)
                        )
                        loc_el = card.find(class_=re.compile(r"location|loc\b", re.I))
                        link_el = card.find("a", href=re.compile(r"job|position", re.I))

                        title = title_el.get_text(strip=True) if title_el else ""
                        if title:
                            jobs.append(
                                _normalize_job(
                                    {
                                        "title": title,
                                        "company": company_el.get_text(strip=True)
                                        if company_el
                                        else "",
                                        "location": {
                                            "display": loc_el.get_text(strip=True)
                                            if loc_el
                                            else ""
                                        },
                                        "jobUrl": link_el["href"] if link_el else "",
                                    }
                                )
                            )
                    except Exception:
                        continue

            return jobs
        except Exception:
            return []

    @staticmethod
    def _from_jsonld(item: dict) -> dict:
        """Convert JSON-LD JobPosting to Monster normalized format."""
        loc = item.get("jobLocation", {})
        if isinstance(loc, list):
            loc = loc[0] if loc else {}
        address = loc.get("address", {})

        salary = item.get("baseSalary", {})
        salary_value = salary.get("value", {}) if isinstance(salary, dict) else {}

        return {
            "title": item.get("title", ""),
            "company": {"name": item.get("hiringOrganization", {}).get("name", "")},
            "location": {
                "display": address.get("addressLocality", "")
                + (
                    ", " + address.get("addressRegion", "")
                    if address.get("addressRegion")
                    else ""
                ),
                "city": address.get("addressLocality", ""),
                "state": address.get("addressRegion", ""),
                "country": address.get("addressCountry", "US"),
            },
            "description": item.get("description", ""),
            "datePosted": item.get("datePosted", ""),
            "jobType": item.get("employmentType", ""),
            "jobUrl": item.get("url", ""),
            "salary": {
                "min": salary_value.get("minValue"),
                "max": salary_value.get("maxValue"),
                "display": "",
            },
        }

    def search_jobs(
        self,
        query: str,
        location: str = "",
        remote: bool = False,
        limit: int = 25,
        **kwargs,
    ) -> list[dict]:
        """Search Monster.com for jobs.

        Args:
            query: Job title or keywords.
            location: Location string. Use "Remote" for remote jobs.
            remote: If True, appends "remote" to search or location.
            limit: Maximum results to return.

        Returns:
            List of normalized job dicts.
        """
        if remote and "remote" not in location.lower():
            if not location:
                location = "Remote"

        results: list[dict] = []
        page = 1

        while len(results) < limit:
            batch = self._fetch_search_page(query, location, page)
            if not batch:
                break
            results.extend(batch)
            if len(batch) < 10:
                break
            page += 1

        return results[:limit]
