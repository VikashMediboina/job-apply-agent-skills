#!/usr/bin/env python3
"""Planning module for job distribution, request parsing, and source allocation.

Supports dynamic allocation across MCP sources (Dice, Indeed) and ATS API
clients (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, BambooHR)
based on user priority (contract/fulltime/diverse/premium).
"""

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Ensure ats_clients is importable (skill root → parent of scripts/)
# ---------------------------------------------------------------------------
_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

try:
    from ats_clients import ATS_REGISTRY, platforms_for_job_type
except ImportError:
    # Graceful degradation if ats_clients not installed
    ATS_REGISTRY = {}

    def platforms_for_job_type(job_type: str) -> list[str]:
        return []


# ───────────────────────────────────────────────────────────────────────────
# Data classes
# ───────────────────────────────────────────────────────────────────────────


@dataclass
class RequestParams:
    """Parsed user request parameters."""

    roles: list[str]
    quantity: int
    timeline: str = "24hrs"
    location: Optional[str] = None
    visa_status: Optional[str] = None
    visa_required: Optional[bool] = None
    work_mode: str = "Flexible"
    score_threshold: int = 50
    source_split: str = "50/50"
    # NEW: priority drives source allocation strategy
    priority: str = "diverse"  # contract | fulltime | diverse | premium
    # NEW: explicit employment type (contract, fulltime, c2h, w2)
    employment_type: Optional[str] = None


@dataclass
class SearchTerm:
    """Search term with priority."""

    term: str
    set_number: int  # 1, 2, or 3
    priority: int  # lower = higher priority


@dataclass
class SourcePlan:
    """Plan for a single source (MCP or ATS API)."""

    source: str  # "dice", "indeed", or ATS slug ("greenhouse", "lever", etc.)
    source_type: str = "mcp"  # "mcp" or "ats_api"
    quantity: int = 0
    search_terms: list[SearchTerm] = field(default_factory=list)
    # ATS-specific: which companies/boards to search
    companies: list[str] = field(default_factory=list)
    # Weight 0-100 — higher means this source gets more allocation
    weight: int = 50


@dataclass
class RolePlan:
    """Plan for a single role."""

    role: str
    quantity: int
    sources: list[SourcePlan] = field(default_factory=list)


# ───────────────────────────────────────────────────────────────────────────
# Source Allocator
# ───────────────────────────────────────────────────────────────────────────

# Default allocation profiles: maps priority → {source: weight}
# Weights are relative; they get normalized to percentages at allocation time.
ALLOCATION_PROFILES: dict[str, dict[str, int]] = {
    "contract": {
        # Contract → Dice is king for contract roles; Indeed secondary;
        # ATS platforms rarely list contract positions
        "dice": 60,
        "indeed": 25,
        "greenhouse": 5,
        "lever": 5,
        "ashby": 3,
        "workable": 2,
        "smartrecruiters": 0,
        "bamboohr": 0,
    },
    "fulltime": {
        # Fulltime → ATS platforms are primary; Dice/Indeed for volume
        "dice": 15,
        "indeed": 15,
        "greenhouse": 20,
        "lever": 15,
        "ashby": 15,
        "workable": 10,
        "smartrecruiters": 5,
        "bamboohr": 5,
    },
    "diverse": {
        # Diverse → balanced across everything
        "dice": 25,
        "indeed": 20,
        "greenhouse": 15,
        "lever": 12,
        "ashby": 10,
        "workable": 8,
        "smartrecruiters": 5,
        "bamboohr": 5,
    },
    "premium": {
        # Premium → top-tier ATS only (startup/tech companies)
        "dice": 10,
        "indeed": 5,
        "greenhouse": 30,
        "lever": 25,
        "ashby": 20,
        "workable": 5,
        "smartrecruiters": 5,
        "bamboohr": 0,
    },
}


class SourceAllocator:
    """Dynamically allocates job search quota across MCP + ATS sources.

    Allocation logic:
    1. Read the user's priority (contract/fulltime/diverse/premium)
    2. Load the corresponding allocation profile (weights per source)
    3. Normalize weights → percentages → quantity per source
    4. Skip sources with weight=0 or no available companies
    5. Return a list of SourcePlan objects

    The allocator respects a legacy source_split (e.g. "60/40") when the user
    explicitly specifies it — in that case, only dice+indeed are used and ATS
    is disabled (backward-compatible behavior).
    """

    def __init__(
        self,
        priority: str = "diverse",
        explicit_split: Optional[str] = None,
        min_per_source: int = 3,
        use_learned_weights: bool = True,
    ):
        self.priority = priority
        self.explicit_split = explicit_split
        self.min_per_source = min_per_source
        self.use_learned_weights = use_learned_weights

    def allocate(
        self,
        total_quantity: int,
        search_terms: list[SearchTerm],
    ) -> list[SourcePlan]:
        """Produce a list of SourcePlan based on priority and quantity.

        Args:
            total_quantity: Total jobs to find.
            search_terms: Available search terms for all sources.

        Returns:
            List of SourcePlan, one per active source.
        """
        # Legacy mode: user explicitly set "60/40" → dice/indeed only
        if self.explicit_split and self._is_legacy_split(self.explicit_split):
            return self._legacy_allocate(total_quantity, search_terms)

        # Dynamic allocation based on priority profile
        # Try learned weights first (from source_metrics), fall back to defaults
        profile = None
        if self.use_learned_weights:
            try:
                from source_metrics import get_adjusted_profile

                profile = get_adjusted_profile(self.priority)
            except ImportError:
                pass
        if profile is None:
            profile = ALLOCATION_PROFILES.get(
                self.priority, ALLOCATION_PROFILES["diverse"]
            )

        # Filter out zero-weight sources and check ATS availability
        active: dict[str, int] = {}
        for source, weight in profile.items():
            if weight <= 0:
                continue
            # ATS sources need at least 1 known company
            if source in ATS_REGISTRY:
                if len(ATS_REGISTRY[source].known_companies) == 0:
                    continue
            active[source] = weight

        if not active:
            # Fallback to dice/indeed only
            return self._legacy_allocate(total_quantity, search_terms)

        # Normalize weights to quantities
        total_weight = sum(active.values())
        plans: list[SourcePlan] = []

        allocated = 0
        source_list = sorted(active.keys(), key=lambda s: active[s], reverse=True)

        for source in source_list:
            weight = active[source]
            pct = weight / total_weight
            qty = max(self.min_per_source, int(total_quantity * pct))

            # Don't over-allocate
            if allocated + qty > total_quantity:
                qty = total_quantity - allocated
            if qty <= 0:
                continue

            is_ats = source in ATS_REGISTRY
            companies = []
            if is_ats:
                companies = list(ATS_REGISTRY[source].known_companies)

            plans.append(
                SourcePlan(
                    source=source,
                    source_type="ats_api" if is_ats else "mcp",
                    quantity=qty,
                    search_terms=search_terms[:4],
                    companies=companies,
                    weight=weight,
                )
            )
            allocated += qty

        # Distribute any remainder to the highest-weight source
        remainder = total_quantity - allocated
        if remainder > 0 and plans:
            plans[0].quantity += remainder

        return plans

    def _is_legacy_split(self, split: str) -> bool:
        """Check if the split string is a legacy dice/indeed split."""
        return bool(re.match(r"^\d+/\d+$", split))

    def _legacy_allocate(
        self,
        total_quantity: int,
        search_terms: list[SearchTerm],
    ) -> list[SourcePlan]:
        """Original dice/indeed-only allocation for backward compat."""
        split = self.explicit_split or "50/50"
        dice_pct, indeed_pct = map(int, split.split("/"))
        dice_qty = int(total_quantity * dice_pct / 100)
        indeed_qty = total_quantity - dice_qty

        plans = []
        if dice_qty > 0:
            plans.append(
                SourcePlan(
                    source="dice",
                    source_type="mcp",
                    quantity=dice_qty,
                    search_terms=search_terms[:4],
                    weight=dice_pct,
                )
            )
        if indeed_qty > 0:
            plans.append(
                SourcePlan(
                    source="indeed",
                    source_type="mcp",
                    quantity=indeed_qty,
                    search_terms=search_terms[:4],
                    weight=indeed_pct,
                )
            )
        return plans

    def summary(self, plans: list[SourcePlan]) -> str:
        """Human-readable summary of the allocation."""
        lines = [
            f"Source Allocation (priority={self.priority})",
            "-" * 50,
        ]
        total = sum(p.quantity for p in plans)
        for plan in plans:
            pct = (plan.quantity / total * 100) if total else 0
            companies_str = (
                f" ({len(plan.companies)} companies)" if plan.companies else ""
            )
            lines.append(
                f"  {plan.source:18s} [{plan.source_type:7s}] "
                f"{plan.quantity:4d} jobs ({pct:5.1f}%){companies_str}"
            )
        lines.append(f"  {'TOTAL':18s} {'':9s} {total:4d} jobs")
        return "\n".join(lines)


# ───────────────────────────────────────────────────────────────────────────
# Request parsing
# ───────────────────────────────────────────────────────────────────────────


def parse_request(request: str, default_quantity: int = 50) -> RequestParams:
    """
    Parse user request string into parameters.

    Supported formats:
    - "Get 50 jobs for AI/ML Engineer"
    - "Get 50 jobs for AI/ML Engineer, remote, Boston"
    - "Get 100 jobs for AI/ML Engineer, Data Scientist"
    - "Get jobs for AI/ML Engineer" (uses default quantity)
    - "Get 50 contract jobs for DevOps Engineer"          # priority=contract
    - "Get 50 fulltime jobs for Full Stack Engineer"       # priority=fulltime
    - "Get 50 premium jobs for ML Engineer"                # priority=premium
    """
    request = request.strip()

    # Default values
    roles: list[str] = []
    quantity = default_quantity
    timeline = "24hrs"
    location: Optional[str] = None
    visa_status: Optional[str] = None
    visa_required: Optional[bool] = None
    work_mode = "Flexible"
    score_threshold = 50
    source_split = "50/50"
    priority = "diverse"
    employment_type: Optional[str] = None

    # Extract quantity (supports both "10 jobs" and "10jobs")
    quantity_match = re.search(r"(\d+)\s*job", request, re.IGNORECASE)
    if quantity_match:
        quantity = int(quantity_match.group(1))

    # Extract priority / employment type
    priority_match = re.search(
        r"\b(contract|fulltime|full[- ]time|diverse|premium)\b",
        request,
        re.IGNORECASE,
    )
    if priority_match:
        raw = priority_match.group(1).lower().replace("-", "").replace(" ", "")
        if raw in ("contract",):
            priority = "contract"
            employment_type = "contract"
        elif raw in ("fulltime",):
            priority = "fulltime"
            employment_type = "fulltime"
        elif raw == "premium":
            priority = "premium"
        elif raw == "diverse":
            priority = "diverse"

    # Also detect c2h / w2 employment types
    emp_match = re.search(r"\b(c2h|w2|c2c)\b", request, re.IGNORECASE)
    if emp_match:
        employment_type = emp_match.group(1).upper()
        if not priority_match:
            priority = "contract"  # c2h/w2/c2c implies contract priority

    # Extract roles (after "for" keyword)
    role_match = re.search(r"for\s+([^,]+)", request, re.IGNORECASE)
    if role_match:
        role_str = role_match.group(1).strip()
        # Remove any priority words that leaked into the role string
        for word in ["contract", "fulltime", "full-time", "diverse", "premium"]:
            role_str = re.sub(rf"\b{word}\b", "", role_str, flags=re.IGNORECASE)
        role_str = role_str.strip()
        # Handle multiple roles separated by comma or " and "
        # NOTE: Do NOT split on "/" — role names like "AI/ML Engineer" use it.
        roles = [r.strip() for r in re.split(r",|\band\b", role_str) if r.strip()]

    # Extract timeline
    timeline_match = re.search(r"(\d+)\s*(hr|hour|day|week)s?", request, re.IGNORECASE)
    if timeline_match:
        num = timeline_match.group(1)
        unit = timeline_match.group(2).lower()
        if unit.startswith("hr") or unit.startswith("hour"):
            timeline = f"{num}hrs"
        elif unit.startswith("day"):
            timeline = f"{num}days"
        elif unit.startswith("week"):
            timeline = f"{num}weeks"

    # Extract location
    location_match = re.search(r",\s*([A-Za-z]+(?:\s+[A-Za-z]+)?)(?:,|$)", request)
    if location_match:
        potential = location_match.group(1).strip()
        if potential.lower() not in ["remote", "hybrid", "onsite"]:
            location = potential

    # Extract work mode
    work_mode_match = re.search(r"\b(remote|hybrid|onsite)\b", request, re.IGNORECASE)
    if work_mode_match:
        work_mode = work_mode_match.group(1).capitalize()

    # Extract score threshold
    score_match = re.search(r"score\s*[<>]?\s*(\d+)%?", request, re.IGNORECASE)
    if score_match:
        score_threshold = int(score_match.group(1))

    # Extract explicit source split (legacy)
    split_match = re.search(r"(\d+)/(\d+)\s*(dice|indeed)", request, re.IGNORECASE)
    if split_match:
        dice_pct = int(split_match.group(1))
        source_split = f"{dice_pct}/{100 - dice_pct}"

    return RequestParams(
        roles=roles,
        quantity=quantity,
        timeline=timeline,
        location=location,
        visa_status=visa_status,
        visa_required=visa_required,
        work_mode=work_mode,
        score_threshold=score_threshold,
        source_split=source_split,
        priority=priority,
        employment_type=employment_type,
    )


# ───────────────────────────────────────────────────────────────────────────
# Distribution plan
# ───────────────────────────────────────────────────────────────────────────


def create_distribution_plan(
    request_params: RequestParams,
    role_search_terms: dict[str, list[SearchTerm]],
    source_split: Optional[str] = None,
) -> list[RolePlan]:
    """
    Create job distribution plan for all roles.

    Uses SourceAllocator for dynamic allocation across MCP + ATS sources
    when no explicit source_split is given. Falls back to legacy dice/indeed
    split when the user specifies "60/40" etc.

    Args:
        request_params: Parsed request parameters
        role_search_terms: Dict mapping role -> list of SearchTerms
        source_split: Override source split (e.g., "50/50", "60/40").
                      If set, forces legacy dice/indeed-only mode.

    Returns:
        List of RolePlan
    """
    # Determine if we're in legacy mode or dynamic mode
    explicit_split = source_split or (
        request_params.source_split if request_params.source_split != "50/50" else None
    )

    # If user explicitly set a split AND no priority override, use legacy
    # If user set a priority, use dynamic allocation
    use_dynamic = (
        request_params.priority != "diverse"
        or explicit_split is None
        or bool(ATS_REGISTRY)
    )

    allocator = SourceAllocator(
        priority=request_params.priority,
        explicit_split=explicit_split if not use_dynamic else None,
    )

    plans: list[RolePlan] = []
    roles = request_params.roles

    if len(roles) == 1:
        role = roles[0]
        terms = role_search_terms.get(role, [])
        source_plans = allocator.allocate(request_params.quantity, terms)

        plans.append(
            RolePlan(
                role=role,
                quantity=request_params.quantity,
                sources=source_plans,
            )
        )
    else:
        # Multiple roles — split quantity evenly
        qty_per_role = request_params.quantity // len(roles)
        remainder = request_params.quantity % len(roles)

        for i, role in enumerate(roles):
            role_qty = qty_per_role + (1 if i < remainder else 0)
            terms = role_search_terms.get(role, [])
            source_plans = allocator.allocate(role_qty, terms)

            plans.append(
                RolePlan(
                    role=role,
                    quantity=role_qty,
                    sources=source_plans,
                )
            )

    return plans


# ───────────────────────────────────────────────────────────────────────────
# Search term loading / filtering (unchanged)
# ───────────────────────────────────────────────────────────────────────────


def load_search_terms(searchterms_path: str) -> list[SearchTerm]:
    """
    Load search terms from searchterms.md file.

    Returns:
        List of SearchTerm sorted by priority (Set 2 + 3 first, then Set 1)
    """
    path = Path(searchterms_path)
    if not path.exists():
        return []

    content = path.read_text()
    terms: list[SearchTerm] = []

    # Parse Broad (Set 1)
    set1_match = re.search(
        r"## Broad.*?(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE
    )
    if set1_match:
        for line in set1_match.group(0).split("\n"):
            line = line.strip().lstrip("-").strip()
            if line and not line.startswith("#"):
                terms.append(SearchTerm(term=line, set_number=1, priority=3))

    # Parse Medium (Set 2)
    set2_match = re.search(
        r"## Medium.*?(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE
    )
    if set2_match:
        for line in set2_match.group(0).split("\n"):
            line = line.strip().lstrip("-").strip()
            if line and not line.startswith("#"):
                terms.append(SearchTerm(term=line, set_number=2, priority=1))

    # Parse Narrow (Set 3)
    set3_match = re.search(
        r"## Narrow.*?(?=\n##|\Z)", content, re.DOTALL | re.IGNORECASE
    )
    if set3_match:
        for line in set3_match.group(0).split("\n"):
            line = line.strip().lstrip("-").strip()
            if line and not line.startswith("#"):
                terms.append(SearchTerm(term=line, set_number=3, priority=2))

    # Sort by priority (lower = higher priority)
    terms.sort(key=lambda x: x.priority)

    return terms


def filter_search_terms(
    terms: list[SearchTerm], work_mode: str, location: str
) -> list[SearchTerm]:
    """
    Filter search terms based on user preferences.

    If user specifies "remote", prioritize terms containing "remote".
    """
    if work_mode.lower() == "remote":
        remote_terms = [t for t in terms if "remote" in t.term.lower()]
        if remote_terms:
            return remote_terms[:4]

    if location and location.lower() != "remote":
        location_terms = [t for t in terms if location.lower() in t.term.lower()]
        if location_terms:
            return location_terms[:4] + terms[:2]  # Mix of location + general

    return terms[:4]


# ───────────────────────────────────────────────────────────────────────────
# CLI test
# ───────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_requests = [
        "Get 50 jobs for AI/ML Engineer",
        "Get 50 jobs for AI/ML Engineer, remote, Boston",
        "Get 100 jobs for AI/ML Engineer, Data Scientist",
        "Get jobs for AI/ML Engineer, score > 70%",
        "Get 50 contract jobs for DevOps Engineer",
        "Get 80 fulltime jobs for Full Stack Engineer",
        "Get 30 premium jobs for ML Engineer",
        "Get 50 c2h jobs for Java Developer",
    ]

    for req in test_requests:
        params = parse_request(req)
        print(f"\nRequest: {req}")
        print(f"  Roles: {params.roles}")
        print(f"  Quantity: {params.quantity}")
        print(f"  Priority: {params.priority}")
        print(f"  Employment Type: {params.employment_type}")
        print(f"  Work Mode: {params.work_mode}")
        print(f"  Score Threshold: {params.score_threshold}%")
        print(f"  Source Split: {params.source_split}")

        # Show allocation
        allocator = SourceAllocator(priority=params.priority)
        dummy_terms = [SearchTerm(term="test", set_number=2, priority=1)]
        plans = allocator.allocate(params.quantity, dummy_terms)
        print(allocator.summary(plans))
