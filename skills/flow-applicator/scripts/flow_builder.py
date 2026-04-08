"""
Flow builder — converts Playwright browser snapshots into flow graph nodes.

This module bridges the gap between live browser state and stored flow graphs.
When the agent encounters a page during application:

  1. Take a browser_snapshot (accessibility tree)
  2. Parse it into structured form data (fields, buttons, questions)
  3. Match against the current flow node
  4. If match → replay known actions
  5. If deviation → create a sister node with the new state

The builder does NOT execute browser actions itself — it produces
structured data that the orchestrator/agent uses to decide what to do.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

import flow_engine


# ── Snapshot Parsing ───────────────────────────────────────────────


@dataclass
class ParsedField:
    """A form field extracted from a browser snapshot."""

    name: str  # The label or accessible name
    ref: str  # The Playwright element ref (e.g. "S12a")
    field_type: str  # "textbox", "combobox", "checkbox", "radio", "file", "slider"
    value: str = ""  # Current value if any
    required: bool = False
    options: list[str] = field(default_factory=list)  # For combobox/radio
    placeholder: str = ""

    def to_dict(self) -> dict:
        d = {"name": self.name, "ref": self.ref, "type": self.field_type}
        if self.value:
            d["value"] = self.value
        if self.required:
            d["required"] = True
        if self.options:
            d["options"] = self.options
        if self.placeholder:
            d["placeholder"] = self.placeholder
        return d


@dataclass
class ParsedButton:
    """A button extracted from a browser snapshot."""

    text: str
    ref: str
    button_type: str = ""  # "submit", "next", "cancel", "back", "apply"

    def classify(self) -> str:
        """Classify button by its text content."""
        text_lower = self.text.lower().strip()
        if any(w in text_lower for w in ["submit", "apply now", "send application"]):
            return "submit"
        if any(w in text_lower for w in ["next", "continue", "proceed"]):
            return "next"
        if any(w in text_lower for w in ["back", "previous"]):
            return "back"
        if any(w in text_lower for w in ["cancel", "close", "dismiss"]):
            return "cancel"
        if any(w in text_lower for w in ["easy apply", "apply", "apply for"]):
            return "apply"
        if any(w in text_lower for w in ["upload", "attach", "choose file"]):
            return "upload"
        if any(w in text_lower for w in ["review", "confirm"]):
            return "review"
        return "other"

    def to_dict(self) -> dict:
        return {"text": self.text, "ref": self.ref, "type": self.classify()}


@dataclass
class ParsedQuestion:
    """A question/label extracted from a browser snapshot."""

    text: str
    field_ref: str = ""  # Associated field ref if identifiable
    question_type: str = "text"  # "text", "yes_no", "select", "long_text"

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "fieldRef": self.field_ref,
            "type": self.question_type,
        }


@dataclass
class ParsedPage:
    """Structured representation of a browser page from a snapshot."""

    url: str = ""
    title: str = ""
    fields: list[ParsedField] = field(default_factory=list)
    buttons: list[ParsedButton] = field(default_factory=list)
    questions: list[ParsedQuestion] = field(default_factory=list)
    headings: list[str] = field(default_factory=list)
    has_file_upload: bool = False
    raw_snapshot: str = ""

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "title": self.title,
            "fields": [f.to_dict() for f in self.fields],
            "buttons": [b.to_dict() for b in self.buttons],
            "questions": [q.to_dict() for q in self.questions],
            "headings": self.headings,
            "hasFileUpload": self.has_file_upload,
        }

    def get_next_button(self) -> Optional[ParsedButton]:
        """Find the primary 'next' or 'continue' button."""
        for b in self.buttons:
            if b.classify() == "next":
                return b
        return None

    def get_submit_button(self) -> Optional[ParsedButton]:
        """Find the submit/apply button."""
        for b in self.buttons:
            if b.classify() in ("submit", "apply"):
                return b
        return None

    def get_upload_button(self) -> Optional[ParsedButton]:
        """Find a file upload button."""
        for b in self.buttons:
            if b.classify() == "upload":
                return b
        # Check for file input fields
        for f in self.fields:
            if f.field_type == "file":
                return ParsedButton(text="upload", ref=f.ref, button_type="upload")
        return None


def parse_snapshot(snapshot_text: str, url: str = "") -> ParsedPage:
    """Parse a Playwright accessibility snapshot into a ParsedPage.

    This parser handles the text-based snapshot format returned by
    playwright_browser_snapshot, which looks like:

    ```
    - heading "Apply for ML Engineer" [level=1]
    - textbox "First name" [ref=S12a] [required]
    - textbox "Last name" [ref=S12b] [required]
    - combobox "Country" [ref=S12c]
        - option "United States"
        - option "Canada"
    - button "Next" [ref=S12d]
    ```
    """
    page = ParsedPage(url=url, raw_snapshot=snapshot_text)
    lines = snapshot_text.splitlines()

    current_options: list[str] = []
    last_field: Optional[ParsedField] = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("```"):
            continue

        # Extract element type, name, and ref
        # Patterns: - type "name" [ref=X] [required]
        m = re.match(
            r'^-?\s*(\w+)\s+"([^"]*)"(?:\s+\[ref=(\w+)\])?(.*)$',
            stripped,
        )
        if not m:
            # Try without quotes: - type name [ref=X]
            m = re.match(
                r"^-?\s*(\w+)\s+([^\[]+?)(?:\s+\[ref=(\w+)\])?(.*)$",
                stripped,
            )
        if not m:
            continue

        elem_type = m.group(1).lower()
        elem_name = m.group(2).strip()
        elem_ref = m.group(3) or ""
        extras = m.group(4) or ""

        required = "[required]" in extras
        disabled = "[disabled]" in extras

        if disabled:
            continue

        if elem_type == "heading":
            page.headings.append(elem_name)
            # Extract level
            level_m = re.search(r"\[level=(\d+)\]", extras)

        elif elem_type in ("textbox", "searchbox"):
            last_field = ParsedField(
                name=elem_name,
                ref=elem_ref,
                field_type="textbox",
                required=required,
            )
            page.fields.append(last_field)

        elif elem_type == "combobox":
            last_field = ParsedField(
                name=elem_name,
                ref=elem_ref,
                field_type="combobox",
                required=required,
            )
            current_options = []
            page.fields.append(last_field)

        elif (
            elem_type == "option" and last_field and last_field.field_type == "combobox"
        ):
            last_field.options.append(elem_name)

        elif elem_type in ("checkbox", "radio"):
            pf = ParsedField(
                name=elem_name,
                ref=elem_ref,
                field_type=elem_type,
                required=required,
            )
            page.fields.append(pf)

        elif elem_type == "button":
            page.buttons.append(ParsedButton(text=elem_name, ref=elem_ref))

        elif elem_type == "link":
            # Links that look like buttons (e.g. "Apply now" links)
            if any(w in elem_name.lower() for w in ["apply", "submit"]):
                page.buttons.append(ParsedButton(text=elem_name, ref=elem_ref))

        elif elem_type in ("text", "paragraph", "label"):
            # Check if it looks like a question
            if "?" in elem_name or any(
                elem_name.lower().startswith(w)
                for w in [
                    "are you",
                    "do you",
                    "have you",
                    "will you",
                    "what",
                    "how",
                    "why",
                    "describe",
                    "tell us",
                ]
            ):
                page.questions.append(ParsedQuestion(text=elem_name))
            elif len(elem_name) > 10 and not elem_name.startswith("http"):
                # Could be a label for the next field
                page.questions.append(ParsedQuestion(text=elem_name))

    # Detect file upload
    for f in page.fields:
        if (
            "resume" in f.name.lower()
            or "upload" in f.name.lower()
            or "cv" in f.name.lower()
        ):
            page.has_file_upload = True
            break

    return page


# ── Flow Matching ──────────────────────────────────────────────────


def match_page_to_node(
    page: ParsedPage, flow: FlowGraph, current_node_id: str = ""
) -> tuple[Optional[FlowNode], float]:
    """Match a parsed page to a node in the flow graph.

    Returns (matched_node, confidence).
    Confidence: 1.0 = exact match, 0.0 = no match.
    """
    best_node = None
    best_score = 0.0

    # If we know the current node, check the expected next node first
    if current_node_id:
        next_node = flow.get_next_node(current_node_id)
        if next_node:
            score = _node_match_score(page, next_node)
            if score >= 0.5:
                return (next_node, score)

    # Check all nodes
    for nid, node in flow.nodes.items():
        score = _node_match_score(page, node)
        if score > best_score:
            best_score = score
            best_node = node

    if best_score >= 0.3:
        return (best_node, best_score)
    return (None, 0.0)


def _node_match_score(page: ParsedPage, node: FlowNode) -> float:
    """Score how well a parsed page matches a flow node."""
    scores = []

    # URL pattern match
    if node.url_pattern and page.url:
        if re.search(node.url_pattern, page.url, re.IGNORECASE):
            scores.append(1.0)
        else:
            scores.append(0.0)

    # Field overlap
    if node.fields:
        page_field_names = {f.name.lower() for f in page.fields}
        node_field_names = {f.lower() for f in node.fields}
        if node_field_names:
            overlap = len(page_field_names & node_field_names) / len(node_field_names)
            scores.append(overlap)

    # Description keyword match
    if node.description and page.headings:
        desc_tokens = set(node.description.lower().split())
        heading_tokens = set()
        for h in page.headings:
            heading_tokens.update(h.lower().split())
        if desc_tokens:
            overlap = len(desc_tokens & heading_tokens) / len(desc_tokens)
            scores.append(overlap * 0.5)

    if not scores:
        return 0.0
    return sum(scores) / len(scores)


# ── Node Building ──────────────────────────────────────────────────


def build_node_from_page(
    node_id: str,
    page: ParsedPage,
    node_type: str = "form",
) -> dict:
    """Create a flow node dict from a parsed page.

    This is used when we encounter a page that doesn't match any known node
    and need to add it (or a sister node) to the flow.
    """
    fields = [f.name for f in page.fields]
    description = (
        " | ".join(page.headings)
        if page.headings
        else f"Auto-discovered {node_type} page"
    )

    node_data: dict[str, Any] = {
        "type": node_type,
        "description": description,
        "fields": fields,
    }

    if page.url:
        node_data["urlPattern"] = _url_to_pattern(page.url)

    next_btn = page.get_next_button()
    if next_btn:
        node_data["nextButton"] = f"[ref={next_btn.ref}]"

    submit_btn = page.get_submit_button()
    if submit_btn:
        node_data["submitButton"] = f"[ref={submit_btn.ref}]"

    return node_data


def _url_to_pattern(url: str) -> str:
    """Convert a specific URL to a regex pattern for matching.

    Example: https://boards.greenhouse.io/acme/jobs/12345
         ->  boards.greenhouse.io/.*/jobs/.*
    """
    # Remove protocol
    pattern = re.sub(r"^https?://", "", url)
    # Replace numeric IDs with .*
    pattern = re.sub(r"/\d+", "/.*", pattern)
    # Remove query string
    pattern = re.sub(r"\?.*$", "", pattern)
    return pattern


# ── Login Detection ─────────────────────────────────────────────────


@dataclass
class LoginDetection:
    """Result of login page detection."""

    is_login_page: bool = False
    platform: str = ""  # "dice", "linkedin", "workday", etc.
    confidence: float = 0.0
    indicators: list[str] = field(default_factory=list)
    redirect_url: str = ""  # Where the login should redirect after auth


# URL patterns that indicate a login/auth page
_LOGIN_URL_PATTERNS: list[tuple[str, str]] = [
    (r"dice\.com/dashboard/login", "dice"),
    (r"linkedin\.com/login", "linkedin"),
    (r"linkedin\.com/checkpoint", "linkedin"),
    (r"myworkday\.com/.*login", "workday"),
    (r"icims\.com/.*login", "icims"),
    (r"signin|sign-in|sign_in", "unknown"),
    (r"login|log-in|log_in", "unknown"),
    (r"/auth/", "unknown"),
    (r"/sso/", "unknown"),
    (r"/oauth", "unknown"),
]

# Snapshot text patterns that indicate a login page
_LOGIN_TEXT_PATTERNS: list[str] = [
    r"sign\s*in",
    r"log\s*in",
    r"create\s+an?\s+account",
    r"continue\s+with\s+(email|google|apple|github|microsoft)",
    r"enter\s+your\s+(email|password)",
    r"forgot\s+(your\s+)?password",
    r"don'?t\s+have\s+an\s+account",
    r"let'?s\s+get\s+you\s+hired",  # Dice-specific
    r"welcome\s+back",
]


def detect_login_page(snapshot_text: str, url: str = "") -> LoginDetection:
    """Detect whether a browser page is a login/authentication gate.

    Analyzes both the URL and the snapshot text for login indicators.
    Returns a LoginDetection with platform identification and confidence.

    This should be called BEFORE process_page() to intercept login gates
    and pause for user authentication.
    """
    result = LoginDetection()
    indicators: list[str] = []

    # Check URL patterns
    url_lower = url.lower()
    for pattern, platform in _LOGIN_URL_PATTERNS:
        if re.search(pattern, url_lower, re.IGNORECASE):
            indicators.append(f"URL matches login pattern: {pattern}")
            if platform != "unknown":
                result.platform = platform
            break

    # Check for redirect URL in query params (common in login gates)
    redirect_m = re.search(r"[?&]redirect[Uu]rl=([^&]+)", url)
    if redirect_m:
        result.redirect_url = redirect_m.group(1)
        indicators.append(f"Has redirect URL: {result.redirect_url}")

    # Check snapshot text patterns
    text_lower = snapshot_text.lower()
    text_match_count = 0
    for pattern in _LOGIN_TEXT_PATTERNS:
        if re.search(pattern, text_lower):
            indicators.append(f"Text matches: {pattern}")
            text_match_count += 1

    # Check for password field (strong indicator)
    if re.search(r'textbox\s+"[^"]*password[^"]*"', text_lower):
        indicators.append("Password field found")
        text_match_count += 2  # Strong signal

    # Check for email-only field without other form fields
    # (login pages typically have email + password, not name/phone/resume)
    page = parse_snapshot(snapshot_text, url)
    form_field_names = {f.name.lower() for f in page.fields}
    login_field_names = {"email", "password", "username", "enter your email"}
    non_login_fields = (
        form_field_names - login_field_names - {"remember me", "keep me signed in"}
    )

    if form_field_names & login_field_names and len(non_login_fields) == 0:
        indicators.append(
            "Only login-related fields present (no application form fields)"
        )
        text_match_count += 1

    # Calculate confidence
    url_score = (
        0.4 if any(re.search(p, url_lower) for p, _ in _LOGIN_URL_PATTERNS) else 0.0
    )
    text_score = min(0.6, text_match_count * 0.15)
    result.confidence = min(1.0, url_score + text_score)
    result.is_login_page = result.confidence >= 0.4
    result.indicators = indicators

    # Try to identify platform from URL if not already set
    if not result.platform and url:
        if "dice.com" in url_lower:
            result.platform = "dice"
        elif "linkedin.com" in url_lower:
            result.platform = "linkedin"
        elif "workday" in url_lower or "myworkdayjobs" in url_lower:
            result.platform = "workday"
        elif "icims.com" in url_lower:
            result.platform = "icims"

    return result


def is_dice_wizard_page(snapshot_text: str, url: str = "") -> dict:
    """Detect whether the current page is a Dice apply wizard step.

    Returns a dict with:
      - is_wizard: bool
      - step: int (1 or 2, or 0 if not detected)
      - step_label: str ("Resume & Cover Letter" or "Review your application")
      - next_action: str ("click_next" or "click_submit")
      - button_ref: str (the ref of the primary action button, if found)
    """
    result = {
        "is_wizard": False,
        "step": 0,
        "step_label": "",
        "next_action": "",
        "button_ref": "",
    }

    url_lower = url.lower()
    if "dice.com/job-applications" not in url_lower:
        return result
    if "wizard" not in url_lower and "start-apply" not in url_lower:
        return result

    result["is_wizard"] = True

    text_lower = snapshot_text.lower()
    page = parse_snapshot(snapshot_text, url)

    # Detect step number
    if "step 1 of 2" in text_lower or "resume & cover letter" in text_lower:
        result["step"] = 1
        result["step_label"] = "Resume & Cover Letter"
        result["next_action"] = "click_next"
        # Find the Next button
        next_btn = page.get_next_button()
        if next_btn:
            result["button_ref"] = next_btn.ref
    elif "step 2 of 2" in text_lower or "review your application" in text_lower:
        result["step"] = 2
        result["step_label"] = "Review your application"
        result["next_action"] = "click_submit"
        # Find the Submit button
        submit_btn = page.get_submit_button()
        if submit_btn:
            result["button_ref"] = submit_btn.ref

    return result


# ── Deviation Detection ────────────────────────────────────────────


def detect_deviations(page: ParsedPage, node: FlowNode, flow: FlowGraph) -> list[dict]:
    """Compare a parsed page with the expected node and identify deviations.

    Returns a list of deviation dicts with type, description, and suggested action.
    """
    deviations = []

    # Check for unexpected fields
    expected_fields = {f.lower() for f in node.fields}
    actual_fields = {f.name.lower() for f in page.fields}

    new_fields = actual_fields - expected_fields
    for nf in new_fields:
        deviations.append(
            {
                "type": "new_field",
                "description": f"Unexpected field: {nf}",
                "field_name": nf,
                "action": "add_to_node",
            }
        )

    missing_fields = expected_fields - actual_fields
    for mf in missing_fields:
        deviations.append(
            {
                "type": "missing_field",
                "description": f"Expected field not found: {mf}",
                "field_name": mf,
                "action": "skip_or_sister",
            }
        )

    # Check for new questions not in flow commonQuestions
    for q in page.questions:
        if flow.find_answer(q.text) is None:
            deviations.append(
                {
                    "type": "new_question",
                    "description": f"Unknown question: {q.text}",
                    "question": q.text,
                    "action": "resolve_and_add",
                }
            )

    return deviations
