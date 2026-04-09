"""
BambooHR ATS client — public careers embed API + multipart application submission.

BambooHR uses per-company subdomains. Most companies expose a public JSON careers
endpoint at:
  https://{subdomain}.bamboohr.com/jobs/embed2.php?applicationSource=bamboohrWebsite

No API key is required for listing open positions. Application submission uses a
standard multipart HTML form POST.
"""

import re
import time
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urljoin

try:
    import requests
    from requests import Session
except ImportError:
    raise ImportError("requests is required: pip install requests")

# ---------------------------------------------------------------------------
# Known BambooHR company subdomains (20+)
# ---------------------------------------------------------------------------
KNOWN_SUBDOMAINS: list[str] = [
    # Confirmed active (have open positions or HTML embed response)
    "zendesk",
    "hootsuite",
    # Commonly used BambooHR companies (may cycle hiring on/off)
    "samba",
    "soundcloud",
    "etsy",
    "wikimedia",
    "mozilla",
    "automattic",
    "basecamp",
    "fastly",
    "cloudinary",
    "imgix",
    "contentful",
    "sanity",
    "storyblok",
    "prismic",
    "butter",
    "strapi",
    "directus",
    "ghost",
    "webflow",
    "framer",
    "invisionapp",
    "drift",
    "intercom",
    "clubhouse",
    "vercel",
    "netlify",
]

# Seconds to wait between requests to avoid hammering company endpoints
_RATE_LIMIT_SLEEP = 0.5

# Public careers embed endpoint template
_EMBED_URL = "https://{subdomain}.bamboohr.com/jobs/embed2.php"
_CAREERS_LIST_URL = "https://{subdomain}.bamboohr.com/careers/list"
_JOB_DETAIL_URL = "https://{subdomain}.bamboohr.com/careers/{job_id}"
_JOB_APPLY_URL = "https://{subdomain}.bamboohr.com/careers/{job_id}/apply"


def _make_session() -> Session:
    """Return a requests Session with browser-like headers."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/html, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    return session


def _normalize_job(raw: dict, subdomain: str) -> dict:
    """Normalize a raw BambooHR job dict into the standard shape."""
    job_id = str(raw.get("id", ""))
    location_raw = raw.get("location", {})
    if isinstance(location_raw, dict):
        parts = filter(None, [location_raw.get("city"), location_raw.get("state")])
        location = ", ".join(parts)
    else:
        location = str(location_raw)

    department_raw = raw.get("department", {})
    if isinstance(department_raw, dict):
        department = department_raw.get("name", "")
    else:
        department = str(department_raw)

    return {
        "title": raw.get("title", "").strip(),
        "company": subdomain,  # company name is the subdomain by default
        "location": location,
        "url": _JOB_DETAIL_URL.format(subdomain=subdomain, job_id=job_id),
        "job_id": job_id,
        "subdomain": subdomain,
        "description": raw.get("description", ""),
        "department": department,
        "employment_type": raw.get("employmentType", ""),
        "remote": raw.get("isRemote", False),
        "source": "bamboohr",
    }


def _parse_jobs_from_html(html: str, subdomain: str) -> list[dict]:
    """
    Fallback HTML parser when embed endpoint returns non-JSON.

    Handles two formats:
    1. BambooHR embed HTML with department sections and ``BambooHR-ATS-Jobs-Item``
       list items (the standard public embed format).
    2. Inline JSON blobs inside ``<script>`` tags.
    3. Plain anchor tags linking to ``/careers/{id}`` (last resort).
    """
    jobs: list[dict] = []

    # --- Strategy 1: BambooHR standard embed HTML (department → jobs list) ---
    # The embed returns HTML like:
    #   <div class="BambooHR-ATS-Department-Header">Marketing</div>
    #   <ul class="BambooHR-ATS-Jobs-List">
    #     <li class="BambooHR-ATS-Jobs-Item">
    #       <a href="//company.bamboohr.com/careers/22">Job Title</a>
    #       <span class="BambooHR-ATS-Location">City, State</span>
    #     </li>
    #   </ul>
    dept_pattern = re.compile(
        r'<div[^>]+class="BambooHR-ATS-Department-Header"[^>]*>(.*?)</div>'
        r'.*?<ul[^>]+class="BambooHR-ATS-Jobs-List"[^>]*>(.*?)</ul>',
        re.DOTALL | re.IGNORECASE,
    )
    job_item_pattern = re.compile(
        r'<li[^>]+class="BambooHR-ATS-Jobs-Item"[^>]*>'
        r'.*?<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>'
        r'(?:.*?<span[^>]+class="BambooHR-ATS-Location"[^>]*>(.*?)</span>)?',
        re.DOTALL | re.IGNORECASE,
    )
    seen: set[str] = set()
    for dept_match in dept_pattern.finditer(html):
        dept_name = re.sub(r"<[^>]+>", "", dept_match.group(1)).strip()
        jobs_html = dept_match.group(2)
        for job_match in job_item_pattern.finditer(jobs_html):
            href = job_match.group(1)
            title = re.sub(r"<[^>]+>", "", job_match.group(2)).strip()
            location = re.sub(r"<[^>]+>", "", job_match.group(3) or "").strip()
            # Fix protocol-relative URLs (//company.bamboohr.com/careers/15)
            if href.startswith("//"):
                href = "https:" + href
            jid_m = re.search(r"/careers/(\d+)", href)
            job_id = jid_m.group(1) if jid_m else ""
            if job_id and job_id not in seen:
                seen.add(job_id)
                jobs.append(
                    {
                        "title": title,
                        "company": subdomain,
                        "location": location,
                        "url": _JOB_DETAIL_URL.format(
                            subdomain=subdomain, job_id=job_id
                        ),
                        "job_id": job_id,
                        "subdomain": subdomain,
                        "description": "",
                        "department": dept_name,
                        "employment_type": "",
                        "remote": False,
                        "source": "bamboohr",
                    }
                )
    if jobs:
        return jobs

    # --- Strategy 2: JSON embedded in a <script> tag ---
    pattern = re.compile(
        r"(?:window\.__BAMBOOHR_INIT__|var\s+\w*[Jj]obs?\w*\s*=)\s*(\{.*?\});",
        re.DOTALL,
    )
    match = pattern.search(html)
    if match:
        try:
            data = json.loads(match.group(1))
            raw_list = data.get("result", data.get("jobs", data.get("data", [])))
            for raw in raw_list:
                jobs.append(_normalize_job(raw, subdomain))
            return jobs
        except (json.JSONDecodeError, AttributeError):
            pass

    # --- Strategy 3: Plain anchor tags with /careers/{id} (last resort) ---
    # Handles both absolute, protocol-relative, and path-only hrefs.
    anchor_pattern = re.compile(
        r'<a[^>]+href=["\'](?:(?:https?:)?//[^"\']*)?/careers/(\d+)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    for m in anchor_pattern.finditer(html):
        job_id = m.group(1)
        title = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if job_id and job_id not in seen:
            seen.add(job_id)
            jobs.append(
                {
                    "title": title,
                    "company": subdomain,
                    "location": "",
                    "url": _JOB_DETAIL_URL.format(subdomain=subdomain, job_id=job_id),
                    "job_id": job_id,
                    "subdomain": subdomain,
                    "description": "",
                    "department": "",
                    "employment_type": "",
                    "remote": False,
                    "source": "bamboohr",
                }
            )

    return jobs


class BambooHRClient:
    """
    Client for BambooHR's public careers API.

    Uses the public embed endpoint — no API key required.
    Application submission uses multipart form POST.
    """

    def __init__(self, session: Session | None = None) -> None:
        self._session = session or _make_session()

    # ------------------------------------------------------------------
    # Public job listing
    # ------------------------------------------------------------------

    def get_jobs(self, subdomain: str) -> list[dict]:
        """
        Fetch all open positions for a BambooHR company subdomain.

        Tries the JSON embed endpoint first; falls back to HTML parsing.

        Args:
            subdomain: Company subdomain (e.g. "mozilla", "automattic").

        Returns:
            List of normalized job dicts.
        """
        url = _EMBED_URL.format(subdomain=subdomain)
        params = {"applicationSource": "bamboohrWebsite"}

        try:
            resp = self._session.get(url, params=params, timeout=15)
            time.sleep(_RATE_LIMIT_SLEEP)

            content_type = resp.headers.get("Content-Type", "")
            if resp.status_code == 200:
                if "application/json" in content_type or resp.text.strip().startswith(
                    "{"
                ):
                    try:
                        data = resp.json()
                        raw_list = data.get("result", data.get("jobs", []))
                        return [_normalize_job(r, subdomain) for r in raw_list]
                    except (ValueError, KeyError):
                        pass
                # Fallback: parse HTML
                return _parse_jobs_from_html(resp.text, subdomain)

        except requests.RequestException:
            pass

        # Second fallback: try the /careers/list endpoint
        try:
            list_url = _CAREERS_LIST_URL.format(subdomain=subdomain)
            resp2 = self._session.get(list_url, timeout=15)
            time.sleep(_RATE_LIMIT_SLEEP)
            if resp2.status_code == 200:
                try:
                    data = resp2.json()
                    raw_list = data.get("result", data.get("jobs", []))
                    return [_normalize_job(r, subdomain) for r in raw_list]
                except ValueError:
                    return _parse_jobs_from_html(resp2.text, subdomain)
        except requests.RequestException:
            pass

        return []

    def search_jobs(
        self,
        query: str,
        location: str = "",
        subdomains: list[str] | None = None,
        limit: int = 25,
    ) -> list[dict]:
        """
        Search across multiple BambooHR company subdomains.

        Fetches jobs from each subdomain and filters by query/location
        terms client-side (BambooHR does not expose a cross-company search API).

        Args:
            query:      Search string matched against title, department, description.
            location:   Optional location filter (city or state).
            subdomains: List of subdomains to search. Defaults to KNOWN_SUBDOMAINS.
            limit:      Max results to return across all companies.

        Returns:
            List of normalized job dicts, sorted by relevance (title match first).
        """
        if subdomains is None:
            subdomains = KNOWN_SUBDOMAINS

        query_lower = query.lower()
        location_lower = location.lower()
        results: list[dict] = []

        for subdomain in subdomains:
            if len(results) >= limit:
                break
            try:
                jobs = self.get_jobs(subdomain)
            except Exception:
                continue

            for job in jobs:
                haystack = " ".join(
                    [
                        job.get("title", ""),
                        job.get("department", ""),
                        job.get("description", ""),
                    ]
                ).lower()

                if query_lower not in haystack:
                    continue

                if (
                    location_lower
                    and location_lower not in job.get("location", "").lower()
                ):
                    continue

                results.append(job)

                if len(results) >= limit:
                    break

        return results[:limit]

    # ------------------------------------------------------------------
    # Job detail
    # ------------------------------------------------------------------

    def get_job(self, subdomain: str, job_id: str) -> dict:
        """
        Fetch detail page for a single BambooHR job.

        Args:
            subdomain: Company subdomain.
            job_id:    Numeric job ID from the careers listing.

        Returns:
            Normalized job dict with description populated from the detail page.
        """
        url = _JOB_DETAIL_URL.format(subdomain=subdomain, job_id=job_id)
        try:
            resp = self._session.get(url, timeout=15)
            time.sleep(_RATE_LIMIT_SLEEP)

            if resp.status_code == 200:
                # Attempt JSON (some detail endpoints return JSON)
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    try:
                        data = resp.json()
                        return _normalize_job(data, subdomain)
                    except ValueError:
                        pass

                # Extract description from HTML
                desc_match = re.search(
                    r'<div[^>]+class="[^"]*BambooRichText[^"]*"[^>]*>(.*?)</div>',
                    resp.text,
                    re.DOTALL | re.IGNORECASE,
                )
                description = ""
                if desc_match:
                    description = re.sub(r"<[^>]+>", "", desc_match.group(1)).strip()

                title_match = re.search(
                    r"<h1[^>]*>(.*?)</h1>", resp.text, re.DOTALL | re.IGNORECASE
                )
                title = ""
                if title_match:
                    title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()

                return {
                    "title": title,
                    "company": subdomain,
                    "location": "",
                    "url": url,
                    "job_id": job_id,
                    "subdomain": subdomain,
                    "description": description,
                    "department": "",
                    "employment_type": "",
                    "remote": False,
                    "source": "bamboohr",
                }
        except requests.RequestException:
            pass

        return {
            "title": "",
            "company": subdomain,
            "location": "",
            "url": url,
            "job_id": job_id,
            "subdomain": subdomain,
            "description": "",
            "department": "",
            "employment_type": "",
            "remote": False,
            "source": "bamboohr",
        }

    # ------------------------------------------------------------------
    # Application form discovery
    # ------------------------------------------------------------------

    def get_application_form(self, subdomain: str, job_id: str) -> dict:
        """
        Fetch and parse the application form for a BambooHR job.

        Fetches the /careers/{job_id}/apply page and extracts form fields.

        Args:
            subdomain: Company subdomain.
            job_id:    Numeric job ID.

        Returns:
            Dict with keys:
              - action (str): Form POST URL.
              - method (str): HTTP method (typically "POST").
              - fields (list[dict]): Each field: {name, type, label, required}.
              - hidden (dict): Hidden fields (name → value).
        """
        apply_url = _JOB_APPLY_URL.format(subdomain=subdomain, job_id=job_id)
        try:
            resp = self._session.get(apply_url, timeout=15)
            time.sleep(_RATE_LIMIT_SLEEP)

            if resp.status_code != 200:
                return {
                    "action": apply_url,
                    "method": "POST",
                    "fields": [],
                    "hidden": {},
                }

            html = resp.text

            # Extract form action
            form_match = re.search(
                r'<form[^>]+action=["\']([^"\']*)["\']',
                html,
                re.IGNORECASE,
            )
            action = apply_url
            if form_match:
                raw_action = form_match.group(1)
                action = urljoin(apply_url, raw_action)

            # Extract visible input/select/textarea fields
            fields: list[dict] = []
            field_pattern = re.compile(
                r"<(?:input|select|textarea)[^>]+>", re.IGNORECASE
            )
            name_re = re.compile(r'\bname=["\']([^"\']+)["\']', re.IGNORECASE)
            type_re = re.compile(r'\btype=["\']([^"\']+)["\']', re.IGNORECASE)
            required_re = re.compile(r"\brequired\b", re.IGNORECASE)

            for tag in field_pattern.finditer(html):
                tag_str = tag.group(0)
                name_m = name_re.search(tag_str)
                if not name_m:
                    continue
                field_name = name_m.group(1)
                field_type = "text"
                type_m = type_re.search(tag_str)
                if type_m:
                    field_type = type_m.group(1)
                if field_type == "hidden":
                    continue
                required = bool(required_re.search(tag_str))
                fields.append(
                    {
                        "name": field_name,
                        "type": field_type,
                        "label": field_name,
                        "required": required,
                    }
                )

            # Extract hidden fields
            hidden: dict[str, str] = {}
            hidden_pattern = re.compile(
                r'<input[^>]+type=["\']hidden["\'][^>]+>', re.IGNORECASE
            )
            value_re = re.compile(r'\bvalue=["\']([^"\']*)["\']', re.IGNORECASE)
            for tag in hidden_pattern.finditer(html):
                tag_str = tag.group(0)
                name_m = name_re.search(tag_str)
                value_m = value_re.search(tag_str)
                if name_m:
                    hidden[name_m.group(1)] = value_m.group(1) if value_m else ""

            return {
                "action": action,
                "method": "POST",
                "fields": fields,
                "hidden": hidden,
            }

        except requests.RequestException:
            return {"action": apply_url, "method": "POST", "fields": [], "hidden": {}}

    # ------------------------------------------------------------------
    # Application submission
    # ------------------------------------------------------------------

    def submit_application(
        self,
        subdomain: str,
        job_id: str,
        answers: dict[str, Any],
        resume_path: str,
    ) -> dict:
        """
        Submit a job application via multipart form POST.

        Fetches the form first to get hidden CSRF tokens, then POSTs.

        Args:
            subdomain:   Company subdomain.
            job_id:      Numeric job ID.
            answers:     Dict mapping form field names to answer strings.
            resume_path: Local path to the resume file (.pdf / .docx).

        Returns:
            Dict with keys:
              - success (bool)
              - status_code (int)
              - url (str): Final URL after submission.
              - message (str): Human-readable status.
        """
        form_info = self.get_application_form(subdomain, job_id)
        action = form_info.get("action") or _JOB_APPLY_URL.format(
            subdomain=subdomain, job_id=job_id
        )

        # Merge hidden fields with provided answers
        payload: dict[str, str] = dict(form_info.get("hidden", {}))
        payload.update({k: str(v) for k, v in answers.items()})

        resume_file = Path(resume_path)
        if not resume_file.exists():
            return {
                "success": False,
                "status_code": 0,
                "url": action,
                "message": f"Resume file not found: {resume_path}",
            }

        mime_map = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".doc": "application/msword",
        }
        mime_type = mime_map.get(resume_file.suffix.lower(), "application/octet-stream")

        # Build multipart payload — files separately from data
        files: dict[str, Any] = {
            "resume": (resume_file.name, resume_file.read_bytes(), mime_type),
        }

        try:
            resp = self._session.post(
                action,
                data=payload,
                files=files,
                timeout=30,
                allow_redirects=True,
            )
            time.sleep(_RATE_LIMIT_SLEEP)

            success = resp.status_code in (200, 201, 302)
            # BambooHR typically redirects to a confirmation page
            confirmation_keywords = [
                "thank",
                "confirm",
                "success",
                "received",
                "submitted",
            ]
            if resp.status_code == 200:
                body_lower = resp.text.lower()
                success = any(kw in body_lower for kw in confirmation_keywords)

            return {
                "success": success,
                "status_code": resp.status_code,
                "url": resp.url,
                "message": "Application submitted successfully"
                if success
                else f"HTTP {resp.status_code}",
            }

        except requests.RequestException as exc:
            return {
                "success": False,
                "status_code": 0,
                "url": action,
                "message": str(exc),
            }

    # ------------------------------------------------------------------
    # URL parsing
    # ------------------------------------------------------------------

    @staticmethod
    def extract_subdomain_and_id_from_url(url: str) -> tuple[str, str]:
        """
        Parse a BambooHR careers URL into (subdomain, job_id).

        Supports formats:
          - https://{subdomain}.bamboohr.com/careers/{job_id}
          - https://{subdomain}.bamboohr.com/careers/{job_id}/apply

        Args:
            url: BambooHR job or apply URL.

        Returns:
            Tuple of (subdomain, job_id). Both empty strings if parsing fails.
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname or ""
            if not hostname.endswith(".bamboohr.com"):
                return ("", "")

            subdomain = hostname.replace(".bamboohr.com", "")
            path = parsed.path  # e.g. /careers/12345 or /careers/12345/apply

            id_match = re.search(r"/careers/(\d+)", path)
            job_id = id_match.group(1) if id_match else ""

            return (subdomain, job_id)
        except Exception:
            return ("", "")
