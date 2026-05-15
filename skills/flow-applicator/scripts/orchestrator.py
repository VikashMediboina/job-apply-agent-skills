"""
Orchestrator — main entry point that ties all flow-applicator modules together.

This module provides the high-level functions that the agent calls:

  1. parse_jobs_file()  — Read jobs.md, extract job cards, filter by score
  2. plan_applications() — Dedup check, platform detection, flow matching
  3. apply_to_job()     — Execute a single application using flow graph
  4. run_session()      — Full session: parse → plan → apply → report

The orchestrator does NOT directly interact with the browser.
It produces structured instructions that the agent executes via Playwright MCP.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import paths
import flow_engine
import answer_engine
import dedup_checker
import status_tracker
import flow_builder

# Class aliases for convenience
FlowGraph = flow_engine.FlowGraph
FlowRegistry = flow_engine.FlowRegistry
AnswerEngine = answer_engine.AnswerEngine
AnswerResult = answer_engine.AnswerResult
DedupChecker = dedup_checker.DedupChecker
ApplicationResult = status_tracker.ApplicationResult
StatusTracker = status_tracker.StatusTracker
ParsedPage = flow_builder.ParsedPage
parse_snapshot = flow_builder.parse_snapshot
match_page_to_node = flow_builder.match_page_to_node
detect_deviations = flow_builder.detect_deviations
detect_login_page = flow_builder.detect_login_page
is_dice_wizard_page = flow_builder.is_dice_wizard_page
LoginDetection = flow_builder.LoginDetection


# ── Job Parsing ────────────────────────────────────────────────────


@dataclass
class JobCard:
    """A single job parsed from jobs.md."""

    title: str = ""
    company: str = ""
    location: str = ""
    work_type: str = ""
    source: str = ""
    salary: str = ""
    score: int = 0
    apply_url: str = ""
    job_id: str = ""
    notes: str = ""
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "workType": self.work_type,
            "source": self.source,
            "salary": self.salary,
            "score": self.score,
            "applyUrl": self.apply_url,
            "jobId": self.job_id,
            "notes": self.notes,
        }


def parse_jobs_file(
    jobs_path: Optional[Path] = None, min_score: int = 70
) -> list[JobCard]:
    """Parse a jobs.md file and return job cards filtered by score.

    If no path provided, uses the most recent jobs.md for today.
    """
    if jobs_path is None:
        jobs_path = paths.find_jobs_file()
    if jobs_path is None or not jobs_path.exists():
        return []

    content = jobs_path.read_text(encoding="utf-8")
    jobs = _parse_job_cards(content)

    # Filter by score
    return [j for j in jobs if j.score >= min_score]


def _parse_job_cards(content: str) -> list[JobCard]:
    """Parse job cards from markdown content.

    Supports two formats:

    Format A (auto-job-hunt md_generator.py actual output):
    ```
    - **Job Title**
      - Company: Company Name
      - Location: City, State
      - Work Type: Remote
      - Source: Dice
      - Salary: $120K-$150K
      - Score: 85% | Apply
      - Apply: https://...
      - ID: abc123
      - Notes: ...
    ```

    Format B (legacy/alternative):
    ```
    ### 1. Job Title
    - **Company:** Company Name
    ...
    ```
    """
    jobs = []

    # Detect which format we're dealing with
    if re.search(r"^- \*\*[^*]+\*\*\s*$", content, re.MULTILINE):
        jobs = _parse_format_a(content)
    elif re.search(r"^###\s+\d+\.\s+", content, re.MULTILINE):
        jobs = _parse_format_b(content)
    elif re.search(r"^###\s+.+$", content, re.MULTILINE) and "|" in content:
        # Table-style format with company headings and markdown tables
        jobs = _parse_table_format(content)
    else:
        # Try known parsers in order
        jobs = (
            _parse_format_a(content)
            or _parse_format_b(content)
            or _parse_table_format(content)
        )

    return jobs


def _parse_format_a(content: str) -> list[JobCard]:
    """Parse Format A: bullet-title with indented sub-bullets.

    ```
    - **Job Title**
      - Company: Value
      - Score: 85% | Apply
      - Apply: https://...
    ```
    """
    jobs = []
    # Split on top-level job entries: "- **Title**"
    sections = re.split(r"^(?=- \*\*[^*]+\*\*)", content, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        # Extract title from "- **Title**"
        title_m = re.match(r"^- \*\*(.+?)\*\*", section)
        if not title_m:
            continue

        job = JobCard(raw_text=section)
        job.title = title_m.group(1).strip()

        # Parse indented sub-bullets: "  - Key: Value"
        for line in section.splitlines()[1:]:
            stripped = line.strip()
            m = re.match(r"^-\s+(.+?):\s*(.+)$", stripped)
            if not m:
                continue
            key = m.group(1).lower().strip()
            value = m.group(2).strip()

            if key == "company":
                job.company = value
            elif key == "location":
                job.location = value
            elif key in ("work type", "work_type", "type"):
                job.work_type = value
            elif key == "source":
                job.source = value
            elif key == "salary":
                job.salary = value
            elif key == "score":
                # Parse "85% | Apply" or "85%"
                score_m = re.search(r"(\d+)", value)
                if score_m:
                    job.score = int(score_m.group(1))
            elif key == "apply":
                # Plain URL or markdown link
                url_m = re.search(r"\((.+?)\)", value)
                if url_m:
                    job.apply_url = url_m.group(1)
                elif value.startswith("http"):
                    job.apply_url = value
            elif key == "id":
                job.job_id = value
            elif key == "notes":
                job.notes = value

        if job.title:
            jobs.append(job)

    return jobs


def _parse_format_b(content: str) -> list[JobCard]:
    """Parse Format B: numbered heading with bold-key bullets.

    ```
    ### 1. Job Title
    - **Company:** Company Name
    ...
    ```
    """
    jobs = []
    sections = re.split(r"^###\s+\d+\.\s+", content, flags=re.MULTILINE)

    for section in sections[1:]:  # Skip header before first ###
        job = JobCard(raw_text=section)

        lines = section.strip().splitlines()
        if lines:
            job.title = lines[0].strip()

        for line in lines:
            line = line.strip()
            m = re.match(r"^-\s+\*\*(.+?):\*\*\s*(.+)$", line)
            if not m:
                continue
            key = m.group(1).lower().strip()
            value = m.group(2).strip()

            if key == "company":
                job.company = value
            elif key == "location":
                job.location = value
            elif key in ("work type", "work_type", "type"):
                job.work_type = value
            elif key == "source":
                job.source = value
            elif key == "salary":
                job.salary = value
            elif key == "score":
                score_m = re.search(r"(\d+)", value)
                if score_m:
                    job.score = int(score_m.group(1))
            elif key == "apply":
                url_m = re.search(r"\((.+?)\)", value)
                if url_m:
                    job.apply_url = url_m.group(1)
                elif value.startswith("http"):
                    job.apply_url = value
            elif key == "id":
                job.job_id = value
            elif key == "notes":
                job.notes = value

        if job.title:
            jobs.append(job)

    return jobs


def _parse_table_format(content: str) -> list[JobCard]:
    """Parse table-style jobs.md where companies are headings (### Company)

    Example section:
    ### Anthropic (AI/ML Company)

    | # | Title | Location | Work Type | URL |
    |---|-------|-----------|---------|-----|
    | 1 | Applied AI Engineer (Startups) | SF/NYC | Hybrid | https://... |
    """
    jobs: list[JobCard] = []
    current_company = ""
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Company heading
        m = re.match(r"^###\s+(.+)$", line)
        if m:
            # Use the heading text as company name (strip parenthetical)
            heading = m.group(1).strip()
            # Keep only the main company name before any parentheses or hyphen
            current_company = re.split(r"\s*\(|\s*-\s*", heading)[0].strip()
            i += 1
            continue

        # Table header detection (must contain 'URL' and 'Title')
        if line.startswith("|") and "url" in line.lower() and "title" in line.lower():
            # Parse header cells to discover column indices
            header_cells = [
                c.strip().lower() for c in line.strip().strip("|").split("|")
            ]
            # build mapping
            mapping = {}
            for idx, name in enumerate(header_cells):
                if "title" in name:
                    mapping["title"] = idx
                elif "location" in name:
                    mapping["location"] = idx
                elif "work type" in name or "work_type" in name or "work type" in name:
                    mapping["work_type"] = idx
                elif "url" in name:
                    mapping["url"] = idx
                elif name.strip().startswith("#"):
                    mapping["index"] = idx

            # skip the separator line if present
            i += 1
            # consume table rows
            while i < len(lines):
                row = lines[i].strip()
                if not row.startswith("|"):
                    break
                # ignore divider lines like |---|
                if re.match(r"^\|\s*-+", row):
                    i += 1
                    continue
                cells = [c.strip() for c in row.strip().strip("|").split("|")]
                # ensure url exists in cells
                url = ""
                if "url" in mapping and mapping["url"] < len(cells):
                    url = cells[mapping["url"]]
                # sometimes URL is the last cell and may not be labeled; try to find http
                if not url or not url.startswith("http"):
                    for c in cells:
                        if c.startswith("http"):
                            url = c
                            break

                if url:
                    title = (
                        cells[mapping.get("title", 1)]
                        if mapping.get("title", 1) < len(cells)
                        else ""
                    )
                    location = (
                        cells[mapping.get("location", 2)]
                        if mapping.get("location", 2) < len(cells)
                        else ""
                    )
                    work_type = (
                        cells[mapping.get("work_type", 3)]
                        if mapping.get("work_type", 3) < len(cells)
                        else ""
                    )
                    job = JobCard(
                        title=title,
                        company=current_company,
                        location=location,
                        work_type=work_type,
                        apply_url=url,
                        score=100,
                        raw_text=row,
                    )
                    jobs.append(job)
                i += 1
            continue

        i += 1

    return jobs


# ── Application Planning ───────────────────────────────────────────


@dataclass
class ApplicationPlan:
    """Plan for a single job application."""

    job: JobCard
    platform: str = ""
    flow_id: str = ""
    flow: Optional[FlowGraph] = None
    is_duplicate: bool = False
    duplicate_reason: str = ""
    skip_reason: str = ""
    priority: int = 0  # Higher = apply first

    @property
    def should_apply(self) -> bool:
        """A job should be applied to if it's not a duplicate, has no skip reason,
        and either has a flow loaded OR is a dice/dice_redirect (flow loaded after navigation)."""
        if self.is_duplicate or self.skip_reason:
            return False
        return self.flow is not None or self.platform in ("dice_redirect", "dice")

    def to_dict(self) -> dict:
        return {
            "job": self.job.to_dict(),
            "platform": self.platform,
            "flowId": self.flow_id,
            "isDuplicate": self.is_duplicate,
            "duplicateReason": self.duplicate_reason,
            "skipReason": self.skip_reason,
            "shouldApply": self.should_apply,
            "priority": self.priority,
        }


def plan_applications(
    jobs: list[JobCard],
    registry: Optional[FlowRegistry] = None,
    dedup: Optional[DedupChecker] = None,
) -> list[ApplicationPlan]:
    """Create application plans for a list of jobs.

    For each job:
      1. Check dedup (skip if already applied)
      2. Detect platform from URL
      3. Load the matching flow graph
      4. Assign priority (higher score = higher priority)
    """
    if registry is None:
        registry = FlowRegistry()
    if dedup is None:
        dedup = DedupChecker()

    plans = []
    for job in jobs:
        plan = ApplicationPlan(job=job, priority=job.score)

        # Dedup check
        is_dup, existing = dedup.is_duplicate(
            job_id=job.job_id,
            url=job.apply_url,
            company=job.company,
            title=job.title,
        )
        if is_dup:
            plan.is_duplicate = True
            plan.duplicate_reason = (
                f"Already applied: {existing.status} on {existing.applied_at}"
                if existing
                else "Duplicate detected"
            )
            plans.append(plan)
            continue

        # Platform detection
        platform = registry.detect_platform(job.apply_url)
        if platform:
            plan.platform = platform
            flow_id = registry.get_flow_id(platform)
            if flow_id:
                plan.flow_id = flow_id
                plan.flow = FlowGraph.load(flow_id)

        # If all apply URLs are Dice redirects, we won't know the real platform
        # until we navigate. Mark as "dice_redirect" for the agent to handle.
        if not platform and "dice.com" in job.apply_url:
            plan.platform = "dice_redirect"
            # Agent will navigate, detect real platform, then load flow

        # No flow and not a redirect → skip
        if not plan.flow and plan.platform != "dice_redirect":
            plan.skip_reason = f"No flow available for URL: {job.apply_url}"

        plans.append(plan)

    # Sort by priority (highest score first), duplicates/skips last
    plans.sort(key=lambda p: (p.should_apply, p.priority), reverse=True)
    return plans


# ── Login Handling ─────────────────────────────────────────────────


@dataclass
class LoginState:
    """Tracks login state per platform during a session."""

    platform: str
    logged_in: bool = False
    login_attempted: bool = False
    user_skipped: bool = False  # User chose not to log in
    skipped_jobs: list[str] = field(default_factory=list)


class SessionLoginTracker:
    """Track login states across platforms during a session.

    When a login is required:
      1. Agent pauses and asks user to log in manually
      2. If user logs in → mark platform as logged_in
      3. If user skips → mark as skipped, skip ALL jobs for that platform
    """

    def __init__(self):
        self._states: dict[str, LoginState] = {}

    def get_state(self, platform: str) -> LoginState:
        if platform not in self._states:
            self._states[platform] = LoginState(platform=platform)
        return self._states[platform]

    def is_logged_in(self, platform: str) -> bool:
        return self._states.get(platform, LoginState(platform=platform)).logged_in

    def is_skipped(self, platform: str) -> bool:
        return self._states.get(platform, LoginState(platform=platform)).user_skipped

    def mark_logged_in(self, platform: str) -> None:
        state = self.get_state(platform)
        state.logged_in = True
        state.login_attempted = True

    def mark_skipped(self, platform: str) -> None:
        state = self.get_state(platform)
        state.user_skipped = True
        state.login_attempted = True

    def add_skipped_job(self, platform: str, job_id: str) -> None:
        state = self.get_state(platform)
        state.skipped_jobs.append(job_id)


def handle_login_page(
    ctx: ApplicationContext,
    snapshot_text: str,
    url: str,
    login_tracker: Optional[SessionLoginTracker] = None,
) -> dict:
    """Handle a detected login page during application.

    Returns a dict with:
      - type: "login_required" | "already_logged_in" | "platform_skipped"
      - platform: the platform requiring login
      - message: human-readable message for the agent to show
      - redirect_url: where login should redirect to
      - action: what the agent should do next

    The agent should:
      1. Show the message to the user
      2. Wait for user to log in manually (or skip)
      3. Call handle_login_complete() after user action
    """
    detection = detect_login_page(snapshot_text, url)

    if not detection.is_login_page:
        return {
            "type": "not_login",
            "platform": "",
            "message": "Page is not a login page",
            "action": "continue",
        }

    platform = _login_source_key(detection, ctx, url)

    # Check if user already skipped this platform
    if login_tracker and login_tracker.is_skipped(platform):
        if login_tracker:
            login_tracker.add_skipped_job(platform, ctx.plan.job.job_id)
        return {
            "type": "platform_skipped",
            "platform": platform,
            "message": f"User previously skipped login for {platform}. Skipping this job.",
            "action": "skip_job",
        }

    # Check if already logged in (shouldn't see login page then, but handle edge case)
    if login_tracker and login_tracker.is_logged_in(platform):
        return {
            "type": "already_logged_in",
            "platform": platform,
            "message": f"Already logged into {platform} but seeing login page. Session may have expired.",
            "action": "request_login",
            "redirect_url": detection.redirect_url,
        }

    return {
        "type": "login_required",
        "platform": platform,
        "message": (
            "Login required for this source category. "
            "Please log in manually in the browser, then click Yes to continue. "
            "If you skip, all jobs from this source category will be skipped."
        ),
        "action": "request_login",
        "redirect_url": detection.redirect_url,
        "indicators": detection.indicators,
    }


def handle_login_complete(
    platform: str,
    user_logged_in: bool,
    login_tracker: SessionLoginTracker,
) -> dict:
    """Called after the user responds to a login request.

    Args:
        platform: Platform that required login
        user_logged_in: True if user logged in, False if they skipped
        login_tracker: Session login tracker

    Returns action dict for the agent.
    """
    if user_logged_in:
        login_tracker.mark_logged_in(platform)
        return {
            "type": "login_success",
            "platform": platform,
            "message": f"Logged into {platform}. Continuing applications.",
            "action": "continue",
        }
    else:
        login_tracker.mark_skipped(platform)
        return {
            "type": "login_skipped",
            "platform": platform,
            "message": f"Skipped login for {platform}. All jobs from this source category will be skipped.",
            "action": "skip_platform",
        }


# ── Dice-Specific Processing ──────────────────────────────────────


def process_dice_page(
    ctx: ApplicationContext,
    snapshot_text: str,
    url: str = "",
    login_tracker: Optional[SessionLoginTracker] = None,
) -> list[dict]:
    """Process a Dice apply wizard page and return actions.

    Dice's flow is simple — no form fields to fill:
      Step 1: Resume pre-loaded → click "Next"
      Step 2: Review → click "Submit"

    This function is optimized for Dice and avoids the overhead of
    the generic process_page() field resolution since Dice has no fields.
    """
    actions: list[dict] = []

    # First check for login gate and delegate to generic login handling.
    login = detect_login_page(snapshot_text, url)
    if login.is_login_page:
        return [handle_login_page(ctx, snapshot_text, url, login_tracker)]

    # Check if this is a wizard page
    wizard = is_dice_wizard_page(snapshot_text, url)
    if not wizard["is_wizard"]:
        # Might be the job detail page — look for Apply Now button
        page = parse_snapshot(snapshot_text, url)
        for btn in page.buttons:
            btn_class = btn.classify()
            if (
                btn_class in ("apply", "submit")
                and "dice.com/job-detail" in url.lower()
            ):
                actions.append(
                    {
                        "type": "click",
                        "ref": btn.ref,
                        "name": btn.text,
                        "purpose": "apply",
                        "note": "Click Apply Now to start Dice wizard",
                    }
                )
                return actions

        # Unknown page state
        actions.append(
            {
                "type": "unknown_page",
                "url": url,
                "message": "Not a recognized Dice page. Check the URL and try again.",
            }
        )
        return actions

    # Dice wizard step
    if wizard["step"] == 1:
        # Step 1: Resume & Cover Letter → just click Next
        if ctx.result:
            ctx.result.nodes_visited.append("step1_resume")
        ctx.current_node_id = "step1_resume"

        actions.append(
            {
                "type": "click",
                "ref": wizard["button_ref"],
                "name": "Next",
                "purpose": "next",
                "note": "Resume is pre-loaded from Dice profile. Skipping cover letter. Click Next.",
            }
        )

    elif wizard["step"] == 2:
        # Step 2: Review → click Submit
        if ctx.result:
            ctx.result.nodes_visited.append("step2_review")
        ctx.current_node_id = "step2_review"

        actions.append(
            {
                "type": "click",
                "ref": wizard["button_ref"],
                "name": "Submit",
                "purpose": "submit",
                "note": "Review page shows pre-filled data. Click Submit to complete application.",
            }
        )

    else:
        # Could be a redirect/loading state
        actions.append(
            {
                "type": "wait",
                "seconds": 2,
                "message": f"Dice wizard step not detected. Step label: {wizard.get('step_label', 'unknown')}",
            }
        )

    return actions


def get_dice_apply_url(job_url: str) -> str:
    """Extract the Dice apply URL from a job detail URL.

    Input:  https://www.dice.com/job-detail/abc-123-def
    Output: https://www.dice.com/job-applications/abc-123-def/start-apply
    """
    # Extract job ID from dice.com/job-detail/{id}
    m = re.search(r"dice\.com/job-detail/([a-zA-Z0-9-]+)", job_url)
    if m:
        job_id = m.group(1)
        return f"https://www.dice.com/job-applications/{job_id}/start-apply"
    return job_url


# ── Page Processing (updated) ─────────────────────────────────────


def process_page_with_login(
    ctx: ApplicationContext,
    snapshot_text: str,
    url: str = "",
    login_tracker: Optional[SessionLoginTracker] = None,
) -> list[dict]:
    """Process a browser page with login detection.

    This wraps process_page() and process_dice_page() with a login
    gate check. Use this instead of process_page() directly.

    Flow:
      1. Check if page is a login gate → return login_required action
      2. If Dice platform → use process_dice_page() (optimized)
      3. Otherwise → use process_page() (generic)
    """
    # Step 1: Login detection
    login = detect_login_page(snapshot_text, url)
    if login.is_login_page:
        result = handle_login_page(ctx, snapshot_text, url, login_tracker)
        if result["action"] in ("request_login", "skip_job", "skip_platform"):
            return [result]

    # Step 2: Platform-specific processing
    platform = ctx.plan.platform
    if platform in ("dice", "dice_redirect"):
        return process_dice_page(ctx, snapshot_text, url, login_tracker)

    # Step 3: Generic processing
    return process_page(ctx, snapshot_text, url)


def _login_source_key(
    detection: LoginDetection, ctx: ApplicationContext, url: str
) -> str:
    """Resolve a stable source category for login tracking."""
    if detection.platform:
        return detection.platform
    if ctx.plan.platform and ctx.plan.platform != "dice_redirect":
        return ctx.plan.platform

    if url:
        m = re.search(r"https?://([^/?#]+)", url, re.IGNORECASE)
        if m:
            host = m.group(1).lower()
            if host.startswith("www."):
                host = host[4:]
            return host

    return "unknown"


# ── Application Execution Context ─────────────────────────────────


@dataclass
class ApplicationContext:
    """Runtime context for executing a single job application.

    This is passed between the orchestrator and the agent during
    the application loop. It tracks the current state, fields to fill,
    and decisions made.
    """

    plan: ApplicationPlan
    result: Optional[ApplicationResult] = None
    answer_engine: Optional[AnswerEngine] = None
    current_node_id: str = ""
    current_page: Optional[ParsedPage] = None
    fields_to_fill: list[dict] = field(default_factory=list)
    questions_to_answer: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)  # Ordered actions for the agent

    def add_action(self, action_type: str, **kwargs) -> None:
        """Queue an action for the agent to execute."""
        self.actions.append({"type": action_type, **kwargs})


def prepare_application(
    plan: ApplicationPlan,
    tracker: StatusTracker,
    candidate: Optional[str] = None,
    role: Optional[str] = None,
) -> ApplicationContext:
    """Prepare the context for executing an application.

    Returns an ApplicationContext with the flow loaded and answer engine ready.
    """
    # Auto-detect candidate/role if not provided
    if candidate is None:
        candidate = paths.candidate_dir().name
    if role is None:
        role = paths.role_dir(candidate).name

    ctx = ApplicationContext(plan=plan)
    ctx.answer_engine = AnswerEngine(candidate=candidate, role=role)

    # Start tracking
    ctx.result = tracker.start_application(
        job_id=plan.job.job_id,
        job_title=plan.job.title,
        company=plan.job.company,
        url=plan.job.apply_url,
        apply_url=plan.job.apply_url,
        score=plan.job.score,
        source=plan.job.source,
        platform=plan.platform,
        flow_id=plan.flow_id,
        flow_version=plan.flow.version if plan.flow else "",
    )

    return ctx


def resolve_dice_redirect(
    ctx: ApplicationContext,
    final_url: str,
    registry: Optional[FlowRegistry] = None,
) -> dict:
    """After navigating to a Dice URL, resolve the real ATS platform.

    The agent should:
      1. Navigate to the Dice apply URL
      2. Wait for redirect to complete (page loads)
      3. Get the final URL from the browser
      4. Call this function with the final URL

    Returns a dict with:
      - platform: detected ATS platform name
      - flowId: the flow ID to use
      - flowLoaded: whether a flow was successfully loaded
      - actions: initial actions (navigate to apply page, etc.)
      - error: error message if platform not recognized

    Common redirect patterns:
      dice.com → greenhouse.io, lever.co, workday.com, icims.com,
                 jobvite.com, myworkdayjobs.com, smartrecruiters.com,
                 direct company career pages
    """
    if registry is None:
        registry = FlowRegistry()

    result = {
        "platform": "",
        "flowId": "",
        "flowLoaded": False,
        "originalUrl": ctx.plan.job.apply_url,
        "finalUrl": final_url,
        "actions": [],
        "error": "",
    }

    # Detect platform from the final URL
    platform = registry.detect_platform(final_url)
    if platform:
        result["platform"] = platform
        ctx.plan.platform = platform

        flow_id = registry.get_flow_id(platform)
        if flow_id:
            result["flowId"] = flow_id
            ctx.plan.flow_id = flow_id
            flow = FlowGraph.load(flow_id)
            if flow:
                ctx.plan.flow = flow
                result["flowLoaded"] = True
            else:
                result["error"] = f"Flow file for '{flow_id}' not found or invalid"
        else:
            result["error"] = f"Platform '{platform}' recognized but no flow registered"
    else:
        # Unknown platform — agent needs to use flow_discoverer prompt
        result["platform"] = "unknown"
        ctx.plan.platform = "unknown"
        result["error"] = (
            f"Unknown ATS platform at {final_url}. "
            "Use the flow_discoverer prompt to analyze the page and build a new flow."
        )

    # Update tracker
    if ctx.result:
        ctx.result.platform = result["platform"]
        ctx.result.flow_id = result.get("flowId", "")

    return result


def process_page(
    ctx: ApplicationContext, snapshot_text: str, url: str = ""
) -> list[dict]:
    """Process a browser snapshot and produce actions for the agent.

    This is the core loop step:
      1. Parse the snapshot
      2. Match to a flow node
      3. Resolve all fields/questions
      4. Return ordered actions (fill, click, upload, etc.)

    Returns a list of action dicts the agent should execute.
    """
    flow = ctx.plan.flow
    page = parse_snapshot(snapshot_text, url=url)
    ctx.current_page = page
    actions: list[dict] = []

    # Match page to flow node
    if flow:
        matched_node, confidence = match_page_to_node(page, flow, ctx.current_node_id)
        if matched_node:
            ctx.current_node_id = matched_node.id
            if ctx.result:
                ctx.result.nodes_visited.append(matched_node.id)

            # Detect deviations
            devs = detect_deviations(page, matched_node, flow)
            if devs and ctx.result:
                from .status_tracker import DeviationLog

                for d in devs:
                    ctx.result.deviations.append(
                        DeviationLog(
                            node_id=matched_node.id,
                            deviation_type=d["type"],
                            description=d["description"],
                            resolution="pending",
                        )
                    )

    # Resolve fields
    for pf in page.fields:
        if ctx.answer_engine:
            result = ctx.answer_engine.get_field_value(pf.name, flow_graph=flow)
            if result.found:
                if pf.field_type == "textbox":
                    actions.append(
                        {
                            "type": "fill",
                            "ref": pf.ref,
                            "name": pf.name,
                            "value": result.answer,
                            "source": result.source,
                        }
                    )
                elif pf.field_type == "combobox":
                    actions.append(
                        {
                            "type": "select",
                            "ref": pf.ref,
                            "name": pf.name,
                            "value": result.answer,
                            "options": pf.options,
                            "source": result.source,
                        }
                    )
                elif pf.field_type in ("checkbox", "radio"):
                    actions.append(
                        {
                            "type": "check",
                            "ref": pf.ref,
                            "name": pf.name,
                            "value": result.answer,
                            "source": result.source,
                        }
                    )
            else:
                actions.append(
                    {
                        "type": "need_answer",
                        "ref": pf.ref,
                        "name": pf.name,
                        "fieldType": pf.field_type,
                        "options": pf.options,
                    }
                )

    # Resolve questions
    for q in page.questions:
        if ctx.answer_engine:
            result = ctx.answer_engine.resolve(q.text, flow_graph=flow)
            if result.found:
                actions.append(
                    {
                        "type": "answer_question",
                        "question": q.text,
                        "answer": result.answer,
                        "fieldRef": q.field_ref,
                        "source": result.source,
                        "confidence": result.confidence,
                    }
                )
            else:
                actions.append(
                    {
                        "type": "need_answer",
                        "question": q.text,
                        "fieldRef": q.field_ref,
                        "fieldType": q.question_type,
                    }
                )

    # File upload
    if page.has_file_upload:
        resume_path = paths.resume_pdf_path()
        if resume_path.exists():
            upload_btn = page.get_upload_button()
            if upload_btn:
                actions.append(
                    {
                        "type": "upload",
                        "ref": upload_btn.ref,
                        "filePath": str(resume_path),
                        "fileName": "resume.pdf",
                    }
                )

    # Navigation button
    next_btn = page.get_next_button()
    submit_btn = page.get_submit_button()
    if submit_btn:
        actions.append(
            {
                "type": "click",
                "ref": submit_btn.ref,
                "name": submit_btn.text,
                "purpose": "submit",
            }
        )
    elif next_btn:
        actions.append(
            {
                "type": "click",
                "ref": next_btn.ref,
                "name": next_btn.text,
                "purpose": "next",
            }
        )

    ctx.actions = actions
    return actions


# ── Session Runner ─────────────────────────────────────────────────


@dataclass
class SessionState:
    """Mutable state for a running application session.

    This tracks progress across multiple jobs, maintains shared state
    (login tracker, dedup, status tracker), and provides the agent
    with the next action to execute at each step.

    Lifecycle:
      1. Agent calls run_session() to get a SessionState
      2. Agent calls next_job() to get the next ApplicationContext
      3. For each job, agent loops: navigate → snapshot → step() → execute → repeat
      4. Agent calls complete_job() or fail_job() when done
      5. Agent calls finish_session() at the end
    """

    plans: list[ApplicationPlan] = field(default_factory=list)
    tracker: StatusTracker = field(default_factory=StatusTracker)
    dedup: DedupChecker = field(default_factory=DedupChecker)
    login_tracker: SessionLoginTracker = field(default_factory=SessionLoginTracker)
    registry: FlowRegistry = field(default_factory=FlowRegistry)

    # Progress tracking
    current_index: int = 0
    current_ctx: Optional[ApplicationContext] = None
    completed: list[dict] = field(default_factory=list)
    failed: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    # Config
    candidate: Optional[str] = None
    role: Optional[str] = None
    max_applications: int = 10

    def __post_init__(self):
        # Auto-detect candidate/role if not provided
        if self.candidate is None:
            self.candidate = paths.candidate_dir().name
        if self.role is None:
            self.role = paths.role_dir(self.candidate).name

    @property
    def remaining(self) -> int:
        return len(self.plans) - self.current_index

    @property
    def total_applied(self) -> int:
        return len(self.completed)

    @property
    def is_done(self) -> bool:
        return self.current_index >= len(self.plans)

    def summary(self) -> dict:
        """Current session progress summary."""
        return {
            "total_planned": len(self.plans),
            "completed": len(self.completed),
            "failed": len(self.failed),
            "skipped": len(self.skipped),
            "remaining": self.remaining,
            "current_index": self.current_index,
            "is_done": self.is_done,
            "completed_jobs": [
                {"title": c["title"], "company": c["company"], "status": c["status"]}
                for c in self.completed
            ],
            "failed_jobs": [
                {
                    "title": f["title"],
                    "company": f["company"],
                    "error": f.get("error", ""),
                }
                for f in self.failed
            ],
            "skipped_jobs": [
                {
                    "title": s["title"],
                    "company": s["company"],
                    "reason": s.get("reason", ""),
                }
                for s in self.skipped
            ],
        }


def run_session(
    jobs_path: Optional[Path] = None,
    min_score: int = 70,
    max_applications: int = 10,
    candidate: Optional[str] = None,
    role: Optional[str] = None,
) -> SessionState:
    """Initialize a full application session.

    Returns a SessionState that the agent uses to drive the loop:

        session = run_session(jobs_path, max_applications=5)
        while not session.is_done:
            ctx = next_job(session)
            if ctx is None:
                break
            # Agent navigates to ctx.plan.job.apply_url
            # Agent takes snapshot, calls step(session, snapshot, url)
            # Agent executes returned actions
            # Agent calls complete_job(session) or fail_job(session, error)
        summary = finish_session(session)
    """
    # Auto-detect candidate/role if not provided
    if candidate is None:
        candidate = paths.candidate_dir().name
    if role is None:
        role = paths.role_dir(candidate).name

    registry = FlowRegistry()
    dedup = DedupChecker()
    tracker = StatusTracker()

    # Parse and plan
    jobs = parse_jobs_file(jobs_path, min_score=min_score)
    if not jobs:
        return SessionState(
            tracker=tracker,
            dedup=dedup,
            registry=registry,
            login_tracker=SessionLoginTracker(),
            candidate=candidate,
            role=role,
            max_applications=max_applications,
        )

    plans = plan_applications(jobs, registry=registry, dedup=dedup)
    apply_plans = [p for p in plans if p.should_apply][:max_applications]

    return SessionState(
        plans=apply_plans,
        tracker=tracker,
        dedup=dedup,
        registry=registry,
        login_tracker=SessionLoginTracker(),
        candidate=candidate,
        role=role,
        max_applications=max_applications,
    )


def next_job(session: SessionState) -> Optional[ApplicationContext]:
    """Advance to the next job in the session and prepare its context.

    Returns None if no more jobs to apply to.
    Automatically skips jobs whose platform has been declined for login.
    """
    while session.current_index < len(session.plans):
        plan = session.plans[session.current_index]

        # Check if platform was skipped (user refused login)
        if session.login_tracker.is_skipped(plan.platform):
            session.skipped.append(
                {
                    "title": plan.job.title,
                    "company": plan.job.company,
                    "job_id": plan.job.job_id,
                    "reason": f"Login skipped for platform: {plan.platform}",
                    "status": "skipped",
                }
            )
            session.login_tracker.add_skipped_job(plan.platform, plan.job.job_id)
            session.current_index += 1
            continue

        # Re-check dedup (may have been applied earlier this session)
        is_dup, existing = session.dedup.is_duplicate(
            job_id=plan.job.job_id,
            url=plan.job.apply_url,
            company=plan.job.company,
            title=plan.job.title,
        )
        if is_dup:
            session.skipped.append(
                {
                    "title": plan.job.title,
                    "company": plan.job.company,
                    "job_id": plan.job.job_id,
                    "reason": "Duplicate detected during session",
                    "status": "skipped",
                }
            )
            session.current_index += 1
            continue

        # Prepare context
        ctx = prepare_application(
            plan=plan,
            tracker=session.tracker,
            candidate=session.candidate,
            role=session.role,
        )
        session.current_ctx = ctx
        return ctx

    return None


def step(
    session: SessionState,
    snapshot_text: str,
    url: str = "",
) -> list[dict]:
    """Process a browser snapshot during the current job application.

    This is the main per-page call. The agent should:
      1. Take a browser_snapshot
      2. Call step(session, snapshot_text, url)
      3. Execute the returned actions in order
      4. Take another snapshot and call step() again
      5. Repeat until a "submit" or "complete" action is returned

    Returns a list of action dicts. Action types:
      - click:           Click an element (ref, purpose: apply/next/submit)
      - fill:            Fill a text field (ref, value, source)
      - select:          Select dropdown option (ref, value, options)
      - check:           Check a checkbox/radio (ref, value)
      - upload:          Upload a file (ref, filePath)
      - answer_question: Answer a question (question, answer, fieldRef)
      - need_answer:     Agent must generate an answer (question, fieldRef)
      - login_required:  Pause and ask user to log in (platform, message)
      - platform_skipped: Platform was declined, skip job
      - wait:            Wait N seconds then re-snapshot
      - complete:        Application submitted successfully
      - unknown_page:    Page not recognized, agent should investigate
      - error:           Something went wrong
    """
    ctx = session.current_ctx
    if ctx is None:
        return [
            {
                "type": "error",
                "message": "No active application. Call next_job() first.",
            }
        ]

    # Check for success page
    if _is_success_page(snapshot_text, url):
        return [
            {
                "type": "complete",
                "message": "Application submitted successfully!",
                "url": url,
            }
        ]

    # Delegate to login-aware processor
    return process_page_with_login(
        ctx=ctx,
        snapshot_text=snapshot_text,
        url=url,
        login_tracker=session.login_tracker,
    )


def complete_job(
    session: SessionState,
    status: str = "submitted",
    notes: str = "",
) -> dict:
    """Mark the current job as successfully applied.

    Records in both StatusTracker (detailed) and DedupChecker (dedup index).
    """
    ctx = session.current_ctx
    if ctx is None:
        return {"error": "No active application"}

    plan = ctx.plan
    result_info = {
        "title": plan.job.title,
        "company": plan.job.company,
        "job_id": plan.job.job_id,
        "url": plan.job.apply_url,
        "score": plan.job.score,
        "platform": plan.platform,
        "status": status,
    }

    # Save to StatusTracker
    if ctx.result:
        saved_path = session.tracker.complete_application(ctx.result, status=status)
        result_info["result_file"] = str(saved_path)

    # Record in dedup index
    session.dedup.record_application(
        job_id=plan.job.job_id,
        url=plan.job.apply_url,
        company=plan.job.company,
        title=plan.job.title,
        status=status,
        platform=plan.platform,
        flow_id=plan.flow_id,
        notes=notes,
    )

    session.completed.append(result_info)
    session.current_ctx = None
    session.current_index += 1

    return {
        "status": "recorded",
        "job": f"{plan.job.title} @ {plan.job.company}",
        "remaining": session.remaining,
        **result_info,
    }


def fail_job(
    session: SessionState,
    error: str = "Unknown error",
) -> dict:
    """Mark the current job application as failed."""
    ctx = session.current_ctx
    if ctx is None:
        return {"error": "No active application"}

    plan = ctx.plan
    result_info = {
        "title": plan.job.title,
        "company": plan.job.company,
        "job_id": plan.job.job_id,
        "url": plan.job.apply_url,
        "error": error,
        "status": "failed",
    }

    # Save to StatusTracker
    if ctx.result:
        session.tracker.fail_application(ctx.result, error=error)

    session.failed.append(result_info)
    session.current_ctx = None
    session.current_index += 1

    return {
        "status": "failed",
        "job": f"{plan.job.title} @ {plan.job.company}",
        "error": error,
        "remaining": session.remaining,
    }


def skip_job(
    session: SessionState,
    reason: str = "Skipped by agent",
) -> dict:
    """Skip the current job without applying."""
    ctx = session.current_ctx
    if ctx is None:
        return {"error": "No active application"}

    plan = ctx.plan
    result_info = {
        "title": plan.job.title,
        "company": plan.job.company,
        "job_id": plan.job.job_id,
        "reason": reason,
        "status": "skipped",
    }

    if ctx.result:
        session.tracker.skip_application(ctx.result, reason=reason)

    session.skipped.append(result_info)
    session.current_ctx = None
    session.current_index += 1

    return {
        "status": "skipped",
        "job": f"{plan.job.title} @ {plan.job.company}",
        "reason": reason,
        "remaining": session.remaining,
    }


def finish_session(session: SessionState) -> dict:
    """Finalize the session and save summary.

    Returns the complete session summary.
    """
    # Save tracker summary
    summary_path = session.tracker.save_session_summary()

    return {
        "summary_file": str(summary_path),
        "tracker_summary": session.tracker.get_session_summary(),
        "session_progress": session.summary(),
        "dedup_stats": session.dedup.get_stats(),
    }


def _is_success_page(snapshot_text: str, url: str) -> bool:
    """Detect application success/confirmation pages."""
    url_lower = url.lower()
    text_lower = snapshot_text.lower()

    # URL patterns
    success_url_patterns = [
        "/wizard/success",
        "/confirmation",
        "/thank-you",
        "/application-submitted",
        "/success",
    ]
    if any(p in url_lower for p in success_url_patterns):
        return True

    # Text patterns
    success_text_patterns = [
        "hooray",
        "application is on its way",
        "application has been submitted",
        "successfully submitted",
        "thank you for applying",
        "application received",
        "we received your application",
        "your application was submitted",
    ]
    if any(p in text_lower for p in success_text_patterns):
        return True

    return False


def create_session_plan(
    jobs_path: Optional[Path] = None,
    min_score: int = 70,
    max_applications: int = 10,
) -> dict:
    """Create a complete session plan for the agent.

    Returns a dict with:
      - jobs: parsed and filtered job list
      - plans: application plans with dedup/platform info
      - summary: counts of apply/skip/duplicate
      - instructions: what the agent should do next
    """
    # Parse jobs
    jobs = parse_jobs_file(jobs_path, min_score=min_score)
    if not jobs:
        return {
            "jobs": [],
            "plans": [],
            "summary": {"total": 0, "apply": 0, "skip": 0, "duplicate": 0},
            "instructions": "No qualifying jobs found. Check the jobs.md path and min_score.",
        }

    # Create plans
    plans = plan_applications(jobs)

    # Limit to max applications
    apply_plans = [p for p in plans if p.should_apply][:max_applications]
    skip_plans = [p for p in plans if not p.should_apply]

    summary = {
        "total": len(jobs),
        "apply": len(apply_plans),
        "skip": len([p for p in skip_plans if p.skip_reason]),
        "duplicate": len([p for p in plans if p.is_duplicate]),
        "noFlow": len([p for p in skip_plans if not p.is_duplicate and p.skip_reason]),
    }

    instructions = []
    if apply_plans:
        instructions.append(f"Ready to apply to {len(apply_plans)} jobs.")
        for i, p in enumerate(apply_plans, 1):
            platform_info = f"({p.platform})" if p.platform else "(platform TBD)"
            instructions.append(
                f"  {i}. {p.job.title} @ {p.job.company} {platform_info} — score {p.job.score}%"
            )
    if summary["duplicate"] > 0:
        instructions.append(f"Skipping {summary['duplicate']} already applied.")
    if summary["noFlow"] > 0:
        instructions.append(f"Skipping {summary['noFlow']} with no matching flow.")

    return {
        "jobs": [j.to_dict() for j in jobs],
        "plans": [p.to_dict() for p in plans],
        "applyPlans": [p.to_dict() for p in apply_plans],
        "summary": summary,
        "instructions": "\n".join(instructions),
    }
