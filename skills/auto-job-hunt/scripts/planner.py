#!/usr/bin/env python3
"""Planning module for job distribution and request parsing."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


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


@dataclass
class SearchTerm:
    """Search term with priority."""

    term: str
    set_number: int  # 1, 2, or 3
    priority: int  # lower = higher priority


@dataclass
class SourcePlan:
    """Plan for a single source."""

    source: str  # dice or indeed
    quantity: int
    search_terms: list[SearchTerm]


@dataclass
class RolePlan:
    """Plan for a single role."""

    role: str
    quantity: int
    sources: list[SourcePlan]


def parse_request(request: str, default_quantity: int = 50) -> RequestParams:
    """
    Parse user request string into parameters.

    Supported formats:
    - "Get 50 jobs for AI/ML Engineer"
    - "Get 50 jobs for AI/ML Engineer, remote, Boston"
    - "Get 50 jobs for AI/ML Engineer, Data Scientist"
    - "Get jobs for AI/ML Engineer" (uses default quantity)
    """
    request = request.strip()

    # Default values
    roles = []
    quantity = default_quantity
    timeline = "24hrs"
    location = None
    visa_status = None
    visa_required = None
    work_mode = "Flexible"
    score_threshold = 50
    source_split = "50/50"

    # Extract quantity (supports both "10 jobs" and "10jobs")
    quantity_match = re.search(r"(\d+)\s*job", request, re.IGNORECASE)
    if quantity_match:
        quantity = int(quantity_match.group(1))

    # Extract roles (after "for" keyword)
    role_match = re.search(r"for\s+([^,]+)", request, re.IGNORECASE)
    if role_match:
        role_str = role_match.group(1).strip()
        # Handle multiple roles separated by comma or "and"
        roles = [r.strip() for r in re.split(r"[,/and]+", role_str)]

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

    # Extract source split
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
    )


def create_distribution_plan(
    request_params: RequestParams,
    role_search_terms: dict[str, list[SearchTerm]],
    source_split: Optional[str] = None,
) -> list[RolePlan]:
    """
    Create job distribution plan for all roles.

    Args:
        request_params: Parsed request parameters
        role_search_terms: Dict mapping role -> list of SearchTerms
        source_split: Override source split (e.g., "50/50", "60/40")

    Returns:
        List of RolePlan
    """
    if not source_split:
        source_split = request_params.source_split

    # Parse source split
    dice_pct, indeed_pct = map(int, source_split.split("/"))

    plans = []
    roles = request_params.roles

    if len(roles) == 1:
        # Single role - use full quantity
        role = roles[0]
        dice_qty = int(request_params.quantity * dice_pct / 100)
        indeed_qty = request_params.quantity - dice_qty

        terms = role_search_terms.get(role, [])
        dice_terms = terms[:4]  # max 4 per source
        indeed_terms = terms[:4]

        plans.append(
            RolePlan(
                role=role,
                quantity=request_params.quantity,
                sources=[
                    SourcePlan(
                        source="dice", quantity=dice_qty, search_terms=dice_terms
                    ),
                    SourcePlan(
                        source="indeed", quantity=indeed_qty, search_terms=indeed_terms
                    ),
                ],
            )
        )
    else:
        # Multiple roles - split evenly
        qty_per_role = request_params.quantity // len(roles)
        remainder = request_params.quantity % len(roles)

        for i, role in enumerate(roles):
            role_qty = qty_per_role + (1 if i < remainder else 0)
            dice_qty = int(role_qty * dice_pct / 100)
            indeed_qty = role_qty - dice_qty

            terms = role_search_terms.get(role, [])
            dice_terms = terms[:4]
            indeed_terms = terms[:4]

            plans.append(
                RolePlan(
                    role=role,
                    quantity=role_qty,
                    sources=[
                        SourcePlan(
                            source="dice", quantity=dice_qty, search_terms=dice_terms
                        ),
                        SourcePlan(
                            source="indeed",
                            quantity=indeed_qty,
                            search_terms=indeed_terms,
                        ),
                    ],
                )
            )

    return plans


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
    terms = []

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


if __name__ == "__main__":
    # Test parsing
    test_requests = [
        "Get 50 jobs for AI/ML Engineer",
        "Get 50 jobs for AI/ML Engineer, remote, Boston",
        "Get 100 jobs for AI/ML Engineer, Data Scientist",
        "Get jobs for AI/ML Engineer, score > 70%",
    ]

    for req in test_requests:
        params = parse_request(req)
        print(f"\nRequest: {req}")
        print(f"  Roles: {params.roles}")
        print(f"  Quantity: {params.quantity}")
        print(f"  Work Mode: {params.work_mode}")
        print(f"  Score Threshold: {params.score_threshold}%")
        print(f"  Source Split: {params.source_split}")
