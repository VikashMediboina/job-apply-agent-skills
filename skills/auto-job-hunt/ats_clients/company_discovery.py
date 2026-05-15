"""
Dynamic company discovery for ATS platforms.

Instead of relying on hardcoded company lists, this module discovers new
companies/boards/subdomains by:

1. Probing known URL patterns (e.g. boards-api.greenhouse.io/{slug})
2. Cross-referencing companies found in job postings from MCP sources
3. Loading previously discovered companies from a persistent cache
4. Accepting manual additions from the user or learning hooks

The discovered companies are merged into the ATS_REGISTRY at runtime and
persisted to disk so future sessions start with an expanded list.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
_CACHE_FILE = _THIS_DIR / "discovered_companies.json"

# ---------------------------------------------------------------------------
# URL patterns for probing ATS platforms
# ---------------------------------------------------------------------------
# Each pattern maps a platform slug to a URL template and expected success
# indicator.  {slug} is replaced with the candidate company identifier.
PROBE_PATTERNS: Dict[str, Dict[str, Any]] = {
    "greenhouse": {
        "url": "https://boards-api.greenhouse.io/v1/boards/{slug}",
        "method": "GET",
        "success_codes": [200],
        "extract_name": lambda data: data.get("name", ""),
    },
    "lever": {
        "url": "https://api.lever.co/v0/postings/{slug}?limit=1",
        "method": "GET",
        "success_codes": [200],
        "extract_name": lambda data: slug if isinstance(data, list) else "",
    },
    "ashby": {
        # Ashby uses GraphQL — probe the job board page instead
        "url": "https://jobs.ashbyhq.com/{slug}",
        "method": "HEAD",
        "success_codes": [200],
        "extract_name": lambda data: "",
    },
    "workable": {
        "url": "https://apply.workable.com/api/v1/widget/accounts/{slug}",
        "method": "GET",
        "success_codes": [200],
        "extract_name": lambda data: data.get("name", ""),
    },
    "smartrecruiters": {
        "url": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
        "method": "GET",
        "success_codes": [200],
        "extract_name": lambda data: "",
    },
    "bamboohr": {
        "url": "https://{slug}.bamboohr.com/careers",
        "method": "HEAD",
        "success_codes": [200],
        "extract_name": lambda data: "",
    },
}

# ---------------------------------------------------------------------------
# URL-based platform detection patterns
# ---------------------------------------------------------------------------
# Given a job URL from Dice/Indeed, detect which ATS it points to and
# extract the company slug.
URL_DETECTION_RULES: list[Dict[str, Any]] = [
    {
        "platform": "greenhouse",
        "patterns": [
            r"boards\.greenhouse\.io/(?P<slug>[^/]+)",
            r"job-boards\.greenhouse\.io/(?P<slug>[^/]+)",
            r"(?P<slug>[^.]+)\.greenhouse\.io",
        ],
    },
    {
        "platform": "lever",
        "patterns": [
            r"jobs\.lever\.co/(?P<slug>[^/]+)",
        ],
    },
    {
        "platform": "ashby",
        "patterns": [
            r"jobs\.ashbyhq\.com/(?P<slug>[^/]+)",
        ],
    },
    {
        "platform": "workable",
        "patterns": [
            r"apply\.workable\.com/(?P<slug>[^/]+)",
            r"(?P<slug>[^.]+)\.workable\.com",
        ],
    },
    {
        "platform": "smartrecruiters",
        "patterns": [
            r"jobs\.smartrecruiters\.com/(?P<slug>[^/]+)",
            r"careers\.smartrecruiters\.com/(?P<slug>[^/]+)",
        ],
    },
    {
        "platform": "bamboohr",
        "patterns": [
            r"(?P<slug>[^.]+)\.bamboohr\.com",
        ],
    },
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class DiscoveredCompany:
    """A company/board/subdomain discovered for a specific ATS platform."""

    slug: str
    platform: str
    name: str = ""
    discovered_from: str = ""  # "url_extract", "probe", "manual", "crossref"
    discovered_at: str = ""  # ISO timestamp
    verified: bool = False  # True if probe confirmed it exists
    job_count: int = 0  # Last known job count (0 = unknown)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "platform": self.platform,
            "name": self.name,
            "discovered_from": self.discovered_from,
            "discovered_at": self.discovered_at,
            "verified": self.verified,
            "job_count": self.job_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DiscoveredCompany":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DiscoveryCache:
    """Persistent cache of all discovered companies across platforms."""

    companies: Dict[str, Dict[str, DiscoveredCompany]] = field(default_factory=dict)
    # companies[platform][slug] = DiscoveredCompany
    last_updated: str = ""

    def add(self, company: DiscoveredCompany) -> bool:
        """Add a company to the cache. Returns True if it was new."""
        if company.platform not in self.companies:
            self.companies[company.platform] = {}
        if company.slug in self.companies[company.platform]:
            return False
        self.companies[company.platform][company.slug] = company
        return True

    def get_slugs(self, platform: str) -> list[str]:
        """Return all known slugs for a platform."""
        return list(self.companies.get(platform, {}).keys())

    def total(self) -> int:
        return sum(len(v) for v in self.companies.values())

    def save(self, path: Optional[Path] = None) -> None:
        """Persist the cache to JSON."""
        target = path or _CACHE_FILE
        data = {
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_companies": self.total(),
            "platforms": {},
        }
        for platform, comps in self.companies.items():
            data["platforms"][platform] = [c.to_dict() for c in comps.values()]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2))
        logger.info("Saved discovery cache: %d companies to %s", self.total(), target)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "DiscoveryCache":
        """Load the cache from JSON. Returns empty cache if file missing."""
        target = path or _CACHE_FILE
        cache = cls()
        if not target.exists():
            return cache
        try:
            raw = json.loads(target.read_text())
            cache.last_updated = raw.get("last_updated", "")
            for platform, companies in raw.get("platforms", {}).items():
                for c_data in companies:
                    c_data["platform"] = platform
                    company = DiscoveredCompany.from_dict(c_data)
                    cache.add(company)
            logger.info(
                "Loaded discovery cache: %d companies from %s",
                cache.total(),
                target,
            )
        except (json.JSONDecodeError, KeyError) as exc:
            logger.warning("Failed to load discovery cache: %s", exc)
        return cache


# ---------------------------------------------------------------------------
# Core discovery functions
# ---------------------------------------------------------------------------


def detect_platform_from_url(url: str) -> Optional[Dict[str, str]]:
    """Detect ATS platform and company slug from a job/apply URL.

    Returns:
        {"platform": "greenhouse", "slug": "stripe"} or None.
    """
    for rule in URL_DETECTION_RULES:
        for pattern in rule["patterns"]:
            m = re.search(pattern, url, re.IGNORECASE)
            if m:
                slug = m.group("slug").lower().strip("/")
                # Skip generic subdomains
                if slug in ("www", "api", "jobs", "careers", "apply"):
                    continue
                return {"platform": rule["platform"], "slug": slug}
    return None


def extract_companies_from_jobs(
    jobs: list[dict],
) -> Dict[str, Set[str]]:
    """Scan a list of job dicts and extract ATS company slugs from URLs.

    Looks at 'applyUrl', 'url', 'detailUrl' fields in each job dict.

    Returns:
        Dict mapping platform slug -> set of discovered company slugs.
    """
    discovered: Dict[str, Set[str]] = {}

    url_fields = ["applyUrl", "url", "detailUrl", "apply_url", "detail_url"]

    for job in jobs:
        for field_name in url_fields:
            url = job.get(field_name, "")
            if not url:
                continue
            result = detect_platform_from_url(url)
            if result:
                plat = result["platform"]
                slug = result["slug"]
                if plat not in discovered:
                    discovered[plat] = set()
                discovered[plat].add(slug)

    return discovered


def probe_company(
    platform: str, slug: str, timeout: float = 5.0
) -> Optional[DiscoveredCompany]:
    """Probe whether a company exists on a given ATS platform.

    Makes a lightweight HTTP request to the platform's public API.

    Args:
        platform: ATS platform slug (e.g. "greenhouse").
        slug: Company identifier to probe.
        timeout: Request timeout in seconds.

    Returns:
        DiscoveredCompany if the probe succeeded, None otherwise.
    """
    if platform not in PROBE_PATTERNS:
        return None

    pattern = PROBE_PATTERNS[platform]
    url = pattern["url"].format(slug=slug)
    method = pattern.get("method", "GET")

    try:
        req = Request(url, method=method)
        req.add_header("User-Agent", "AutoJobHunt/1.0 (company discovery)")
        req.add_header("Accept", "application/json")

        with urlopen(req, timeout=timeout) as resp:
            if resp.status in pattern["success_codes"]:
                name = ""
                if method == "GET":
                    try:
                        data = json.loads(resp.read().decode("utf-8"))
                        extract = pattern.get("extract_name")
                        if extract and callable(extract):
                            name = extract(data)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass

                return DiscoveredCompany(
                    slug=slug,
                    platform=platform,
                    name=name or slug,
                    discovered_from="probe",
                    discovered_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    verified=True,
                )
    except HTTPError as exc:
        if exc.code == 404:
            logger.debug("Probe 404 for %s/%s", platform, slug)
        else:
            logger.debug("Probe HTTP %d for %s/%s", exc.code, platform, slug)
    except (URLError, TimeoutError, OSError) as exc:
        logger.debug("Probe failed for %s/%s: %s", platform, slug, exc)

    return None


def discover_from_job_results(
    jobs: list[dict],
    cache: Optional[DiscoveryCache] = None,
    verify: bool = False,
) -> DiscoveryCache:
    """Extract and optionally verify new companies from job search results.

    This is the main entry point called after each MCP search (Dice/Indeed)
    to automatically expand ATS company lists.

    Args:
        jobs: List of job dicts from any source.
        cache: Existing cache to merge into. Loads from disk if None.
        verify: If True, probe each new company to confirm it exists.

    Returns:
        Updated DiscoveryCache with any new discoveries.
    """
    if cache is None:
        cache = DiscoveryCache.load()

    extracted = extract_companies_from_jobs(jobs)
    new_count = 0

    for platform, slugs in extracted.items():
        for slug in slugs:
            # Skip if already in cache
            if slug in cache.companies.get(platform, {}):
                continue

            company = DiscoveredCompany(
                slug=slug,
                platform=platform,
                name=slug,
                discovered_from="url_extract",
                discovered_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                verified=False,
            )

            if verify:
                verified = probe_company(platform, slug)
                if verified:
                    company = verified
                else:
                    company.verified = False

            if cache.add(company):
                new_count += 1
                logger.info(
                    "Discovered new %s company: %s (verified=%s)",
                    platform,
                    slug,
                    company.verified,
                )

    if new_count > 0:
        cache.save()
        logger.info("Discovery complete: %d new companies found", new_count)

    return cache


def get_expanded_company_list(
    platform: str,
    cache: Optional[DiscoveryCache] = None,
) -> list[str]:
    """Return the union of hardcoded + discovered companies for a platform.

    This is what the search functions should use instead of the raw
    KNOWN_* constants.

    Args:
        platform: ATS platform slug.
        cache: Discovery cache. Loads from disk if None.

    Returns:
        Deduplicated list of company slugs.
    """
    # Import here to avoid circular imports
    from . import ATS_REGISTRY

    if platform not in ATS_REGISTRY:
        return []

    if cache is None:
        cache = DiscoveryCache.load()

    # Start with hardcoded known companies
    known = set(ATS_REGISTRY[platform].known_companies)

    # Add discovered companies
    discovered = set(cache.get_slugs(platform))

    merged = sorted(known | discovered)
    logger.debug(
        "%s companies: %d known + %d discovered = %d total",
        platform,
        len(known),
        len(discovered - known),
        len(merged),
    )
    return merged


def bulk_probe(
    platform: str,
    slugs: list[str],
    delay: float = 0.5,
    cache: Optional[DiscoveryCache] = None,
) -> list[DiscoveredCompany]:
    """Probe a batch of candidate slugs against a platform.

    Useful for expanding known companies when search results are low.
    Includes a delay between requests to avoid rate limiting.

    Args:
        platform: ATS platform slug.
        slugs: Candidate company slugs to probe.
        delay: Seconds between requests.
        cache: Cache to check for already-known slugs.

    Returns:
        List of newly verified companies.
    """
    if cache is None:
        cache = DiscoveryCache.load()

    existing = set(cache.get_slugs(platform))
    new_finds: list[DiscoveredCompany] = []

    for slug in slugs:
        if slug in existing:
            continue

        result = probe_company(platform, slug)
        if result:
            if cache.add(result):
                new_finds.append(result)
                logger.info("Bulk probe: found %s/%s", platform, slug)

        if delay > 0:
            time.sleep(delay)

    if new_finds:
        cache.save()

    return new_finds


def discovery_summary(cache: Optional[DiscoveryCache] = None) -> str:
    """Human-readable summary of the discovery cache."""
    if cache is None:
        cache = DiscoveryCache.load()

    lines = [
        "Company Discovery Cache",
        "=" * 40,
        f"Last updated: {cache.last_updated or 'never'}",
        f"Total discovered: {cache.total()}",
        "",
    ]

    from . import ATS_REGISTRY

    for platform in ATS_REGISTRY:
        known = len(ATS_REGISTRY[platform].known_companies)
        discovered = len(cache.get_slugs(platform))
        verified = sum(
            1 for c in cache.companies.get(platform, {}).values() if c.verified
        )
        lines.append(
            f"  {platform}: {known} hardcoded + {discovered} discovered "
            f"({verified} verified)"
        )

    return "\n".join(lines)


__all__ = [
    "DiscoveredCompany",
    "DiscoveryCache",
    "detect_platform_from_url",
    "extract_companies_from_jobs",
    "probe_company",
    "discover_from_job_results",
    "get_expanded_company_list",
    "bulk_probe",
    "discovery_summary",
]
