"""
Ashby ATS API client.

Ashby's public job board uses a GraphQL API at:
  https://jobs.ashbyhq.com/api/non-user-graphql

No authentication required for reading public job postings.
Application submission still uses the REST posting API.

Hosted jobs page: https://jobs.ashbyhq.com/{org}/{uuid}
"""

import base64
import time
import re
from typing import Optional
from pathlib import Path

try:
    import requests
    from requests import Response
except ImportError:
    raise ImportError("requests is required: pip install requests")

# ---------------------------------------------------------------------------
# Known Ashby organisation slugs (used for broad search)
# ---------------------------------------------------------------------------
KNOWN_ASHBY_ORGS: list[str] = [
    "openai",
    "anthropic",
    "mistral",
    "cohere",
    "scale-ai",
    "huggingface",
    "replit",
    "supabase",
    "vercel",
    "railway",
    "planetscale",
    "neon",
    "turso",
    "convex",
    "lancedb",
    "weaviate",
    "qdrant",
    "chroma",
    "pinecone",
    "langchain",
    "groq",
    "together-ai",
    "perplexity",
    "cursor",
    "codeium",
    "anyscale",
    "modal",
    "replicate",
    "weights-biases",
    "dbt-labs",
]

# ---------------------------------------------------------------------------
# Ashby system field paths (used in applicationForm.fields)
# ---------------------------------------------------------------------------
SYSTEM_FIELDS = {
    "name": "_systemfield_name",
    "email": "_systemfield_email",
    "phone": "_systemfield_phone",
    "linkedin": "_systemfield_linkedin",
    "github": "_systemfield_github",
    "portfolio": "_systemfield_portfolio",
    "website": "_systemfield_website",
    "location": "_systemfield_location",
    "resume": "_systemfield_resume",
    "cover_letter": "_systemfield_coverLetter",
}

# GraphQL endpoint used by the Ashby-hosted job board frontend (no auth required)
GRAPHQL_URL = "https://jobs.ashbyhq.com/api/non-user-graphql"

# Legacy REST API base (still used for application submission)
API_BASE = "https://api.ashbyhq.com/posting-api/job-posting"

RATE_LIMIT_SLEEP = 0.5  # seconds between requests (conservative)

# GraphQL query to list all job postings for an org (brief format)
_GQL_LIST_JOBS = """
query AshbyListJobs($org: String!) {
  jobBoardWithTeams(organizationHostedJobsPageName: $org) {
    jobPostings {
      id
      title
      locationName
      workplaceType
      employmentType
      compensationTierSummary
    }
  }
  organizationFromHostedJobsPageName(organizationHostedJobsPageName: $org) {
    name
  }
}
"""

# GraphQL query to get details for a single job posting
_GQL_GET_JOB = """
query AshbyGetJob($org: String!, $jobId: String!) {
  jobPosting(organizationHostedJobsPageName: $org, jobPostingId: $jobId) {
    id
    title
    departmentName
    teamNames
    locationName
    workplaceType
    employmentType
    descriptionHtml
    publishedDate
    compensationTierSummary
    applicationForm {
      sections {
        fields {
          field {
            path
            title
            type
          }
          isRequired
        }
      }
    }
  }
  organizationFromHostedJobsPageName(organizationHostedJobsPageName: $org) {
    name
  }
}
"""


class AshbyClient:
    """
    Client for the Ashby job board GraphQL API and the posting REST API.

    Reading public job postings uses the GraphQL endpoint at
    https://jobs.ashbyhq.com/api/non-user-graphql (no authentication).

    Application submission uses the legacy REST posting API at
    https://api.ashbyhq.com/posting-api/job-posting/{id}/apply.
    """

    def __init__(self, api_key: Optional[str] = None, timeout: int = 15) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Origin": "https://jobs.ashbyhq.com",
                "Referer": "https://jobs.ashbyhq.com/",
            }
        )
        if api_key:
            self.session.headers["Authorization"] = f"Basic {api_key}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _graphql(self, query: str, variables: Optional[dict] = None) -> dict:
        """Execute a GraphQL query against the Ashby non-user endpoint."""
        time.sleep(RATE_LIMIT_SLEEP)
        payload: dict = {"query": query}
        if variables:
            payload["variables"] = variables
        resp: Response = self.session.post(
            GRAPHQL_URL, json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise RuntimeError(f"GraphQL errors: {body['errors']}")
        return body.get("data") or {}

    def _post(
        self, url: str, json_body: Optional[dict] = None, files: Optional[dict] = None
    ) -> dict:
        """Execute POST request to the legacy REST API and return parsed JSON."""
        time.sleep(RATE_LIMIT_SLEEP)
        if files:
            # Multipart — remove Content-Type so requests sets boundary correctly
            headers = {
                k: v for k, v in self.session.headers.items() if k != "Content-Type"
            }
            resp: Response = self.session.post(
                url, data=json_body, files=files, headers=headers, timeout=self.timeout
            )
        else:
            resp = self.session.post(url, json=json_body or {}, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _normalize_job(raw: dict, org_slug: str, company_name: str = "") -> dict:
        """Convert a raw Ashby job posting dict to a normalised format."""
        posting_id = raw.get("id", "")
        url = f"https://jobs.ashbyhq.com/{org_slug}/{posting_id}"

        # Location / remote
        location_parts = []
        if raw.get("locationName"):
            location_parts.append(raw["locationName"])
        workplace = raw.get("workplaceType", "")
        if workplace == "Remote" and "Remote" not in location_parts:
            location_parts.append("Remote")
        location = ", ".join(location_parts) or "Not specified"
        is_remote = workplace == "Remote"

        return {
            "title": raw.get("title", "Unknown Title"),
            "company": company_name or org_slug,
            "location": location,
            "url": url,
            "job_id": posting_id,
            "org_slug": org_slug,
            "department": raw.get("departmentName", ""),
            "description": raw.get("descriptionHtml") or raw.get("description") or "",
            "employment_type": raw.get("employmentType", ""),
            "compensation_summary": raw.get("compensationTierSummary", ""),
            "is_remote": is_remote,
            "published_at": raw.get("publishedDate") or raw.get("publishedAt", ""),
            "source": "ashby",
        }

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def list_jobs(self, organization_host_slug: str) -> list[dict]:
        """
        Retrieve all open job postings for a given Ashby-hosted org.

        Uses the GraphQL endpoint at jobs.ashbyhq.com (no auth required).

        Args:
            organization_host_slug: The org's Ashby slug, e.g. "replit"

        Returns:
            List of normalised job dicts.
        """
        try:
            data = self._graphql(_GQL_LIST_JOBS, {"org": organization_host_slug})
        except Exception:
            return []

        board = data.get("jobBoardWithTeams") or {}
        raw_jobs: list[dict] = board.get("jobPostings") or []
        org_info = data.get("organizationFromHostedJobsPageName") or {}
        company_name = org_info.get("name") or organization_host_slug

        return [
            self._normalize_job(j, organization_host_slug, company_name)
            for j in raw_jobs
        ]

    def search_jobs(
        self,
        query: str,
        location: str = "",
        orgs: Optional[list[str]] = None,
        limit: int = 25,
    ) -> list[dict]:
        """
        Search for jobs matching *query* across multiple Ashby organisations.

        Args:
            query: Keyword(s) to match against title and description.
            location: Optional location filter (case-insensitive substring match).
            orgs: List of org slugs to search. Defaults to KNOWN_ASHBY_ORGS.
            limit: Maximum number of results to return.

        Returns:
            Sorted list of matching normalised job dicts (best title matches first).
        """
        orgs = orgs or KNOWN_ASHBY_ORGS
        query_lower = query.lower()
        location_lower = location.lower()
        results: list[dict] = []

        for slug in orgs:
            if len(results) >= limit * 3:  # fetch headroom then trim
                break
            jobs = self.list_jobs(slug)
            for job in jobs:
                title_match = query_lower in job["title"].lower()
                desc_match = query_lower in job["description"].lower()
                loc_match = (
                    not location_lower or location_lower in job["location"].lower()
                )
                if (title_match or desc_match) and loc_match:
                    results.append(job)

        # Prioritise title matches
        results.sort(
            key=lambda j: (0 if query_lower in j["title"].lower() else 1, j["title"])
        )
        return results[:limit]

    def get_job(self, posting_id: str, organization_slug: str) -> dict:
        """
        Fetch a single job posting by its ID via GraphQL.

        Args:
            posting_id: UUID of the job posting.
            organization_slug: Ashby org slug (e.g. "replit").

        Returns:
            Normalised job dict.

        Raises:
            RuntimeError: If the posting is not found or unavailable.
        """
        data = self._graphql(
            _GQL_GET_JOB, {"org": organization_slug, "jobId": posting_id}
        )
        raw = data.get("jobPosting")
        if not raw:
            raise RuntimeError(
                f"Job posting {posting_id} not found for org {organization_slug}"
            )
        org_info = data.get("organizationFromHostedJobsPageName") or {}
        company_name = org_info.get("name") or organization_slug
        return self._normalize_job(raw, organization_slug, company_name)

    def get_application_form(self, posting_id: str, organization_slug: str) -> dict:
        """
        Fetch the application form schema for a job posting via GraphQL.

        Args:
            posting_id: UUID of the job posting.
            organization_slug: Ashby org slug.

        Returns:
            Dict with keys: posting_id, fields, required_fields, custom_fields.
        """
        data = self._graphql(
            _GQL_GET_JOB, {"org": organization_slug, "jobId": posting_id}
        )
        raw = data.get("jobPosting") or {}
        form_def = raw.get("applicationForm") or {}
        sections = form_def.get("sections") or []

        fields = []
        required_fields = []
        custom_fields = []

        for section in sections:
            for field_entry in section.get("fields") or []:
                field_info = field_entry.get("field") or {}
                path = field_info.get("path", "")
                label = field_info.get("title", path)
                required = field_entry.get("isRequired", False)
                field_type = field_info.get("type", "text")

                entry = {
                    "path": path,
                    "label": label,
                    "type": field_type,
                    "required": required,
                    "is_system_field": path.startswith("_systemfield_"),
                }
                fields.append(entry)
                if required:
                    required_fields.append(path)
                if not path.startswith("_systemfield_"):
                    custom_fields.append(entry)

        return {
            "posting_id": posting_id,
            "organization_slug": organization_slug,
            "fields": fields,
            "required_fields": required_fields,
            "custom_fields": custom_fields,
        }

    def submit_application(
        self,
        posting_id: str,
        organization_slug: str,
        answers: dict,
        resume_path: str,
    ) -> dict:
        """
        Submit a job application to Ashby via the posting API.

        Args:
            posting_id: UUID of the job posting.
            organization_slug: Ashby org slug.
            answers: Dict mapping field paths to answer values.
                     e.g. {"_systemfield_name": "Jane Doe", "_systemfield_email": "jane@x.com"}
            resume_path: Local filesystem path to the resume PDF/DOCX.

        Returns:
            API response dict with keys: success, applicationId (on success).

        Raises:
            FileNotFoundError: If resume_path does not exist.
            requests.HTTPError: On API errors.
        """
        resume_file = Path(resume_path)
        if not resume_file.exists():
            raise FileNotFoundError(f"Resume not found: {resume_path}")

        # Encode resume as base64
        resume_bytes = resume_file.read_bytes()
        resume_b64 = base64.b64encode(resume_bytes).decode("utf-8")

        # Build applicationForm fields list
        form_fields = [
            {"path": path, "value": value} for path, value in answers.items()
        ]

        payload = {
            "organizationHostedJobsPageName": organization_slug,
            "applicationForm": {"fields": form_fields},
            "resume": resume_b64,
        }

        url = f"{API_BASE}/{posting_id}/apply"
        try:
            response = self._post(url, json_body=payload)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            body = exc.response.text if exc.response is not None else ""
            return {
                "success": False,
                "error": f"HTTP {status}",
                "detail": body,
                "posting_id": posting_id,
                "organization_slug": organization_slug,
            }

        return {
            "success": response.get("success", True),
            "application_id": response.get("applicationId") or response.get("id"),
            "posting_id": posting_id,
            "organization_slug": organization_slug,
            "raw": response,
        }

    @staticmethod
    def extract_org_and_id_from_url(url: str) -> tuple[str, str]:
        """
        Parse org slug and job UUID from an Ashby-hosted job URL.

        Supported formats:
          - https://jobs.ashbyhq.com/{org}/{uuid}
          - https://jobs.ashbyhq.com/{org}/{uuid}?...

        Args:
            url: Full Ashby job URL.

        Returns:
            Tuple of (org_slug, posting_id).

        Raises:
            ValueError: If the URL does not match the expected pattern.
        """
        pattern = r"https?://jobs\.ashbyhq\.com/([^/?#]+)/([^/?#]+)"
        match = re.match(pattern, url.strip())
        if not match:
            raise ValueError(
                f"URL does not match expected Ashby pattern "
                f"(https://jobs.ashbyhq.com/{{org}}/{{uuid}}): {url}"
            )
        org_slug = match.group(1)
        posting_id = match.group(2)
        return org_slug, posting_id

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def build_answers_from_profile(
        self, profile: dict, custom_answers: Optional[dict] = None
    ) -> dict:
        """
        Map a candidate profile dict to Ashby field paths.

        Args:
            profile: Dict with keys: name, email, phone, linkedin, github, location, website.
            custom_answers: Additional field-path → value pairs (custom questions).

        Returns:
            Dict of {field_path: value} ready for submit_application().
        """
        mapping = {
            SYSTEM_FIELDS["name"]: profile.get("name", ""),
            SYSTEM_FIELDS["email"]: profile.get("email", ""),
        }
        if profile.get("phone"):
            mapping[SYSTEM_FIELDS["phone"]] = profile["phone"]
        if profile.get("linkedin"):
            mapping[SYSTEM_FIELDS["linkedin"]] = profile["linkedin"]
        if profile.get("github"):
            mapping[SYSTEM_FIELDS["github"]] = profile["github"]
        if profile.get("portfolio") or profile.get("website"):
            mapping[SYSTEM_FIELDS["portfolio"]] = profile.get(
                "portfolio"
            ) or profile.get("website", "")
        if profile.get("location"):
            mapping[SYSTEM_FIELDS["location"]] = profile["location"]

        if custom_answers:
            mapping.update(custom_answers)

        # Remove empty strings to avoid sending blank optional fields
        return {k: v for k, v in mapping.items() if v}
