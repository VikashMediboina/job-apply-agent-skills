"""
SmartRecruiters ATS API client.

SmartRecruiters exposes a public REST API for job postings. No authentication
is required for reading public postings. Applications (candidate submission)
also work without auth for most company portals.

Public API base: https://api.smartrecruiters.com/v1/companies/{company_identifier}/postings
"""

import time
import re
from urllib.parse import urlparse, urlencode, parse_qs
from typing import Optional

try:
    import requests
except ImportError:
    raise ImportError("requests is required: pip install requests")


# ---------------------------------------------------------------------------
# Known SmartRecruiters company identifiers
# These are the slugs used in the API and in SmartRecruiters-hosted career pages.
# ---------------------------------------------------------------------------
KNOWN_COMPANY_IDENTIFIERS = [
    "IKEA",
    "VolkswagenGroupofAmericaInc",
    "McDonaldsCorporation",
    "Aldi",
    "BestBuy",
    "CVSHealth",
    "WalmartStores",
    "Costco",
    "Target",
    "HomeDepot",
    "Lowes",
    "Walgreens",
    "Samsung",
    "LG",
    "Philips",
    "Siemens",
    "Bosch",
    "ABB",
    "SchneiderElectric",
    "Honeywell",
    "Nestle",
    "UnileverNorthAmerica",
    "PepsiCo",
    "CocaCola",
    "Heineken",
    "Carrefour",
    "Auchan",
    "MediaMarktSaturn",
    "DeutscheTelekom",
    "Orange",
]

BASE_URL = "https://api.smartrecruiters.com/v1"

# Rate limit between API calls (seconds)
_RATE_LIMIT_SLEEP = 0.5


class SmartRecruitersClient:
    """
    Client for the SmartRecruiters public Jobs API.

    No authentication is required for reading public postings. Candidate
    submission (``submit_application``) also uses the public endpoint.

    Usage::

        client = SmartRecruitersClient()

        # Search one company
        results = client.search_jobs(query="software engineer", company_identifier="Bosch")

        # Search across known companies
        all_results = client.search_all_jobs(query="data analyst", location="New York")

        # Get job details
        job = client.get_job("Bosch", "some-posting-id")

        # Submit application
        client.submit_application("Bosch", "some-posting-id", answers={}, resume_path="/path/to/resume.pdf")
    """

    def __init__(self, rate_limit_sleep: float = _RATE_LIMIT_SLEEP):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "JobSearchBot/1.0",
            }
        )
        self.rate_limit_sleep = rate_limit_sleep

    # ------------------------------------------------------------------
    # Public search
    # ------------------------------------------------------------------

    def search_jobs(
        self,
        query: str = "",
        company_identifier: str = None,
        location: str = "",
        limit: int = 25,
        offset: int = 0,
    ) -> dict:
        """
        Search jobs for a specific company on SmartRecruiters.

        Args:
            query: Free-text search (job title, keywords, skills).
            company_identifier: SmartRecruiters company slug (required).
            location: Location string, e.g. "New York" or "Remote".
            limit: Number of results to return (max 100).
            offset: Pagination offset.

        Returns:
            Normalized dict with keys:
                ``jobs`` (list), ``totalFound`` (int), ``offset`` (int), ``limit`` (int).

        Raises:
            requests.HTTPError: On non-2xx responses.
        """
        # If no company_identifier, search across all known companies
        if not company_identifier:
            return self.search_all_jobs(
                query=query,
                location=location,
                limit=limit,
            )

        params: dict = {"limit": min(limit, 100), "offset": offset}

        if query:
            params["q"] = query

        # Parse city from location string (first part before comma)
        city, country = self._parse_location(location)
        if city:
            params["city"] = city
        if country:
            params["country"] = country

        url = f"{BASE_URL}/companies/{company_identifier}/postings"

        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                # Company not found or no public postings — return empty result
                return {
                    "jobs": [],
                    "totalFound": 0,
                    "offset": offset,
                    "limit": limit,
                    "company_identifier": company_identifier,
                    "error": f"Company '{company_identifier}' not found or has no public postings",
                }
            raise
        finally:
            time.sleep(self.rate_limit_sleep)

        raw_jobs = data.get("content", [])
        return {
            "jobs": [self._normalize_job(job, company_identifier) for job in raw_jobs],
            "totalFound": data.get("totalFound", len(raw_jobs)),
            "offset": data.get("offset", offset),
            "limit": data.get("limit", limit),
            "company_identifier": company_identifier,
        }

    def search_all_jobs(
        self,
        query: str,
        location: str = "",
        companies: Optional[list] = None,
        limit: int = 25,
    ) -> list:
        """
        Search jobs across multiple SmartRecruiters company identifiers.

        SmartRecruiters does not have a global cross-company search endpoint,
        so this method fans out requests to each company in parallel (sequential
        with rate limiting).

        Args:
            query: Free-text search string.
            location: Optional location filter.
            companies: List of company identifiers to search. Defaults to
                ``KNOWN_COMPANY_IDENTIFIERS``.
            limit: Results per company (capped at 100).

        Returns:
            Flat list of normalized job dicts from all companies.
        """
        company_list = companies if companies is not None else KNOWN_COMPANY_IDENTIFIERS
        all_jobs: list = []

        for company_id in company_list:
            try:
                result = self.search_jobs(
                    query=query,
                    company_identifier=company_id,
                    location=location,
                    limit=limit,
                )
                all_jobs.extend(result.get("jobs", []))
            except requests.HTTPError:
                # Skip companies that don't respond (private portals, 404s)
                continue
            except Exception:  # noqa: BLE001
                continue

        return all_jobs

    # ------------------------------------------------------------------
    # Job detail
    # ------------------------------------------------------------------

    def get_job(self, company_identifier: str, posting_id: str) -> dict:
        """
        Retrieve full details for a specific job posting.

        Args:
            company_identifier: SmartRecruiters company slug.
            posting_id: The posting UUID or slug.

        Returns:
            Normalized job dict with full description included.

        Raises:
            requests.HTTPError: On non-2xx responses.
        """
        url = f"{BASE_URL}/companies/{company_identifier}/postings/{posting_id}"
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
        finally:
            time.sleep(self.rate_limit_sleep)

        return self._normalize_job(data, company_identifier, full=True)

    # ------------------------------------------------------------------
    # Application form configuration
    # ------------------------------------------------------------------

    def get_application_form(self, company_identifier: str, posting_id: str) -> dict:
        """
        Retrieve the application form configuration for a posting.

        This endpoint returns the questionnaire (custom questions) that the
        candidate must answer when applying.

        Args:
            company_identifier: SmartRecruiters company slug.
            posting_id: The posting UUID or slug.

        Returns:
            Raw form configuration dict from the API. Keys typically include:
                ``postingId``, ``sections`` (list of question groups),
                ``questions`` (flat list), ``consentText``.

        Raises:
            requests.HTTPError: On non-2xx responses.
        """
        url = f"{BASE_URL}/companies/{company_identifier}/postings/{posting_id}/configuration"
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            data = response.json()
        finally:
            time.sleep(self.rate_limit_sleep)

        return data

    # ------------------------------------------------------------------
    # Application submission
    # ------------------------------------------------------------------

    def submit_application(
        self,
        company_identifier: str,
        posting_id: str,
        answers: dict,
        resume_path: str,
    ) -> dict:
        """
        Submit a candidate application for a SmartRecruiters job posting.

        The ``answers`` dict should map profile field names to values. This
        method builds the SmartRecruiters candidate body and POSTs it to the
        candidates endpoint. The resume is uploaded as a multipart file.

        Args:
            company_identifier: SmartRecruiters company slug.
            posting_id: The posting UUID or slug.
            answers: Dict of field values. Expected keys (all optional where
                marked):
                    ``firstName``, ``lastName``, ``email`` (required),
                    ``phone``, ``linkedin``, ``github``, ``city``, ``country``,
                    ``questionnaire`` (list of ``{questionId, answer}`` dicts).
            resume_path: Absolute path to the resume PDF/DOCX file.

        Returns:
            Dict with keys:
                ``success`` (bool), ``candidateId`` (str or None),
                ``message`` (str), ``status_code`` (int).

        Raises:
            FileNotFoundError: If resume_path does not exist.
            requests.HTTPError: On non-2xx responses.
        """
        import os

        if not os.path.exists(resume_path):
            raise FileNotFoundError(f"Resume not found: {resume_path}")

        # Build candidate body per SmartRecruiters API spec
        candidate_body = self._build_candidate_body(answers)

        url = f"{BASE_URL}/companies/{company_identifier}/postings/{posting_id}/candidates"

        # SmartRecruiters expects multipart when attaching a resume
        try:
            with open(resume_path, "rb") as resume_file:
                files = {
                    "candidate": (
                        None,
                        self._to_json_str(candidate_body),
                        "application/json",
                    ),
                    "resume": (
                        os.path.basename(resume_path),
                        resume_file,
                        self._mime_type(resume_path),
                    ),
                }
                # Remove Content-Type header so requests sets multipart boundary
                headers = {
                    k: v
                    for k, v in self.session.headers.items()
                    if k.lower() != "content-type"
                }
                response = self.session.post(
                    url, files=files, headers=headers, timeout=30
                )

            if response.status_code in (200, 201):
                resp_data = {}
                try:
                    resp_data = response.json()
                except Exception:  # noqa: BLE001
                    pass
                return {
                    "success": True,
                    "candidateId": resp_data.get("id"),
                    "message": "Application submitted successfully",
                    "status_code": response.status_code,
                }

            response.raise_for_status()
            return {
                "success": False,
                "candidateId": None,
                "message": f"Unexpected status: {response.status_code}",
                "status_code": response.status_code,
            }

        except requests.HTTPError as exc:
            return {
                "success": False,
                "candidateId": None,
                "message": str(exc),
                "status_code": exc.response.status_code
                if exc.response is not None
                else 0,
            }
        finally:
            time.sleep(self.rate_limit_sleep)

    # ------------------------------------------------------------------
    # URL parsing
    # ------------------------------------------------------------------

    def extract_company_and_id_from_url(self, url: str) -> tuple:
        """
        Parse a SmartRecruiters job URL to extract company identifier and
        posting ID.

        Handles these URL patterns:
        - ``https://jobs.smartrecruiters.com/CompanyName/posting-id``
        - ``https://jobs.smartrecruiters.com/CompanyName/posting-id/some-title``
        - ``https://api.smartrecruiters.com/v1/companies/CompanyName/postings/posting-id``
        - ``https://www.smartrecruiters.com/CompanyName/posting-id``

        Args:
            url: SmartRecruiters job URL.

        Returns:
            Tuple of ``(company_identifier, posting_id)``. Returns
            ``(None, None)`` if the URL cannot be parsed.
        """
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        parts = path.split("/")

        # API URL pattern: /v1/companies/{company}/postings/{id}
        if "companies" in parts and "postings" in parts:
            try:
                company_idx = parts.index("companies") + 1
                posting_idx = parts.index("postings") + 1
                return parts[company_idx], parts[posting_idx]
            except (IndexError, ValueError):
                pass

        # jobs.smartrecruiters.com/{Company}/{posting-id}[/{slug}]
        # www.smartrecruiters.com/{Company}/{posting-id}[/{slug}]
        if len(parts) >= 2:
            return parts[0], parts[1]

        return None, None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_job(
        self, raw: dict, company_identifier: str, full: bool = False
    ) -> dict:
        """
        Convert a raw SmartRecruiters posting dict into the normalized format
        used across all ATS clients.

        Normalized keys: title, company, location, url, job_id,
        company_identifier, description, department, source.
        """
        # Location assembly
        location_data = raw.get("location", {})
        city = location_data.get("city", "")
        country = location_data.get("country", "")
        remote = location_data.get("remote", False)
        if remote:
            location_str = "Remote"
        else:
            location_str = ", ".join(filter(None, [city, country]))

        # Build apply URL — prefer applyUrl, then construct the canonical
        # jobs.smartrecruiters.com URL (the ref field points to the API, not the
        # candidate-facing apply page).
        posting_id = raw.get("id", "")
        apply_url = (
            raw.get("applyUrl")
            or f"https://jobs.smartrecruiters.com/{company_identifier}/{posting_id}"
        )

        # Department / function
        department = ""
        dept_data = raw.get("department")
        if isinstance(dept_data, dict):
            department = dept_data.get("label", "")
        elif isinstance(dept_data, str):
            department = dept_data

        function_data = raw.get("function")
        if not department and isinstance(function_data, dict):
            department = function_data.get("label", "")

        normalized = {
            "title": raw.get("name", ""),
            "company": raw.get("company", {}).get("name", company_identifier)
            if isinstance(raw.get("company"), dict)
            else company_identifier,
            "location": location_str,
            "url": apply_url,
            "job_id": posting_id,
            "company_identifier": company_identifier,
            "department": department,
            "source": "smartrecruiters",
            "employment_type": self._extract_employment_type(raw),
            "posted_date": raw.get("releasedDate", raw.get("createdOn", "")),
            "experience_level": self._extract_experience_level(raw),
        }

        if full:
            normalized["description"] = (
                raw.get("jobAd", {})
                .get("sections", {})
                .get("jobDescription", {})
                .get("text", "")
            )
        else:
            normalized["description"] = ""

        return normalized

    def _extract_employment_type(self, raw: dict) -> str:
        type_of_employment = raw.get("typeOfEmployment")
        if isinstance(type_of_employment, dict):
            return type_of_employment.get("label", "")
        return ""

    def _extract_experience_level(self, raw: dict) -> str:
        exp_level = raw.get("experienceLevel")
        if isinstance(exp_level, dict):
            return exp_level.get("label", "")
        return ""

    def _parse_location(self, location: str) -> tuple:
        """
        Split a location string like "New York, US" into (city, country).
        Returns ("", "") if location is empty or "remote".
        """
        if not location or location.lower() in ("remote", "anywhere", ""):
            return "", ""
        parts = [p.strip() for p in location.split(",")]
        city = parts[0] if parts else ""
        country = parts[1].upper() if len(parts) > 1 else ""
        return city, country

    def _build_candidate_body(self, answers: dict) -> dict:
        """
        Build the SmartRecruiters candidate JSON body from a flat answers dict.

        Expected input keys (all optional unless noted):
            firstName, lastName, email (required), phone, linkedin, github,
            website, city, country, questionnaire (list of {questionId, answer}).
        """
        # Split name if only 'name' is provided
        first = answers.get("firstName", "")
        last = answers.get("lastName", "")
        if not first and not last and answers.get("name"):
            name_parts = answers["name"].strip().rsplit(" ", 1)
            first = name_parts[0]
            last = name_parts[1] if len(name_parts) > 1 else ""

        web_info = (
            answers.get("linkedin")
            or answers.get("github")
            or answers.get("website")
            or ""
        )

        body: dict = {
            "firstName": first,
            "lastName": last,
            "email": answers.get("email", ""),
            "phoneNumber": answers.get("phone", ""),
            "location": {
                "country": (answers.get("country", "us") or "us").lower(),
            },
        }

        if answers.get("city"):
            body["location"]["city"] = answers["city"]

        if web_info:
            body["web"] = {"info": web_info}

        # Questionnaire answers
        questionnaire = answers.get("questionnaire", [])
        if questionnaire:
            body["questionnaire"] = questionnaire

        # Experience / education placeholders (SmartRecruiters accepts empty lists)
        body.setdefault("experience", [])
        body.setdefault("education", [])

        return body

    @staticmethod
    def _to_json_str(data: dict) -> str:
        import json

        return json.dumps(data)

    @staticmethod
    def _mime_type(path: str) -> str:
        lower = path.lower()
        if lower.endswith(".pdf"):
            return "application/pdf"
        if lower.endswith(".docx"):
            return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if lower.endswith(".doc"):
            return "application/msword"
        return "application/octet-stream"
