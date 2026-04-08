"""
Duplicate application checker.

Prevents applying to the same job twice by maintaining an index at:
  {workspace}/applications/_index.json

Index structure:
  {
    "version": "1.0.0",
    "applications": [
      {
        "jobId": "abc123",
        "url": "https://...",
        "company": "Acme",
        "title": "ML Engineer",
        "appliedAt": "2026-04-07T10:30:00",
        "status": "submitted",  // submitted | failed | skipped | duplicate
        "platform": "greenhouse",
        "flowId": "greenhouse",
        "notes": ""
      }
    ]
  }

Dedup checks:
  1. Exact job ID match
  2. URL fuzzy match (ignore query params, trailing slashes)
  3. Company + title exact match (catches reposts)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse, urljoin

import paths


@dataclass
class ApplicationRecord:
    """A record of a single application attempt."""

    job_id: str
    url: str
    company: str
    title: str
    applied_at: str
    status: str  # "submitted", "failed", "skipped", "duplicate"
    platform: str = ""
    flow_id: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "jobId": self.job_id,
            "url": self.url,
            "company": self.company,
            "title": self.title,
            "appliedAt": self.applied_at,
            "status": self.status,
            "platform": self.platform,
            "flowId": self.flow_id,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ApplicationRecord:
        return cls(
            job_id=data.get("jobId", ""),
            url=data.get("url", ""),
            company=data.get("company", ""),
            title=data.get("title", ""),
            applied_at=data.get("appliedAt", ""),
            status=data.get("status", ""),
            platform=data.get("platform", ""),
            flow_id=data.get("flowId", ""),
            notes=data.get("notes", ""),
        )


def _normalize_url(url: str) -> str:
    """Normalize a URL for comparison: strip query params, trailing slash, lowercase."""
    parsed = urlparse(url.lower().strip())
    # Keep scheme + host + path, strip query/fragment
    path = parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def _company_title_key(company: str, title: str) -> str:
    """Create a normalized key from company + title."""
    c = re.sub(r"[^a-z0-9]", "", company.lower())
    t = re.sub(r"[^a-z0-9]", "", title.lower())
    return f"{c}::{t}"


class DedupChecker:
    """Checks for duplicate applications before applying."""

    def __init__(self):
        self._index: dict = {}
        self._records: list[ApplicationRecord] = []
        self._load()

    def _load(self) -> None:
        """Load the applications index."""
        self._index = paths.load_json(paths.applications_index_path())
        if not self._index:
            self._index = {"version": "1.0.0", "applications": []}
        self._records = [
            ApplicationRecord.from_dict(r) for r in self._index.get("applications", [])
        ]

    def _save(self) -> None:
        """Persist the applications index."""
        self._index["applications"] = [r.to_dict() for r in self._records]
        paths.save_json(paths.applications_index_path(), self._index)

    def is_duplicate(
        self, job_id: str = "", url: str = "", company: str = "", title: str = ""
    ) -> tuple[bool, Optional[ApplicationRecord]]:
        """Check if a job has already been applied to.

        Returns (is_dup, existing_record).
        Checks in order: job ID, URL fuzzy, company+title.
        """
        # 1. Exact job ID match
        if job_id:
            for rec in self._records:
                if rec.job_id and rec.job_id == job_id:
                    return (True, rec)

        # 2. URL fuzzy match
        if url:
            norm_url = _normalize_url(url)
            for rec in self._records:
                if rec.url and _normalize_url(rec.url) == norm_url:
                    return (True, rec)

        # 3. Company + title exact match
        if company and title:
            key = _company_title_key(company, title)
            for rec in self._records:
                if rec.company and rec.title:
                    if _company_title_key(rec.company, rec.title) == key:
                        return (True, rec)

        return (False, None)

    def record_application(
        self,
        job_id: str,
        url: str,
        company: str,
        title: str,
        status: str,
        platform: str = "",
        flow_id: str = "",
        notes: str = "",
    ) -> ApplicationRecord:
        """Record a new application attempt and save index."""
        rec = ApplicationRecord(
            job_id=job_id,
            url=url,
            company=company,
            title=title,
            applied_at=datetime.now().isoformat(),
            status=status,
            platform=platform,
            flow_id=flow_id,
            notes=notes,
        )
        self._records.append(rec)
        self._save()
        return rec

    def get_stats(self) -> dict[str, int]:
        """Return counts by status."""
        stats: dict[str, int] = {}
        for rec in self._records:
            stats[rec.status] = stats.get(rec.status, 0) + 1
        stats["total"] = len(self._records)
        return stats

    def get_today_count(self) -> int:
        """Number of applications submitted today."""
        today = datetime.now().strftime("%Y-%m-%d")
        return sum(
            1
            for r in self._records
            if r.applied_at.startswith(today) and r.status == "submitted"
        )

    def get_recent(self, n: int = 10) -> list[ApplicationRecord]:
        """Return the N most recent application records."""
        return list(reversed(self._records[-n:]))
