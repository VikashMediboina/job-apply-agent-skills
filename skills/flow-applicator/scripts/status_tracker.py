"""
Application status tracker.

Writes per-application result files to:
  {workspace}/applications/{date}/{job_id}.json

Each file contains the full application context:
  - Job details (title, company, URL, score)
  - Application flow used
  - Fields filled and answers given
  - Questions encountered (with sources)
  - Deviations from known flow
  - Screenshots/snapshots taken
  - Final status and any error details
  - Timing information

This data feeds back into flow improvement:
  - New questions → added to flow commonQuestions
  - New fields → added to flow knownFields
  - Deviations → sister nodes created
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import paths


@dataclass
class QuestionLog:
    """Log of a question encountered during application."""

    question: str
    answer: str
    source: str  # "flow", "template", "role_qna", "profile", "generated"
    confidence: float
    field_name: str = ""
    was_new: bool = False  # True if this question was not in any source

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FieldLog:
    """Log of a field filled during application."""

    field_name: str
    value: str
    source: str
    selector: str = ""
    field_type: str = ""  # "text", "email", "file", "select", "radio", "checkbox"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DeviationLog:
    """Log of a deviation from the known flow."""

    node_id: str
    deviation_type: (
        str  # "new_field", "new_question", "unexpected_page", "missing_element"
    )
    description: str
    resolution: str  # "sister_node_created", "skipped", "manual", "failed"
    new_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ApplicationResult:
    """Complete record of a single application attempt."""

    # Job info
    job_id: str
    job_title: str
    company: str
    url: str
    apply_url: str
    score: int = 0
    source: str = ""  # "dice", "linkedin", "indeed"

    # Flow info
    platform: str = ""
    flow_id: str = ""
    flow_version: str = ""

    # Execution
    status: str = ""  # "submitted", "failed", "skipped", "incomplete"
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0
    error: str = ""

    # Detailed logs
    fields_filled: list[FieldLog] = field(default_factory=list)
    questions_answered: list[QuestionLog] = field(default_factory=list)
    deviations: list[DeviationLog] = field(default_factory=list)
    nodes_visited: list[str] = field(default_factory=list)

    # Token cost tracking
    tokens_used: int = 0
    llm_calls: int = 0

    def to_dict(self) -> dict:
        return {
            "jobId": self.job_id,
            "jobTitle": self.job_title,
            "company": self.company,
            "url": self.url,
            "applyUrl": self.apply_url,
            "score": self.score,
            "source": self.source,
            "platform": self.platform,
            "flowId": self.flow_id,
            "flowVersion": self.flow_version,
            "status": self.status,
            "startedAt": self.started_at,
            "completedAt": self.completed_at,
            "durationSeconds": self.duration_seconds,
            "error": self.error,
            "fieldsFilled": [f.to_dict() for f in self.fields_filled],
            "questionsAnswered": [q.to_dict() for q in self.questions_answered],
            "deviations": [d.to_dict() for d in self.deviations],
            "nodesVisited": self.nodes_visited,
            "tokensUsed": self.tokens_used,
            "llmCalls": self.llm_calls,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ApplicationResult:
        return cls(
            job_id=data.get("jobId", ""),
            job_title=data.get("jobTitle", ""),
            company=data.get("company", ""),
            url=data.get("url", ""),
            apply_url=data.get("applyUrl", ""),
            score=data.get("score", 0),
            source=data.get("source", ""),
            platform=data.get("platform", ""),
            flow_id=data.get("flowId", ""),
            flow_version=data.get("flowVersion", ""),
            status=data.get("status", ""),
            started_at=data.get("startedAt", ""),
            completed_at=data.get("completedAt", ""),
            duration_seconds=data.get("durationSeconds", 0.0),
            error=data.get("error", ""),
            fields_filled=[FieldLog(**f) for f in data.get("fieldsFilled", [])],
            questions_answered=[
                QuestionLog(**q) for q in data.get("questionsAnswered", [])
            ],
            deviations=[DeviationLog(**d) for d in data.get("deviations", [])],
            nodes_visited=data.get("nodesVisited", []),
            tokens_used=data.get("tokensUsed", 0),
            llm_calls=data.get("llmCalls", 0),
        )


class StatusTracker:
    """Tracks and persists application results."""

    def __init__(self, date: Optional[str] = None):
        self.date = date or datetime.now().strftime("%Y-%m-%d")
        self._results: list[ApplicationResult] = []

    def start_application(
        self,
        job_id: str,
        job_title: str,
        company: str,
        url: str,
        apply_url: str,
        score: int = 0,
        source: str = "",
        platform: str = "",
        flow_id: str = "",
        flow_version: str = "",
    ) -> ApplicationResult:
        """Create a new ApplicationResult and mark it as started."""
        result = ApplicationResult(
            job_id=job_id,
            job_title=job_title,
            company=company,
            url=url,
            apply_url=apply_url,
            score=score,
            source=source,
            platform=platform,
            flow_id=flow_id,
            flow_version=flow_version,
            status="in_progress",
            started_at=datetime.now().isoformat(),
        )
        self._results.append(result)
        return result

    def complete_application(
        self, result: ApplicationResult, status: str = "submitted"
    ) -> Path:
        """Mark an application as complete and save to disk."""
        result.status = status
        result.completed_at = datetime.now().isoformat()

        # Calculate duration
        if result.started_at:
            try:
                start = datetime.fromisoformat(result.started_at)
                end = datetime.fromisoformat(result.completed_at)
                result.duration_seconds = (end - start).total_seconds()
            except ValueError:
                pass

        return self._save_result(result)

    def fail_application(self, result: ApplicationResult, error: str) -> Path:
        """Mark an application as failed."""
        result.error = error
        return self.complete_application(result, status="failed")

    def skip_application(self, result: ApplicationResult, reason: str) -> Path:
        """Mark an application as skipped."""
        result.error = reason
        return self.complete_application(result, status="skipped")

    def _save_result(self, result: ApplicationResult) -> Path:
        """Save a single result to disk."""
        day_dir = paths.daily_applications_dir(self.date)
        # Sanitize job_id for filename
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in result.job_id)
        if not safe_id:
            safe_id = f"unknown_{datetime.now().strftime('%H%M%S')}"
        filepath = day_dir / f"{safe_id}.json"
        paths.save_json(filepath, result.to_dict())
        return filepath

    def get_session_summary(self) -> dict:
        """Return a summary of the current session's applications."""
        statuses: dict[str, int] = {}
        total_tokens = 0
        total_llm_calls = 0
        total_duration = 0.0

        for r in self._results:
            statuses[r.status] = statuses.get(r.status, 0) + 1
            total_tokens += r.tokens_used
            total_llm_calls += r.llm_calls
            total_duration += r.duration_seconds

        return {
            "date": self.date,
            "totalApplications": len(self._results),
            "statuses": statuses,
            "totalTokens": total_tokens,
            "totalLlmCalls": total_llm_calls,
            "totalDurationSeconds": round(total_duration, 1),
            "newQuestionsDiscovered": sum(
                sum(1 for q in r.questions_answered if q.was_new) for r in self._results
            ),
            "deviationsEncountered": sum(len(r.deviations) for r in self._results),
        }

    def load_day_results(self) -> list[ApplicationResult]:
        """Load all results for the current date from disk."""
        day_dir = paths.daily_applications_dir(self.date)
        results = []
        if day_dir.exists():
            for f in sorted(day_dir.glob("*.json")):
                if f.name == "_summary.json":
                    continue
                data = paths.load_json(f)
                if data:
                    results.append(ApplicationResult.from_dict(data))
        return results

    def save_session_summary(self) -> Path:
        """Write session summary to applications/{date}/_summary.json."""
        day_dir = paths.daily_applications_dir(self.date)
        summary_path = day_dir / "_summary.json"
        paths.save_json(summary_path, self.get_session_summary())
        return summary_path
