#!/usr/bin/env python3
"""Source performance metrics and learning hooks for auto-job-hunt.

Tracks per-source, per-search-term, and per-company performance across
sessions so the SourceAllocator can shift weight toward sources that
actually produce high-scoring, actionable jobs.

Metrics captured per session:
  - jobs_returned     : raw count of jobs from this source
  - jobs_scored       : count after scoring (non-red-flagged)
  - jobs_apply        : count with recommendation == "Apply"
  - jobs_consider     : count with recommendation == "Consider"
  - avg_score         : mean score of all scored jobs from this source
  - top_score         : max score from this source
  - response_time_ms  : how long the source took to respond (optional)
  - new_companies     : companies discovered from this source (ATS discovery)

Learning outputs:
  - source_weights    : adjusted allocation weights per priority profile
  - term_rankings     : which search terms produced the best results
  - company_rankings  : which ATS companies returned the most Apply jobs

Persistence:
  - metrics.json      : raw session history (append-only)
  - learned_weights.json : computed allocation adjustments
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_SCRIPTS_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPTS_DIR.parent
_METRICS_DIR = _SKILL_ROOT / "metrics"
_METRICS_FILE = _METRICS_DIR / "metrics.json"
_LEARNED_WEIGHTS_FILE = _METRICS_DIR / "learned_weights.json"


def _ensure_metrics_dir() -> Path:
    _METRICS_DIR.mkdir(parents=True, exist_ok=True)
    return _METRICS_DIR


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SourceMetric:
    """Performance data for a single source in a single session."""

    source: str  # "dice", "indeed", "greenhouse", etc.
    source_type: str  # "mcp" or "ats_api"
    search_term: str = ""  # which search term produced these results
    company: str = ""  # for ATS: which company/board
    jobs_returned: int = 0
    jobs_scored: int = 0
    jobs_apply: int = 0
    jobs_consider: int = 0
    jobs_skip: int = 0
    avg_score: float = 0.0
    top_score: int = 0
    response_time_ms: int = 0
    new_companies_discovered: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def yield_rate(self) -> float:
        """Percentage of returned jobs that scored Apply."""
        return (self.jobs_apply / self.jobs_returned * 100) if self.jobs_returned else 0

    @property
    def quality_score(self) -> float:
        """Composite quality metric (0-100).

        Weights:
          - 50% yield_rate (Apply jobs / returned)
          - 30% avg_score
          - 20% consider_rate (Consider / returned)
        """
        consider_rate = (
            (self.jobs_consider / self.jobs_returned * 100) if self.jobs_returned else 0
        )
        return (self.yield_rate * 0.5) + (self.avg_score * 0.3) + (consider_rate * 0.2)


@dataclass
class SessionMetrics:
    """Aggregated metrics for an entire job search session."""

    session_id: str  # timestamp-based
    timestamp: str  # ISO 8601
    request: str  # original user request
    priority: str  # contract/fulltime/diverse/premium
    roles: list[str] = field(default_factory=list)
    total_jobs_returned: int = 0
    total_jobs_scored: int = 0
    total_apply: int = 0
    total_consider: int = 0
    source_metrics: list[SourceMetric] = field(default_factory=list)
    duration_seconds: float = 0.0
    # Top-performing entries
    best_source: str = ""
    best_search_term: str = ""
    best_company: str = ""


@dataclass
class LearnedWeights:
    """Computed weight adjustments derived from historical metrics.

    These modify the base ALLOCATION_PROFILES in planner.py at runtime.
    """

    # source → adjustment multiplier (1.0 = no change, 1.5 = 50% boost, 0.5 = halved)
    source_adjustments: Dict[str, float] = field(default_factory=dict)
    # search_term → quality_score (higher = better)
    term_rankings: Dict[str, float] = field(default_factory=dict)
    # platform:company → quality_score
    company_rankings: Dict[str, float] = field(default_factory=dict)
    # priority → {source: adjusted_weight}
    adjusted_profiles: Dict[str, Dict[str, int]] = field(default_factory=dict)
    # Metadata
    sessions_analyzed: int = 0
    last_updated: str = ""
    confidence: float = 0.0  # 0-1, increases with more data


# ---------------------------------------------------------------------------
# Metrics collection
# ---------------------------------------------------------------------------


class MetricsCollector:
    """Collects source performance data during a job search session."""

    def __init__(
        self,
        request: str = "",
        priority: str = "diverse",
        roles: Optional[list[str]] = None,
    ):
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.request = request
        self.priority = priority
        self.roles = roles or []
        self._source_metrics: list[SourceMetric] = []
        self._start_time = time.time()

    def record_source(
        self,
        source: str,
        source_type: str,
        jobs: list[dict],
        search_term: str = "",
        company: str = "",
        response_time_ms: int = 0,
        new_companies: int = 0,
        errors: Optional[list[str]] = None,
    ) -> SourceMetric:
        """Record results from a single source query.

        Args:
            source: Source slug (e.g. "dice", "greenhouse").
            source_type: "mcp" or "ats_api".
            jobs: List of scored job dicts (must have 'score' and 'recommendation').
            search_term: The search term used for this query.
            company: ATS company/board slug (if applicable).
            response_time_ms: How long the query took.
            new_companies: Number of new companies discovered from results.
            errors: Any errors encountered.

        Returns:
            The recorded SourceMetric.
        """
        apply_jobs = [j for j in jobs if j.get("recommendation") == "Apply"]
        consider_jobs = [j for j in jobs if j.get("recommendation") == "Consider"]
        skip_jobs = [j for j in jobs if j.get("recommendation") == "Skip"]

        scores = [j.get("score", 0) for j in jobs if "score" in j]
        avg_score = sum(scores) / len(scores) if scores else 0.0
        top_score = max(scores) if scores else 0

        metric = SourceMetric(
            source=source,
            source_type=source_type,
            search_term=search_term,
            company=company,
            jobs_returned=len(jobs),
            jobs_scored=len([j for j in jobs if "score" in j]),
            jobs_apply=len(apply_jobs),
            jobs_consider=len(consider_jobs),
            jobs_skip=len(skip_jobs),
            avg_score=round(avg_score, 1),
            top_score=top_score,
            response_time_ms=response_time_ms,
            new_companies_discovered=new_companies,
            errors=errors or [],
        )

        self._source_metrics.append(metric)
        logger.info(
            "Recorded metrics for %s/%s: %d returned, %d apply, yield=%.1f%%",
            source,
            search_term or company or "all",
            metric.jobs_returned,
            metric.jobs_apply,
            metric.yield_rate,
        )
        return metric

    def record_source_from_scored(
        self,
        scored_jobs: list[dict],
        source_field: str = "source",
    ) -> list[SourceMetric]:
        """Auto-record metrics by grouping scored jobs by their source field.

        Useful when you have a flat list of scored jobs and want to
        break them out by source after the fact.

        Args:
            scored_jobs: List of scored job dicts.
            source_field: Field name containing the source slug.

        Returns:
            List of recorded SourceMetrics, one per source.
        """
        by_source: Dict[str, list[dict]] = {}
        for job in scored_jobs:
            src = job.get(source_field, "unknown")
            by_source.setdefault(src, []).append(job)

        metrics = []
        for src, jobs in by_source.items():
            # Infer source_type
            source_type = (
                "ats_api"
                if src
                in (
                    "greenhouse",
                    "lever",
                    "ashby",
                    "workable",
                    "smartrecruiters",
                    "bamboohr",
                )
                else "mcp"
            )

            metric = self.record_source(
                source=src,
                source_type=source_type,
                jobs=jobs,
            )
            metrics.append(metric)

        return metrics

    def finalize(self) -> SessionMetrics:
        """Finalize the session and return aggregated metrics."""
        elapsed = time.time() - self._start_time

        total_returned = sum(m.jobs_returned for m in self._source_metrics)
        total_scored = sum(m.jobs_scored for m in self._source_metrics)
        total_apply = sum(m.jobs_apply for m in self._source_metrics)
        total_consider = sum(m.jobs_consider for m in self._source_metrics)

        # Find best performers
        best_source = ""
        best_term = ""
        best_company = ""

        if self._source_metrics:
            # Best source by quality_score
            by_source: Dict[str, list[SourceMetric]] = {}
            for m in self._source_metrics:
                by_source.setdefault(m.source, []).append(m)

            source_quality = {
                src: sum(m.quality_score for m in ms) / len(ms)
                for src, ms in by_source.items()
                if any(m.jobs_returned > 0 for m in ms)
            }
            if source_quality:
                best_source = max(source_quality, key=source_quality.get)

            # Best search term by quality_score
            by_term: Dict[str, list[SourceMetric]] = {}
            for m in self._source_metrics:
                if m.search_term:
                    by_term.setdefault(m.search_term, []).append(m)

            term_quality = {
                term: sum(m.quality_score for m in ms) / len(ms)
                for term, ms in by_term.items()
                if any(m.jobs_returned > 0 for m in ms)
            }
            if term_quality:
                best_term = max(term_quality, key=term_quality.get)

            # Best company by yield_rate
            by_company: Dict[str, list[SourceMetric]] = {}
            for m in self._source_metrics:
                if m.company:
                    by_company.setdefault(f"{m.source}:{m.company}", []).append(m)

            company_quality = {
                comp: sum(m.quality_score for m in ms) / len(ms)
                for comp, ms in by_company.items()
                if any(m.jobs_returned > 0 for m in ms)
            }
            if company_quality:
                best_company = max(company_quality, key=company_quality.get)

        session = SessionMetrics(
            session_id=self.session_id,
            timestamp=datetime.now().isoformat(),
            request=self.request,
            priority=self.priority,
            roles=self.roles,
            total_jobs_returned=total_returned,
            total_jobs_scored=total_scored,
            total_apply=total_apply,
            total_consider=total_consider,
            source_metrics=self._source_metrics,
            duration_seconds=round(elapsed, 1),
            best_source=best_source,
            best_search_term=best_term,
            best_company=best_company,
        )

        return session


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def save_session_metrics(session: SessionMetrics) -> Path:
    """Append session metrics to the metrics history file.

    Returns:
        Path to the metrics file.
    """
    _ensure_metrics_dir()

    # Load existing history
    history: list[dict] = []
    if _METRICS_FILE.exists():
        try:
            history = json.loads(_METRICS_FILE.read_text())
            if not isinstance(history, list):
                history = []
        except json.JSONDecodeError:
            history = []

    # Serialize session
    session_data = {
        "session_id": session.session_id,
        "timestamp": session.timestamp,
        "request": session.request,
        "priority": session.priority,
        "roles": session.roles,
        "total_jobs_returned": session.total_jobs_returned,
        "total_jobs_scored": session.total_jobs_scored,
        "total_apply": session.total_apply,
        "total_consider": session.total_consider,
        "duration_seconds": session.duration_seconds,
        "best_source": session.best_source,
        "best_search_term": session.best_search_term,
        "best_company": session.best_company,
        "source_metrics": [asdict(m) for m in session.source_metrics],
    }

    history.append(session_data)

    # Keep last 100 sessions to prevent unbounded growth
    if len(history) > 100:
        history = history[-100:]

    _METRICS_FILE.write_text(json.dumps(history, indent=2))
    logger.info("Saved session metrics: %s", session.session_id)
    return _METRICS_FILE


def load_session_history(limit: int = 50) -> list[dict]:
    """Load recent session history.

    Args:
        limit: Max number of sessions to return (most recent first).

    Returns:
        List of session dicts, newest first.
    """
    if not _METRICS_FILE.exists():
        return []

    try:
        history = json.loads(_METRICS_FILE.read_text())
        if not isinstance(history, list):
            return []
        return list(reversed(history[-limit:]))
    except json.JSONDecodeError:
        return []


# ---------------------------------------------------------------------------
# Learning engine
# ---------------------------------------------------------------------------


def compute_learned_weights(
    min_sessions: int = 3,
    decay_factor: float = 0.9,
) -> LearnedWeights:
    """Analyze historical metrics and compute weight adjustments.

    The learning algorithm:
    1. Load the last N sessions from metrics.json
    2. For each source, compute an exponentially-weighted quality_score
       (recent sessions count more than older ones)
    3. Convert quality scores to adjustment multipliers:
       - Sources consistently above average get a boost (up to 1.5x)
       - Sources consistently below average get dampened (down to 0.5x)
       - Sources with no data stay at 1.0x
    4. Rank search terms and companies by their quality scores
    5. Optionally recompute adjusted allocation profiles

    Args:
        min_sessions: Minimum sessions needed before adjustments are made.
        decay_factor: Exponential decay for older sessions (0-1).
                      0.9 means the previous session counts 90% as much.

    Returns:
        LearnedWeights with adjustments and rankings.
    """
    history = load_session_history(limit=50)

    learned = LearnedWeights(
        last_updated=datetime.now().isoformat(),
        sessions_analyzed=len(history),
    )

    if len(history) < min_sessions:
        learned.confidence = len(history) / min_sessions
        logger.info(
            "Not enough sessions for learning (%d/%d). Confidence: %.1f",
            len(history),
            min_sessions,
            learned.confidence,
        )
        return learned

    # ------------------------------------------------------------------
    # Step 1: Compute weighted quality scores per source
    # ------------------------------------------------------------------
    source_scores: Dict[
        str, list[tuple[float, float]]
    ] = {}  # source → [(quality, weight)]
    term_scores: Dict[str, list[tuple[float, float]]] = {}
    company_scores: Dict[str, list[tuple[float, float]]] = {}

    for i, session in enumerate(history):
        session_weight = decay_factor**i  # More recent = higher weight

        for sm_data in session.get("source_metrics", []):
            sm = SourceMetric(
                **{
                    k: v
                    for k, v in sm_data.items()
                    if k in SourceMetric.__dataclass_fields__
                }
            )

            if sm.jobs_returned == 0:
                continue

            q = sm.quality_score

            # Source aggregation
            source_scores.setdefault(sm.source, []).append((q, session_weight))

            # Term aggregation
            if sm.search_term:
                term_scores.setdefault(sm.search_term, []).append((q, session_weight))

            # Company aggregation
            if sm.company:
                key = f"{sm.source}:{sm.company}"
                company_scores.setdefault(key, []).append((q, session_weight))

    # ------------------------------------------------------------------
    # Step 2: Compute weighted averages
    # ------------------------------------------------------------------
    def weighted_avg(scores: list[tuple[float, float]]) -> float:
        total_weight = sum(w for _, w in scores)
        if total_weight == 0:
            return 0.0
        return sum(q * w for q, w in scores) / total_weight

    source_quality = {
        src: weighted_avg(scores) for src, scores in source_scores.items()
    }
    term_quality = {term: weighted_avg(scores) for term, scores in term_scores.items()}
    company_quality = {
        comp: weighted_avg(scores) for comp, scores in company_scores.items()
    }

    # ------------------------------------------------------------------
    # Step 3: Convert to adjustment multipliers
    # ------------------------------------------------------------------
    if source_quality:
        avg_quality = sum(source_quality.values()) / len(source_quality)
        if avg_quality > 0:
            for src, q in source_quality.items():
                ratio = q / avg_quality
                # Clamp to [0.5, 1.5] range
                adjustment = max(0.5, min(1.5, ratio))
                learned.source_adjustments[src] = round(adjustment, 2)
        else:
            for src in source_quality:
                learned.source_adjustments[src] = 1.0

    # ------------------------------------------------------------------
    # Step 4: Rank terms and companies
    # ------------------------------------------------------------------
    learned.term_rankings = {
        k: round(v, 1) for k, v in sorted(term_quality.items(), key=lambda x: -x[1])
    }
    learned.company_rankings = {
        k: round(v, 1) for k, v in sorted(company_quality.items(), key=lambda x: -x[1])
    }

    # ------------------------------------------------------------------
    # Step 5: Compute adjusted allocation profiles
    # ------------------------------------------------------------------
    try:
        import sys

        if str(_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS_DIR))
        from planner import ALLOCATION_PROFILES

        for priority, profile in ALLOCATION_PROFILES.items():
            adjusted = {}
            for source, base_weight in profile.items():
                multiplier = learned.source_adjustments.get(source, 1.0)
                adjusted[source] = max(0, int(base_weight * multiplier))
            learned.adjusted_profiles[priority] = adjusted
    except ImportError:
        logger.warning("Could not import ALLOCATION_PROFILES for adjustment")

    # Confidence increases with more data (caps at 1.0 at 20+ sessions)
    learned.confidence = min(1.0, len(history) / 20)

    return learned


def save_learned_weights(weights: LearnedWeights) -> Path:
    """Persist learned weights to disk.

    Returns:
        Path to the learned weights file.
    """
    _ensure_metrics_dir()

    data = {
        "source_adjustments": weights.source_adjustments,
        "term_rankings": weights.term_rankings,
        "company_rankings": weights.company_rankings,
        "adjusted_profiles": weights.adjusted_profiles,
        "sessions_analyzed": weights.sessions_analyzed,
        "last_updated": weights.last_updated,
        "confidence": weights.confidence,
    }

    _LEARNED_WEIGHTS_FILE.write_text(json.dumps(data, indent=2))
    logger.info(
        "Saved learned weights (confidence=%.2f, sessions=%d)",
        weights.confidence,
        weights.sessions_analyzed,
    )
    return _LEARNED_WEIGHTS_FILE


def load_learned_weights() -> Optional[LearnedWeights]:
    """Load previously computed weights from disk.

    Returns:
        LearnedWeights or None if no file exists.
    """
    if not _LEARNED_WEIGHTS_FILE.exists():
        return None

    try:
        data = json.loads(_LEARNED_WEIGHTS_FILE.read_text())
        return LearnedWeights(
            source_adjustments=data.get("source_adjustments", {}),
            term_rankings=data.get("term_rankings", {}),
            company_rankings=data.get("company_rankings", {}),
            adjusted_profiles=data.get("adjusted_profiles", {}),
            sessions_analyzed=data.get("sessions_analyzed", 0),
            last_updated=data.get("last_updated", ""),
            confidence=data.get("confidence", 0.0),
        )
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Failed to load learned weights: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Integration helpers
# ---------------------------------------------------------------------------


def get_adjusted_profile(priority: str) -> Optional[Dict[str, int]]:
    """Get learned allocation profile for a priority, if available.

    This is the main integration point with planner.py's SourceAllocator.
    If confidence is high enough (>= 0.5), returns the adjusted profile.
    Otherwise returns None (use defaults).

    Args:
        priority: "contract", "fulltime", "diverse", or "premium".

    Returns:
        Adjusted weight dict {source: weight} or None.
    """
    weights = load_learned_weights()
    if weights is None:
        return None
    if weights.confidence < 0.5:
        logger.debug(
            "Learned weights confidence too low (%.2f), using defaults",
            weights.confidence,
        )
        return None

    return weights.adjusted_profiles.get(priority)


def get_top_search_terms(n: int = 5) -> list[str]:
    """Return the top N search terms by historical quality.

    Useful for prioritizing search terms when the user doesn't specify.

    Args:
        n: Number of top terms to return.

    Returns:
        List of search term strings, best first.
    """
    weights = load_learned_weights()
    if weights is None or not weights.term_rankings:
        return []

    return list(weights.term_rankings.keys())[:n]


def get_top_companies(platform: str, n: int = 10) -> list[str]:
    """Return the top N companies for a platform by historical quality.

    Args:
        platform: ATS platform slug.
        n: Number of top companies to return.

    Returns:
        List of company slugs, best first.
    """
    weights = load_learned_weights()
    if weights is None or not weights.company_rankings:
        return []

    prefix = f"{platform}:"
    matching = [
        (key.split(":", 1)[1], score)
        for key, score in weights.company_rankings.items()
        if key.startswith(prefix)
    ]
    matching.sort(key=lambda x: -x[1])
    return [slug for slug, _ in matching[:n]]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def metrics_summary(session: Optional[SessionMetrics] = None) -> str:
    """Generate a human-readable metrics report.

    If a session is provided, reports on that session.
    Otherwise reports on overall history.

    Args:
        session: Optional specific session to report on.

    Returns:
        Formatted string report.
    """
    lines = []

    if session:
        lines.extend(
            [
                "Session Metrics Report",
                "=" * 50,
                f"Session: {session.session_id}",
                f"Request: {session.request}",
                f"Priority: {session.priority}",
                f"Roles: {', '.join(session.roles)}",
                f"Duration: {session.duration_seconds}s",
                "",
                f"Total returned: {session.total_jobs_returned}",
                f"Total scored:   {session.total_jobs_scored}",
                f"Apply:          {session.total_apply}",
                f"Consider:       {session.total_consider}",
                "",
                f"Best source:      {session.best_source or 'N/A'}",
                f"Best search term: {session.best_search_term or 'N/A'}",
                f"Best company:     {session.best_company or 'N/A'}",
                "",
                "Source Breakdown:",
                "-" * 50,
                f"{'Source':<18s} {'Type':<8s} {'Ret':>4s} {'Apply':>5s} "
                f"{'Yield':>6s} {'AvgSc':>5s} {'Quality':>7s}",
                "-" * 50,
            ]
        )

        for m in session.source_metrics:
            lines.append(
                f"{m.source:<18s} {m.source_type:<8s} {m.jobs_returned:4d} "
                f"{m.jobs_apply:5d} {m.yield_rate:5.1f}% "
                f"{m.avg_score:5.1f} {m.quality_score:6.1f}"
            )

    else:
        # Overall history report
        history = load_session_history(limit=20)
        weights = load_learned_weights()

        lines.extend(
            [
                "Source Performance History",
                "=" * 50,
                f"Sessions analyzed: {len(history)}",
            ]
        )

        if weights:
            lines.extend(
                [
                    f"Learning confidence: {weights.confidence:.0%}",
                    "",
                    "Source Adjustments (1.0 = baseline):",
                    "-" * 40,
                ]
            )
            for src, adj in sorted(
                weights.source_adjustments.items(), key=lambda x: -x[1]
            ):
                bar = (
                    "+" * int((adj - 1.0) * 20)
                    if adj >= 1.0
                    else "-" * int((1.0 - adj) * 20)
                )
                lines.append(f"  {src:<18s} {adj:.2f}x  {bar}")

            if weights.term_rankings:
                lines.extend(
                    [
                        "",
                        "Top Search Terms:",
                        "-" * 40,
                    ]
                )
                for term, score in list(weights.term_rankings.items())[:10]:
                    lines.append(f"  {score:5.1f}  {term}")

            if weights.company_rankings:
                lines.extend(
                    [
                        "",
                        "Top Companies:",
                        "-" * 40,
                    ]
                )
                for comp, score in list(weights.company_rankings.items())[:10]:
                    lines.append(f"  {score:5.1f}  {comp}")

        else:
            lines.append("\nNo learned weights yet. Run more searches to build data.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Post-session hook: the main entry point called after each search session
# ---------------------------------------------------------------------------


def post_session_hook(
    scored_jobs: list[dict],
    request: str = "",
    priority: str = "diverse",
    roles: Optional[list[str]] = None,
    recompute: bool = True,
) -> Dict[str, Any]:
    """Main hook to call after each job search session completes.

    This is the single integration point for run.py. Call it after scoring
    is done and before returning results to the user.

    Steps:
    1. Create a MetricsCollector and auto-record from scored jobs
    2. Finalize the session
    3. Save session metrics to history
    4. Optionally recompute learned weights
    5. Return a summary dict

    Args:
        scored_jobs: List of scored job dicts (with 'score', 'recommendation',
                     'source' fields).
        request: The original user request string.
        priority: The priority used for this session.
        roles: Target roles.
        recompute: If True, recompute learned weights after saving.

    Returns:
        Dict with 'session_id', 'summary', 'metrics_path', 'weights_path'.
    """
    collector = MetricsCollector(
        request=request,
        priority=priority,
        roles=roles,
    )

    # Auto-record by source
    collector.record_source_from_scored(scored_jobs)

    # Finalize
    session = collector.finalize()

    # Save
    metrics_path = save_session_metrics(session)

    # Recompute weights
    weights_path = None
    if recompute:
        weights = compute_learned_weights()
        weights_path = save_learned_weights(weights)

    summary = metrics_summary(session)

    return {
        "session_id": session.session_id,
        "summary": summary,
        "metrics_path": str(metrics_path),
        "weights_path": str(weights_path) if weights_path else None,
        "total_returned": session.total_jobs_returned,
        "total_apply": session.total_apply,
        "best_source": session.best_source,
        "best_search_term": session.best_search_term,
    }


# ---------------------------------------------------------------------------
# CLI test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Quick self-test with dummy data
    test_jobs = [
        {
            "title": "ML Engineer",
            "source": "dice",
            "score": 82,
            "recommendation": "Apply",
            "searchTerm": "machine learning engineer",
        },
        {
            "title": "AI Developer",
            "source": "dice",
            "score": 71,
            "recommendation": "Apply",
            "searchTerm": "AI developer",
        },
        {
            "title": "Data Scientist",
            "source": "indeed",
            "score": 55,
            "recommendation": "Consider",
            "searchTerm": "data scientist",
        },
        {
            "title": "Backend Engineer",
            "source": "greenhouse",
            "score": 78,
            "recommendation": "Apply",
            "searchTerm": "python backend",
            "company": "stripe",
        },
        {
            "title": "Full Stack Dev",
            "source": "lever",
            "score": 45,
            "recommendation": "Skip",
            "searchTerm": "full stack",
            "company": "netflix",
        },
    ]

    result = post_session_hook(
        scored_jobs=test_jobs,
        request="Get 50 jobs for ML Engineer",
        priority="fulltime",
        roles=["ML Engineer"],
    )

    print(result["summary"])
    print(f"\nMetrics saved to: {result['metrics_path']}")
    if result["weights_path"]:
        print(f"Weights saved to: {result['weights_path']}")
