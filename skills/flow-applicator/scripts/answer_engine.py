"""
Answer engine for job application questions.

Priority order (highest to lowest):
  1. Flow commonQuestions — exact/fuzzy match from the platform flow
  2. question_templates.md — pattern-matched from references
  3. role_qna.md — role-specific Q&A
  4. profile_data.md / profile.md — structured candidate data
  5. LLM-generated — only as last resort (costs tokens)

Company-specific answers are NEVER added to generic templates —
they go into the flow's commonQuestions or a company-specific state file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import paths


@dataclass
class AnswerResult:
    """Result of an answer lookup."""

    answer: str
    source: str  # "flow", "template", "role_qna", "profile", "generated", "not_found"
    confidence: float  # 0.0 to 1.0
    field_name: str = ""
    question: str = ""

    @property
    def found(self) -> bool:
        return self.source != "not_found"


class AnswerEngine:
    """Resolves answers to application questions from multiple sources."""

    def __init__(
        self,
        candidate: Optional[str] = None,
        role: Optional[str] = None,
    ):
        # Auto-detect candidate/role if not provided
        if candidate is None:
            candidate = paths.candidate_dir().name
        if role is None:
            role = paths.role_dir(candidate).name

        self.candidate = candidate
        self.role = role
        # Lazy-loaded caches
        self._templates: Optional[dict[str, str]] = None
        self._role_qna: Optional[dict[str, str]] = None
        self._profile_data: Optional[dict[str, Any]] = None

    # ── Source loaders ─────────────────────────────────────────────

    def _load_templates(self) -> dict[str, str]:
        """Parse question_templates.md into {pattern: answer} dict."""
        if self._templates is not None:
            return self._templates

        self._templates = {}
        path = paths.question_templates_path()
        if not path.exists():
            return self._templates

        content = path.read_text(encoding="utf-8")
        # Parse markdown tables: | Question Pattern | Answer |
        for line in content.splitlines():
            line = line.strip()
            if (
                not line.startswith("|")
                or line.startswith("|--")
                or line.startswith("| Question")
            ):
                continue
            parts = [p.strip() for p in line.split("|")]
            parts = [p for p in parts if p]  # Remove empty from leading/trailing |
            if len(parts) >= 2:
                question_pattern = parts[0]
                answer = parts[1]
                if answer and question_pattern and question_pattern != "---":
                    # Also handle 3-column tables (Question | Type | Answer)
                    if len(parts) >= 3 and parts[1] in ("text", "email", "tel", "url"):
                        answer = parts[2]
                    self._templates[question_pattern.lower()] = answer

        # Parse non-table Q&A sections
        lines = content.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            # Match ### "Question" patterns
            m = re.match(r'^###\s+"(.+)"', line)
            if m:
                q = m.group(1).lower()
                # Collect answer lines until next heading
                answer_lines = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("#"):
                    answer_lines.append(lines[i])
                    i += 1
                answer_text = "\n".join(answer_lines).strip()
                if answer_text.startswith("```"):
                    # Strip code fences
                    answer_text = re.sub(r"^```\w*\n?", "", answer_text)
                    answer_text = re.sub(r"\n?```$", "", answer_text)
                if answer_text:
                    self._templates[q] = answer_text.strip()
                continue
            i += 1

        return self._templates

    def _load_role_qna(self) -> dict[str, str]:
        """Parse role_qna.md into {question: answer} dict."""
        if self._role_qna is not None:
            return self._role_qna

        self._role_qna = {}
        path = paths.role_qna_path(self.candidate, self.role)
        if not path.exists():
            return self._role_qna

        content = path.read_text(encoding="utf-8")
        current_q = None
        answer_lines = []

        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("Q:") or stripped.startswith("**Q:"):
                # Save previous Q&A
                if current_q and answer_lines:
                    self._role_qna[current_q.lower()] = "\n".join(answer_lines).strip()
                current_q = re.sub(r"^\*?\*?Q:\s*", "", stripped).rstrip("*").strip()
                answer_lines = []
            elif stripped.startswith("A:") or stripped.startswith("**A:"):
                a_text = re.sub(r"^\*?\*?A:\s*", "", stripped).rstrip("*").strip()
                answer_lines.append(a_text)
            elif current_q and stripped:
                answer_lines.append(stripped)

        if current_q and answer_lines:
            self._role_qna[current_q.lower()] = "\n".join(answer_lines).strip()

        return self._role_qna

    def _load_profile_data(self) -> dict[str, Any]:
        """Parse profile_data.md YAML blocks into a flat dict."""
        if self._profile_data is not None:
            return self._profile_data

        self._profile_data = {}
        path = paths.profile_data_path()
        if not path.exists():
            return self._profile_data

        content = path.read_text(encoding="utf-8")
        # Extract key: value pairs from YAML blocks
        in_yaml = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "```yaml":
                in_yaml = True
                continue
            if stripped == "```":
                in_yaml = False
                continue
            if in_yaml and ":" in stripped:
                key, _, value = stripped.partition(":")
                key = key.strip().lower().replace(" ", "_")
                value = value.strip().strip('"').strip("'")
                if key and value:
                    self._profile_data[key] = value

        return self._profile_data

    # ── Matching logic ─────────────────────────────────────────────

    def _fuzzy_match(
        self,
        question: str,
        candidates: dict[str, str],
        min_confidence: float = 0.6,
    ) -> Optional[tuple[str, float]]:
        """Find the best fuzzy match for a question in a {pattern: answer} dict.

        Returns (answer, confidence) or None if below min_confidence.
        """
        q_lower = question.lower().strip()
        q_tokens = set(q_lower.split())

        best_answer = None
        best_score = 0.0

        for pattern, answer in candidates.items():
            p_lower = pattern.lower().strip()

            # Exact match
            if q_lower == p_lower:
                return (answer, 1.0)

            # Containment
            if p_lower in q_lower or q_lower in p_lower:
                score = min(len(p_lower), len(q_lower)) / max(
                    len(p_lower), len(q_lower)
                )
                if score > best_score:
                    best_score = score
                    best_answer = answer
                continue

            # Token overlap
            p_tokens = set(p_lower.split())
            if p_tokens:
                overlap = len(q_tokens & p_tokens) / len(p_tokens)
                if overlap > best_score:
                    best_score = overlap
                    best_answer = answer

        if best_answer and best_score >= min_confidence:
            return (best_answer, best_score)
        return None

    def _profile_field_match(self, question: str) -> Optional[tuple[str, float]]:
        """Try to match a question to a profile data field."""
        profile = self._load_profile_data()
        q_lower = question.lower()

        # Ordered field mapping — more specific patterns first to avoid
        # "visa" matching before "sponsorship" for sponsorship questions.
        field_keywords: list[tuple[str, list[str]]] = [
            # Sponsorship-specific (must come before visa/authorization)
            (
                "require_sponsorship",
                [
                    "require sponsorship",
                    "need sponsorship",
                    "sponsorship required",
                    "visa sponsorship",
                    "do you require",
                    "do you need",
                ],
            ),
            # Work authorization
            (
                "current_status",
                [
                    "work authorization",
                    "authorization status",
                    "visa status",
                    "immigration status",
                    "authorized to work",
                ],
            ),
            # Contact info
            ("name", ["full name"]),
            ("first_name", ["first name"]),
            ("last_name", ["last name"]),
            ("email", ["email", "e-mail"]),
            ("phone", ["phone", "mobile", "telephone", "cell"]),
            # Location
            ("location", ["current location", "where are you located", "city"]),
            ("address", ["street address", "mailing address"]),
            # Online profiles
            ("linkedin", ["linkedin"]),
            ("github", ["github"]),
            ("portfolio", ["portfolio", "website", "personal site"]),
            # Compensation
            (
                "salary_expectation",
                [
                    "salary",
                    "compensation",
                    "expected pay",
                    "desired salary",
                    "pay expectation",
                ],
            ),
            # Experience
            (
                "total_years",
                [
                    "years of experience",
                    "total experience",
                    "how many years",
                ],
            ),
            # Education
            ("degree", ["degree", "highest degree", "education level"]),
            ("university", ["university", "school", "college"]),
            ("field", ["major", "field of study"]),
            ("graduation", ["graduation", "grad year", "when did you graduate"]),
            # Availability
            (
                "start_date",
                [
                    "start date",
                    "when can you start",
                    "earliest start",
                    "availability date",
                ],
            ),
            ("notice_period", ["notice period"]),
            # Relocation
            (
                "available_for_relocation",
                [
                    "willing to relocate",
                    "open to relocation",
                    "relocate",
                    "relocation",
                ],
            ),
            # Work mode
            (
                "remote_preference",
                [
                    "work mode",
                    "remote",
                    "hybrid",
                    "onsite",
                    "work arrangement",
                    "work preference",
                ],
            ),
        ]

        for profile_key, keywords in field_keywords:
            for kw in keywords:
                if kw in q_lower:
                    value = profile.get(profile_key)
                    if value:
                        return (str(value), 0.8)

        return None

    # ── Known field detection ──────────────────────────────────────

    _KNOWN_FIELD_KEYWORDS = {
        "email": ["email", "e-mail"],
        "phone": ["phone", "mobile", "telephone", "cell"],
        "name": ["full name", "first name", "last name", "your name"],
        "location": ["city", "current location", "where are you located"],
        "linkedin": ["linkedin"],
        "github": ["github"],
        "portfolio": ["portfolio", "website", "personal site"],
        "salary": ["salary", "compensation", "expected pay", "desired salary"],
        "visa": [
            "work authorization",
            "visa status",
            "authorized to work",
            "immigration status",
        ],
        "sponsorship": ["sponsorship", "require sponsorship", "need sponsorship"],
        "start_date": [
            "start date",
            "when can you start",
            "earliest start",
            "availability",
        ],
        "notice_period": ["notice period"],
        "relocate": [
            "willing to relocate",
            "open to relocation",
            "relocate",
            "relocation",
        ],
        "years_experience": [
            "years of experience",
            "total experience",
            "how many years",
        ],
        "work_mode": ["work mode", "remote", "hybrid", "onsite", "work arrangement"],
    }

    def _is_known_field_question(self, question: str) -> bool:
        """Check if a question is asking for a known profile field."""
        q_lower = question.lower()
        for keywords in self._KNOWN_FIELD_KEYWORDS.values():
            for kw in keywords:
                if kw in q_lower:
                    return True
        return False

    # ── Main resolution ────────────────────────────────────────────

    def resolve(
        self,
        question: str,
        flow_graph=None,
        field_name: str = "",
    ) -> AnswerResult:
        """Resolve an answer through the priority chain.

        Args:
            question: The question text from the application form.
            flow_graph: Optional FlowGraph to check commonQuestions first.
            field_name: Optional field identifier for direct mapping.

        Returns:
            AnswerResult with the answer, source, and confidence.

        Resolution order:
          1. Flow commonQuestions (exact/fuzzy from platform flow)
          2. Profile field match (for known field questions like email, phone, location)
          3. question_templates.md (high-confidence fuzzy match >= 0.7)
          4. role_qna.md (high-confidence fuzzy match >= 0.7)
          5. question_templates.md (lower-confidence >= 0.6)
          6. role_qna.md (lower-confidence >= 0.6)
          7. Not found — caller should use LLM
        """
        # Priority 1: Flow commonQuestions
        if flow_graph:
            answer = flow_graph.find_answer(question)
            if answer:
                return AnswerResult(
                    answer=answer,
                    source="flow",
                    confidence=0.95,
                    field_name=field_name,
                    question=question,
                )

        # Priority 2: Profile field match — runs early for known fields
        # (email, phone, location, visa, etc. should come from profile data)
        if self._is_known_field_question(question) or field_name:
            match = self._profile_field_match(question)
            if match:
                return AnswerResult(
                    answer=match[0],
                    source="profile",
                    confidence=match[1],
                    field_name=field_name,
                    question=question,
                )

        # Priority 3: question_templates.md (high confidence only)
        templates = self._load_templates()
        match = self._fuzzy_match(question, templates, min_confidence=0.7)
        if match:
            return AnswerResult(
                answer=match[0],
                source="template",
                confidence=match[1],
                field_name=field_name,
                question=question,
            )

        # Priority 4: role_qna.md (high confidence only)
        role_qna = self._load_role_qna()
        match = self._fuzzy_match(question, role_qna, min_confidence=0.7)
        if match:
            return AnswerResult(
                answer=match[0],
                source="role_qna",
                confidence=match[1],
                field_name=field_name,
                question=question,
            )

        # Priority 5: Templates at lower threshold
        match = self._fuzzy_match(question, templates, min_confidence=0.6)
        if match:
            return AnswerResult(
                answer=match[0],
                source="template",
                confidence=match[1],
                field_name=field_name,
                question=question,
            )

        # Priority 6: Role Q&A at lower threshold
        match = self._fuzzy_match(question, role_qna, min_confidence=0.6)
        if match:
            return AnswerResult(
                answer=match[0],
                source="role_qna",
                confidence=match[1],
                field_name=field_name,
                question=question,
            )

        # Priority 7: Profile field match as final fallback (for non-known-field questions)
        match = self._profile_field_match(question)
        if match:
            return AnswerResult(
                answer=match[0],
                source="profile",
                confidence=match[1],
                field_name=field_name,
                question=question,
            )

        # Priority 8: Not found — caller should use LLM
        return AnswerResult(
            answer="",
            source="not_found",
            confidence=0.0,
            field_name=field_name,
            question=question,
        )

    def resolve_batch(
        self,
        questions: list[dict[str, str]],
        flow_graph=None,
    ) -> list[AnswerResult]:
        """Resolve multiple questions at once.

        Args:
            questions: List of {"question": str, "field_name": str} dicts.
            flow_graph: Optional FlowGraph for commonQuestions.

        Returns:
            List of AnswerResult in same order as input.
        """
        return [
            self.resolve(
                question=q.get("question", ""),
                flow_graph=flow_graph,
                field_name=q.get("field_name", ""),
            )
            for q in questions
        ]

    def get_field_value(
        self,
        field_name: str,
        flow_graph=None,
    ) -> AnswerResult:
        """Resolve a known field name (e.g. 'email', 'phone') to its value.

        This uses the field mapping approach rather than question matching.
        """
        if flow_graph:
            mapping = flow_graph.get_field_mapping(field_name)
            if mapping:
                if mapping.source == "profile":
                    profile = self._load_profile_data()
                    value = profile.get(mapping.source_field)
                    if value:
                        return AnswerResult(
                            answer=str(value),
                            source="profile",
                            confidence=1.0,
                            field_name=field_name,
                        )
                elif mapping.source == "template":
                    templates = self._load_templates()
                    value = templates.get(mapping.source_field.lower())
                    if value:
                        return AnswerResult(
                            answer=value,
                            source="template",
                            confidence=1.0,
                            field_name=field_name,
                        )

        # Fallback: treat field_name as a question
        return self.resolve(field_name, flow_graph=flow_graph, field_name=field_name)
