"""
Flow graph engine for job application automation.

Concepts:
  FlowNode  - A screen/state in an application form (landing, form, review, etc.)
  FlowEdge  - A transition between nodes (click next, submit, etc.)
  FlowGraph - A complete application flow for a platform (LinkedIn, Greenhouse, etc.)
  FlowRegistry - Index of all available flows with URL-pattern matching

Flow graphs are stored as JSON at:
  {repo_root}/.agents/skills/flow-applicator/flows/

When the agent encounters a page that doesn't match any known node,
it creates a "sister node" — a variant attached to the parent via a
condition, preserving the main flow while extending coverage.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import paths


# ── Data Classes ───────────────────────────────────────────────────


@dataclass
class FlowNode:
    """A single screen/state in an application flow."""

    id: str
    type: str  # "page", "form", "review", "confirmation", "error"
    description: str = ""
    url_pattern: str = ""
    fields: list[str] = field(default_factory=list)
    elements: dict[str, Any] = field(default_factory=dict)
    next_button: str = ""
    submit_button: str = ""
    wait_for: str = ""
    # Sister nodes for deviations
    sisters: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        # Clean empty values
        return {k: v for k, v in d.items() if v}

    @classmethod
    def from_dict(cls, node_id: str, data: dict) -> FlowNode:
        return cls(
            id=node_id,
            type=data.get("type", "form"),
            description=data.get("description", ""),
            url_pattern=data.get("urlPattern", ""),
            fields=data.get("fields", []),
            elements=data.get("elements", {}),
            next_button=data.get("nextButton", ""),
            submit_button=data.get("submitButton", ""),
            wait_for=data.get("waitFor", ""),
            sisters=data.get("sisters", []),
        )


@dataclass
class FlowEdge:
    """A transition between two nodes."""

    from_node: str
    to_node: str
    trigger: str  # "click_apply", "click_next", "click_submit", "auto_redirect"
    condition: str = ""  # Optional condition for branching

    def to_dict(self) -> dict:
        d = {"from": self.from_node, "to": self.to_node, "trigger": self.trigger}
        if self.condition:
            d["condition"] = self.condition
        return d

    @classmethod
    def from_dict(cls, data: dict) -> FlowEdge:
        return cls(
            from_node=data["from"],
            to_node=data["to"],
            trigger=data["trigger"],
            condition=data.get("condition", ""),
        )


@dataclass
class FieldMapping:
    """Maps a form field to a profile/template data source."""

    field_name: str
    source: str  # "profile", "role", "template", "generated"
    source_field: str

    def to_dict(self) -> dict:
        return {"source": self.source, "field": self.source_field}

    @classmethod
    def from_dict(cls, field_name: str, data: dict) -> FieldMapping:
        return cls(
            field_name=field_name,
            source=data["source"],
            source_field=data["field"],
        )


@dataclass
class CommonQuestion:
    """A known question with a pre-defined answer."""

    question: str
    answer: str
    match_type: str = "fuzzy"  # "exact", "fuzzy", "regex"

    def to_dict(self) -> dict:
        d = {"question": self.question, "answer": self.answer}
        if self.match_type != "fuzzy":
            d["matchType"] = self.match_type
        return d

    @classmethod
    def from_dict(cls, data: dict) -> CommonQuestion:
        return cls(
            question=data["question"],
            answer=data["answer"],
            match_type=data.get("matchType", "fuzzy"),
        )


@dataclass
class FlowGraph:
    """A complete application flow for a platform."""

    flow_id: str
    version: str
    platform: str
    platform_type: str  # "easy_apply", "ats", "custom"
    description: str
    nodes: dict[str, FlowNode] = field(default_factory=dict)
    edges: list[FlowEdge] = field(default_factory=list)
    field_mappings: dict[str, FieldMapping] = field(default_factory=dict)
    common_questions: list[CommonQuestion] = field(default_factory=list)
    known_fields: dict[str, dict] = field(default_factory=dict)
    platform_notes: dict[str, Any] = field(default_factory=dict)

    def get_node(self, node_id: str) -> Optional[FlowNode]:
        return self.nodes.get(node_id)

    def get_start_node(self) -> Optional[FlowNode]:
        """Return the entry point node (usually 'landing')."""
        if "landing" in self.nodes:
            return self.nodes["landing"]
        # Fallback: find node that has no incoming edges
        targets = {e.to_node for e in self.edges}
        for nid, node in self.nodes.items():
            if nid not in targets:
                return node
        return None

    def get_next_node(self, current_id: str) -> Optional[FlowNode]:
        """Get the default next node from the current node."""
        for edge in self.edges:
            if edge.from_node == current_id and not edge.condition:
                return self.nodes.get(edge.to_node)
        return None

    def get_edges_from(self, node_id: str) -> list[FlowEdge]:
        return [e for e in self.edges if e.from_node == node_id]

    def get_field_mapping(self, field_name: str) -> Optional[FieldMapping]:
        return self.field_mappings.get(field_name)

    def find_answer(self, question_text: str) -> Optional[str]:
        """Search common questions for a fuzzy match."""
        q_lower = question_text.lower().strip()
        for cq in self.common_questions:
            cq_lower = cq.question.lower().strip()
            if cq.match_type == "exact" and q_lower == cq_lower:
                return cq.answer
            elif cq.match_type == "regex":
                if re.search(cq.question, question_text, re.IGNORECASE):
                    return cq.answer
            else:  # fuzzy
                # Check containment both ways + token overlap
                if cq_lower in q_lower or q_lower in cq_lower:
                    return cq.answer
                q_tokens = set(q_lower.split())
                cq_tokens = set(cq_lower.split())
                overlap = len(q_tokens & cq_tokens) / max(len(cq_tokens), 1)
                if overlap >= 0.7:
                    return cq.answer
        return None

    def add_sister_node(
        self,
        parent_id: str,
        sister_id: str,
        condition: str,
        node_data: dict,
    ) -> FlowNode:
        """Add a sister (variant) node under a parent for deviations."""
        sister = FlowNode.from_dict(sister_id, node_data)
        parent = self.nodes.get(parent_id)
        if parent:
            parent.sisters.append(
                {
                    "id": sister_id,
                    "condition": condition,
                    "node": node_data,
                }
            )
        self.nodes[sister_id] = sister
        return sister

    def add_common_question(self, question: str, answer: str) -> None:
        """Add a new common question (dedup by question text)."""
        for cq in self.common_questions:
            if cq.question.lower().strip() == question.lower().strip():
                cq.answer = answer  # Update existing
                return
        self.common_questions.append(CommonQuestion(question=question, answer=answer))

    def to_dict(self) -> dict:
        return {
            "flowId": self.flow_id,
            "version": self.version,
            "platform": self.platform,
            "platformType": self.platform_type,
            "description": self.description,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "fieldMappings": {
                fn: fm.to_dict() for fn, fm in self.field_mappings.items()
            },
            "commonQuestions": [cq.to_dict() for cq in self.common_questions],
            "knownFields": self.known_fields,
            "platformNotes": self.platform_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> FlowGraph:
        nodes = {}
        for nid, ndata in data.get("nodes", {}).items():
            nodes[nid] = FlowNode.from_dict(nid, ndata)

        edges = [FlowEdge.from_dict(e) for e in data.get("edges", [])]

        field_mappings = {}
        for fn, fm_data in data.get("fieldMappings", {}).items():
            field_mappings[fn] = FieldMapping.from_dict(fn, fm_data)

        common_questions = [
            CommonQuestion.from_dict(cq) for cq in data.get("commonQuestions", [])
        ]

        return cls(
            flow_id=data["flowId"],
            version=data.get("version", "1.0.0"),
            platform=data["platform"],
            platform_type=data.get("platformType", "ats"),
            description=data.get("description", ""),
            nodes=nodes,
            edges=edges,
            field_mappings=field_mappings,
            common_questions=common_questions,
            known_fields=data.get("knownFields", {}),
            platform_notes=data.get("platformNotes", {}),
        )

    def save(self) -> Path:
        """Persist this flow graph to the global flows directory."""
        p = paths.flow_path(self.flow_id)
        paths.save_json(p, self.to_dict())
        return p

    @classmethod
    def load(cls, flow_id: str) -> Optional[FlowGraph]:
        """Load a flow graph from the global flows directory."""
        p = paths.flow_path(flow_id)
        data = paths.load_json(p)
        if not data:
            return None
        return cls.from_dict(data)


# ── Flow Registry ──────────────────────────────────────────────────


class FlowRegistry:
    """Index of all available flows with URL-to-platform matching."""

    def __init__(self):
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        self._data = paths.load_json(paths.registry_path())

    def save(self) -> None:
        paths.save_json(paths.registry_path(), self._data)

    @property
    def registry(self) -> dict:
        return self._data.get("registry", {})

    @property
    def flows(self) -> list[dict]:
        return self.registry.get("flows", [])

    @property
    def platform_patterns(self) -> dict[str, list[str]]:
        return self.registry.get("platformPatterns", {})

    def detect_platform(self, url: str) -> Optional[str]:
        """Match a URL against known platform patterns.

        Returns the platform name (e.g. "greenhouse") or None.
        """
        url_lower = url.lower()
        for platform, patterns in self.platform_patterns.items():
            for pattern in patterns:
                if pattern.lower() in url_lower:
                    return platform
        return None

    def get_flow_id(self, platform: str) -> Optional[str]:
        """Get the flow ID for a platform."""
        for flow_entry in self.flows:
            if flow_entry.get("platform") == platform:
                return flow_entry.get("flowId")
        return None

    def get_flow_for_url(self, url: str) -> Optional[FlowGraph]:
        """Detect platform from URL and load the corresponding flow."""
        platform = self.detect_platform(url)
        if not platform:
            return None
        flow_id = self.get_flow_id(platform)
        if not flow_id:
            return None
        return FlowGraph.load(flow_id)

    def list_platforms(self) -> list[str]:
        return list(self.platform_patterns.keys())

    def list_flows(self) -> list[dict]:
        return self.flows

    def add_flow_entry(self, entry: dict) -> None:
        """Add or update a flow entry in the registry."""
        flows = self.registry.setdefault("flows", [])
        for i, existing in enumerate(flows):
            if existing.get("flowId") == entry.get("flowId"):
                flows[i] = entry
                self.save()
                return
        flows.append(entry)
        self.save()

    def add_platform_pattern(self, platform: str, pattern: str) -> None:
        """Add a URL pattern for a platform."""
        patterns = self.registry.setdefault("platformPatterns", {})
        plist = patterns.setdefault(platform, [])
        if pattern not in plist:
            plist.append(pattern)
            self.save()
