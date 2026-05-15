"""
ATS API clients for direct API-based job scraping.

Provides a unified registry so the planner and source subagent can dynamically
select which platforms to query based on user priority and job type.

Usage:
    from ats_clients import ATS_REGISTRY, get_client, search_all

    # Get a single client
    client = get_client("greenhouse")
    jobs = client.search_jobs(query="python developer", location="Remote")

    # Search across multiple platforms
    results = search_all(
        query="full stack engineer",
        location="San Francisco, CA",
        platforms=["greenhouse", "lever", "ashby"],
        limit_per_platform=25,
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client imports
# ---------------------------------------------------------------------------
from .greenhouse import GreenhouseClient, KNOWN_BOARD_TOKENS
from .lever import LeverClient, KNOWN_SITES as LEVER_KNOWN_SITES
from .ashby import AshbyClient, KNOWN_ASHBY_ORGS
from .workable import WorkableClient, KNOWN_SUBDOMAINS as WORKABLE_KNOWN_SUBDOMAINS
from .smartrecruiters import SmartRecruitersClient, KNOWN_COMPANY_IDENTIFIERS
from .bamboohr import BambooHRClient, KNOWN_SUBDOMAINS as BAMBOOHR_KNOWN_SUBDOMAINS
from .linkedin import LinkedInClient
from .ziprecruiter import ZipRecruiterClient
from .glassdoor import GlassdoorClient
from .simplyhired import SimplyHiredClient
from .monster import MonsterClient
from .careerjet import CareerJetClient
from .google_jobs import GoogleJobsClient


# ---------------------------------------------------------------------------
# Protocol for type-safe client access
# ---------------------------------------------------------------------------
@runtime_checkable
class ATSClient(Protocol):
    """Minimal interface every ATS client exposes."""

    def search_jobs(
        self,
        query: str,
        location: str = "",
        limit: int = 25,
        **kwargs: Any,
    ) -> list[dict]: ...


# ---------------------------------------------------------------------------
# Platform metadata
# ---------------------------------------------------------------------------
@dataclass
class PlatformInfo:
    """Static metadata about a supported ATS platform."""

    name: str  # Human-readable name
    slug: str  # Registry key (lowercase, no spaces)
    client_cls: type  # Class to instantiate
    auth_required: bool  # Whether an API key is needed for reading
    public_api: bool  # Whether it has a free public jobs API
    known_companies_key: str  # Name of the module-level constant
    known_companies: list[str] = field(default_factory=list)
    default_priority: int = 50  # 0-100, higher = prefer this source
    best_for: list[str] = field(default_factory=list)  # e.g. ["fulltime", "startup"]
    description: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
ATS_REGISTRY: Dict[str, PlatformInfo] = {
    "greenhouse": PlatformInfo(
        name="Greenhouse",
        slug="greenhouse",
        client_cls=GreenhouseClient,
        auth_required=False,
        public_api=True,
        known_companies_key="KNOWN_BOARD_TOKENS",
        known_companies=list(KNOWN_BOARD_TOKENS),
        default_priority=90,
        best_for=["fulltime", "startup", "tech"],
        description="Popular ATS for tech companies. Public boards API, no auth needed.",
    ),
    "lever": PlatformInfo(
        name="Lever",
        slug="lever",
        client_cls=LeverClient,
        auth_required=False,
        public_api=True,
        known_companies_key="KNOWN_SITES",
        known_companies=list(LEVER_KNOWN_SITES),
        default_priority=85,
        best_for=["fulltime", "startup", "tech", "growth"],
        description="Lever postings API. Public, no auth for reading.",
    ),
    "ashby": PlatformInfo(
        name="Ashby",
        slug="ashby",
        client_cls=AshbyClient,
        auth_required=False,
        public_api=True,
        known_companies_key="KNOWN_ASHBY_ORGS",
        known_companies=list(KNOWN_ASHBY_ORGS),
        default_priority=80,
        best_for=["fulltime", "startup", "tech"],
        description="GraphQL-based job board. Popular with modern startups.",
    ),
    "workable": PlatformInfo(
        name="Workable",
        slug="workable",
        client_cls=WorkableClient,
        auth_required=False,
        public_api=True,
        known_companies_key="KNOWN_SUBDOMAINS",
        known_companies=list(WORKABLE_KNOWN_SUBDOMAINS),
        default_priority=70,
        best_for=["fulltime", "smb", "international"],
        description="Public global board + company SPI. Auth optional for reading.",
    ),
    "smartrecruiters": PlatformInfo(
        name="SmartRecruiters",
        slug="smartrecruiters",
        client_cls=SmartRecruitersClient,
        auth_required=False,
        public_api=True,
        known_companies_key="KNOWN_COMPANY_IDENTIFIERS",
        known_companies=list(KNOWN_COMPANY_IDENTIFIERS),
        default_priority=60,
        best_for=["fulltime", "enterprise", "retail"],
        description="REST API for large enterprises. Public postings endpoint.",
    ),
    "bamboohr": PlatformInfo(
        name="BambooHR",
        slug="bamboohr",
        client_cls=BambooHRClient,
        auth_required=False,
        public_api=True,
        known_companies_key="KNOWN_SUBDOMAINS",
        known_companies=list(BAMBOOHR_KNOWN_SUBDOMAINS),
        default_priority=50,
        best_for=["fulltime", "smb", "non-tech"],
        description="Embed endpoint for SMBs. HTML parsing fallback.",
    ),
    "linkedin": PlatformInfo(
        name="LinkedIn",
        slug="linkedin",
        client_cls=LinkedInClient,
        auth_required=False,
        public_api=False,
        known_companies_key="",
        known_companies=[],
        default_priority=88,
        best_for=["fulltime", "contract", "executive", "diverse"],
        description="LinkedIn public jobs search scraper. No auth for basic listings.",
    ),
    "ziprecruiter": PlatformInfo(
        name="ZipRecruiter",
        slug="ziprecruiter",
        client_cls=ZipRecruiterClient,
        auth_required=False,
        public_api=True,
        known_companies_key="",
        known_companies=[],
        default_priority=72,
        best_for=["fulltime", "smb", "diverse", "volume"],
        description="ZipRecruiter public embed JSON endpoint. No auth required.",
    ),
    "glassdoor": PlatformInfo(
        name="Glassdoor",
        slug="glassdoor",
        client_cls=GlassdoorClient,
        auth_required=False,
        public_api=True,
        known_companies_key="",
        known_companies=[],
        default_priority=68,
        best_for=["fulltime", "enterprise", "diverse"],
        description="Glassdoor public job listings. Includes company reviews context.",
    ),
    "simplyhired": PlatformInfo(
        name="SimplyHired",
        slug="simplyhired",
        client_cls=SimplyHiredClient,
        auth_required=False,
        public_api=True,
        known_companies_key="",
        known_companies=[],
        default_priority=55,
        best_for=["fulltime", "smb", "diverse", "volume"],
        description="SimplyHired public JSON search API. No auth needed.",
    ),
    "monster": PlatformInfo(
        name="Monster",
        slug="monster",
        client_cls=MonsterClient,
        auth_required=False,
        public_api=True,
        known_companies_key="",
        known_companies=[],
        default_priority=52,
        best_for=["fulltime", "enterprise", "diverse"],
        description="Monster public job search JSON API. No auth needed.",
    ),
    "careerjet": PlatformInfo(
        name="CareerJet",
        slug="careerjet",
        client_cls=CareerJetClient,
        auth_required=False,
        public_api=True,
        known_companies_key="",
        known_companies=[],
        default_priority=48,
        best_for=["fulltime", "international", "diverse"],
        description="CareerJet free public JSON API. No key required for basic access.",
    ),
    "google_jobs": PlatformInfo(
        name="Google Jobs",
        slug="google_jobs",
        client_cls=GoogleJobsClient,
        auth_required=False,
        public_api=False,
        known_companies_key="",
        known_companies=[],
        default_priority=75,
        best_for=["fulltime", "contract", "diverse", "aggregated"],
        description="Google for Jobs aggregator. Wide coverage via JSON-LD / SerpAPI.",
    ),
}


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------
_client_cache: Dict[str, Any] = {}


def get_client(platform: str, **kwargs: Any) -> Any:
    """Instantiate (or return cached) client for *platform*.

    Args:
        platform: Registry key (e.g. "greenhouse", "lever").
        **kwargs: Passed to the client constructor.

    Returns:
        An instance of the corresponding ATS client.

    Raises:
        KeyError: If *platform* is not in the registry.
    """
    if platform not in ATS_REGISTRY:
        raise KeyError(
            f"Unknown platform '{platform}'. Available: {list(ATS_REGISTRY.keys())}"
        )
    cache_key = f"{platform}:{hash(frozenset(kwargs.items()))}"
    if cache_key not in _client_cache:
        info = ATS_REGISTRY[platform]
        _client_cache[cache_key] = info.client_cls(**kwargs)
    return _client_cache[cache_key]


def get_known_companies(platform: str) -> list[str]:
    """Return the list of known companies/boards/subdomains for *platform*."""
    if platform not in ATS_REGISTRY:
        raise KeyError(f"Unknown platform '{platform}'.")
    return list(ATS_REGISTRY[platform].known_companies)


def update_known_companies(platform: str, new_companies: list[str]) -> int:
    """Add newly discovered companies to a platform's known list.

    Returns the number of *new* companies added (deduped).
    """
    if platform not in ATS_REGISTRY:
        raise KeyError(f"Unknown platform '{platform}'.")
    info = ATS_REGISTRY[platform]
    existing = set(info.known_companies)
    additions = [c for c in new_companies if c not in existing]
    info.known_companies.extend(additions)
    if additions:
        logger.info(
            "Added %d new companies to %s: %s",
            len(additions),
            platform,
            additions[:5],
        )
    return len(additions)


def search_all(
    query: str,
    location: str = "",
    platforms: Optional[List[str]] = None,
    limit_per_platform: int = 25,
    extra_companies: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, list[dict]]:
    """Search across multiple ATS platforms in sequence.

    Args:
        query: Job search query (e.g. "full stack engineer").
        location: Location filter (e.g. "Remote", "San Francisco, CA").
        platforms: Which platforms to search. None = all registered.
        limit_per_platform: Max jobs to return per platform.
        extra_companies: Optional dict of {platform: [company_slugs]} to add
                         to known companies before searching.

    Returns:
        Dict mapping platform slug -> list of job dicts.
    """
    targets = platforms or list(ATS_REGISTRY.keys())
    results: Dict[str, list[dict]] = {}

    # Merge any dynamically discovered companies first
    if extra_companies:
        for plat, companies in extra_companies.items():
            if plat in ATS_REGISTRY:
                update_known_companies(plat, companies)

    for plat in targets:
        if plat not in ATS_REGISTRY:
            logger.warning("Skipping unknown platform: %s", plat)
            continue
        try:
            client = get_client(plat)
            jobs = client.search_jobs(
                query=query, location=location, limit=limit_per_platform
            )
            results[plat] = jobs
            logger.info("Found %d jobs on %s", len(jobs), plat)
        except Exception as exc:
            logger.error("Error searching %s: %s", plat, exc, exc_info=True)
            results[plat] = []

    return results


def platforms_for_job_type(job_type: str) -> list[str]:
    """Return platform slugs best suited for a given job type.

    Args:
        job_type: One of "contract", "fulltime", "diverse", "premium".

    Returns:
        Ordered list of platform slugs, highest priority first.
    """
    type_map = {
        "contract": [],  # Contract jobs → Dice MCP primary, ATS secondary
        "fulltime": list(ATS_REGISTRY.keys()),  # All ATS platforms
        "diverse": list(ATS_REGISTRY.keys()),  # All ATS platforms
        "premium": ["greenhouse", "lever", "ashby"],  # Top-tier ATS only
    }

    platforms = type_map.get(job_type, list(ATS_REGISTRY.keys()))

    # Sort by default_priority descending
    return sorted(
        platforms,
        key=lambda p: ATS_REGISTRY[p].default_priority,
        reverse=True,
    )


def platform_summary() -> str:
    """Return a human-readable summary of all registered platforms."""
    lines = ["ATS Platform Registry", "=" * 40]
    for slug, info in ATS_REGISTRY.items():
        lines.append(
            f"  {info.name} ({slug}): "
            f"{len(info.known_companies)} known companies | "
            f"priority={info.default_priority} | "
            f"auth={'required' if info.auth_required else 'none'} | "
            f"best_for={info.best_for}"
        )
    return "\n".join(lines)


__all__ = [
    # Registry & metadata
    "ATS_REGISTRY",
    "PlatformInfo",
    "ATSClient",
    # Client classes
    "GreenhouseClient",
    "LeverClient",
    "AshbyClient",
    "WorkableClient",
    "SmartRecruitersClient",
    "BambooHRClient",
    "LinkedInClient",
    "ZipRecruiterClient",
    "GlassdoorClient",
    "SimplyHiredClient",
    "MonsterClient",
    "CareerJetClient",
    "GoogleJobsClient",
    # Known company lists
    "KNOWN_BOARD_TOKENS",
    "LEVER_KNOWN_SITES",
    "KNOWN_ASHBY_ORGS",
    "WORKABLE_KNOWN_SUBDOMAINS",
    "KNOWN_COMPANY_IDENTIFIERS",
    "BAMBOOHR_KNOWN_SUBDOMAINS",
    # Helpers
    "get_client",
    "get_known_companies",
    "update_known_companies",
    "search_all",
    "platforms_for_job_type",
    "platform_summary",
]
