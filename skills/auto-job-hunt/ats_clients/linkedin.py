"""
LinkedIn Jobs scraper client.

LinkedIn does not offer a public jobs API. This client scrapes the public
LinkedIn Jobs search page using requests + HTML parsing. For heavy usage or
JavaScript-rendered pages, the Playwright MCP is preferred.

Public search URL (no login required for basic listings):
  https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
  ?keywords={query}&location={location}&start={offset}

This endpoint returns HTML job cards that can be parsed without a browser.

Usage::

    from ats_clients.linkedin import LinkedInClient

    client = LinkedInClient()
    jobs = client.search_jobs("machine learning engineer", location="remote", limit=25)
"""

from __future__ import annotations

import re
import time
import urllib.parse
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

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
JOB_URL_BASE = "https://www.linkedin.com/jobs/view"
RATE_LIMIT_SLEEP = 1.5  # LinkedIn is sensitive to rapid requests
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.linkedin.com/jobs/",
}

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _normalize_job(card: dict, raw_html: str = "") -> dict:
    """Normalize a parsed LinkedIn job card to the canonical job dict."""
    job_id = card.get("job_id", "")
    return {
        "id": f"linkedin_{job_id}" if job_id else "",
        "externalJobId": job_id,
        "title": card.get("title", ""),
        "jobDescription": card.get("description", ""),
        "jobDescriptionHTML": raw_html,
        "salary": {
            "min": None,
            "max": None,
            "currencyCode": "USD",
            "type": "yearly",
            "isEstimated": False,
        },
        "employment": {
            "jobTypes": [card.get("job_type", "Full-time")],
            "workType": card.get("work_type", ""),
            "experienceLevel": card.get("level", ""),
            "visaSponsorship": False,
        },
        "location": {
            "formatted": card.get("location", ""),
            "city": "",
            "state": "",
            "country": "US",
            "remote": "remote" in card.get("location", "").lower(),
        },
        "posting": {
            "postedDate": card.get("posted_date", ""),
            "expired": False,
        },
        "apply": {
            "applyUrl": card.get("apply_url", ""),
            "easyApply": card.get("easy_apply", False),
            "applicationMethod": "linkedin",
        },
        "company": {
            "name": card.get("company", ""),
            "industry": "",
            "website": "",
        },
        "skills": [],
        "jobSource": {
            "platform": "linkedin",
            "sourceName": "LinkedIn",
            "sourceType": "job_board",
        },
        "source": "linkedin",
    }


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class LinkedInClient:
    """Scraper for LinkedIn Jobs public guest API.

    Uses the unauthenticated LinkedIn Jobs guest endpoint which returns HTML
    job cards. No login or API key required.

    Args:
        timeout: Request timeout in seconds.
        session: Optional requests.Session for connection reuse or mocking.
    """

    def __init__(
        self,
        timeout: int = 20,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.timeout = timeout
        self._session = session or requests.Session()
        self._session.headers.update(HEADERS)

    def _fetch_page(self, params: dict, attempt: int = 0) -> Optional[str]:
        """Fetch a page of job listings HTML."""
        time.sleep(RATE_LIMIT_SLEEP)
        try:
            resp = self._session.get(SEARCH_URL, params=params, timeout=self.timeout)
            if resp.status_code == 429:
                wait = 30 * (attempt + 1)
                time.sleep(wait)
                if attempt < MAX_RETRIES:
                    return self._fetch_page(params, attempt + 1)
                return None
            resp.raise_for_status()
            return resp.text
        except Exception:
            return None

    def _parse_cards(self, html: str) -> list[dict]:
        """Parse job cards from LinkedIn guest API HTML response."""
        jobs = []
        try:
            soup = BeautifulSoup(html, "html.parser")
            cards = soup.find_all("li")
            for card in cards:
                try:
                    # Job ID from data-entity-urn or anchor href
                    urn = card.get("data-entity-urn", "")
                    job_id = urn.split(":")[-1] if urn else ""

                    # Title
                    title_el = card.find(
                        "h3", class_=re.compile(r"base-search-card__title", re.I)
                    )
                    title = title_el.get_text(strip=True) if title_el else ""

                    # Company
                    company_el = card.find(
                        "h4", class_=re.compile(r"base-search-card__subtitle", re.I)
                    )
                    company = company_el.get_text(strip=True) if company_el else ""

                    # Location
                    loc_el = card.find(
                        "span", class_=re.compile(r"job-search-card__location", re.I)
                    )
                    location = loc_el.get_text(strip=True) if loc_el else ""

                    # Posted date
                    time_el = card.find("time")
                    posted = time_el.get("datetime", "") if time_el else ""

                    # Apply URL
                    link_el = card.find(
                        "a", class_=re.compile(r"base-card__full-link", re.I)
                    )
                    apply_url = link_el.get("href", "") if link_el else ""
                    if not job_id and apply_url:
                        match = re.search(r"/view/[^/]+-(\d+)", apply_url)
                        if match:
                            job_id = match.group(1)

                    # Easy apply indicator
                    easy_apply = bool(card.find(class_=re.compile(r"easy-apply", re.I)))

                    if title:
                        jobs.append(
                            _normalize_job(
                                {
                                    "job_id": job_id,
                                    "title": title,
                                    "company": company,
                                    "location": location,
                                    "posted_date": posted,
                                    "apply_url": apply_url,
                                    "easy_apply": easy_apply,
                                }
                            )
                        )
                except Exception:
                    continue
        except Exception:
            pass
        return jobs

    def search_jobs(
        self,
        query: str,
        location: str = "",
        remote: bool = False,
        job_type: str = "",
        limit: int = 25,
        **kwargs,
    ) -> list[dict]:
        """Search LinkedIn Jobs for matching postings.

        Args:
            query: Job title or keywords.
            location: Location string (e.g. "Boston, MA" or "United States").
            remote: If True, filter for remote jobs only.
            job_type: One of "F" (fulltime), "P" (parttime), "C" (contract),
                      "T" (temporary), "I" (internship).
            limit: Maximum results to return.

        Returns:
            List of normalized job dicts.
        """
        results: list[dict] = []
        page_size = 25
        offset = 0

        f_WT = "2" if remote else ""  # LinkedIn remote filter code

        while len(results) < limit:
            params: dict = {
                "keywords": query,
                "start": offset,
                "count": page_size,
            }
            if location:
                params["location"] = location
            if f_WT:
                params["f_WT"] = f_WT
            if job_type:
                params["f_JT"] = job_type

            html = self._fetch_page(params)
            if not html:
                break

            batch = self._parse_cards(html)
            if not batch:
                break

            results.extend(batch)
            offset += page_size

            # LinkedIn guest API typically caps at 1000 results
            if len(batch) < page_size:
                break

        return results[:limit]
