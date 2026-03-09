"""Playbook data model — versioned, executable documents with action-bound steps."""

import yaml
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path


@dataclass
class ParamSource:
    from_: str  # "trigger_ticket", "calculation", "user_input"
    field: Optional[str] = None
    extract: Optional[str] = None
    calculate: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ParamSource":
        return cls(from_=d.get("from", ""), field=d.get("field"), extract=d.get("extract"), calculate=d.get("calculate"))

    def to_dict(self) -> dict:
        d = {"from": self.from_}
        if self.field:
            d["field"] = self.field
        if self.extract:
            d["extract"] = self.extract
        if self.calculate:
            d["calculate"] = self.calculate
        return d


@dataclass
class ActionBinding:
    tool: str
    params: dict = field(default_factory=dict)
    param_sources: dict = field(default_factory=dict)  # key -> ParamSource
    navigate_to: Optional[str] = None
    prefill: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "ActionBinding":
        param_sources = {}
        for k, v in d.get("param_sources", {}).items():
            param_sources[k] = ParamSource.from_dict(v)
        return cls(
            tool=d["tool"],
            params=d.get("params", {}),
            param_sources=param_sources,
            navigate_to=d.get("navigate_to"),
            prefill=d.get("prefill", []),
        )

    def to_dict(self) -> dict:
        d = {"tool": self.tool}
        if self.params:
            d["params"] = self.params
        if self.param_sources:
            d["param_sources"] = {k: v.to_dict() for k, v in self.param_sources.items()}
        if self.navigate_to:
            d["navigate_to"] = self.navigate_to
        if self.prefill:
            d["prefill"] = self.prefill
        return d


@dataclass
class PlaybookStep:
    id: int
    name: str
    action: ActionBinding
    auth_required: bool = False
    auth_method: Optional[str] = None  # "stored_session", "human_handoff"
    human_required: bool = False
    optional: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "PlaybookStep":
        return cls(
            id=d["id"],
            name=d["name"],
            action=ActionBinding.from_dict(d["action"]),
            auth_required=d.get("auth_required", False),
            auth_method=d.get("auth_method"),
            human_required=d.get("human_required", False),
            optional=d.get("optional", False),
        )

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "action": self.action.to_dict(),
            "auth_required": self.auth_required,
            "human_required": self.human_required,
        }
        if self.auth_method:
            d["auth_method"] = self.auth_method
        if self.optional:
            d["optional"] = self.optional
        return d


@dataclass
class TriggerPattern:
    ticket_type: Optional[str] = None
    keywords: list = field(default_factory=list)
    source: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "TriggerPattern":
        return cls(ticket_type=d.get("ticket_type"), keywords=d.get("keywords", []), source=d.get("source", []))

    def matches(self, ticket_type: str = "", text: str = "", source: str = "") -> bool:
        if self.ticket_type and self.ticket_type.lower() != ticket_type.lower():
            return False
        if self.source and source.lower() not in [s.lower() for s in self.source]:
            return False
        if self.keywords:
            text_lower = text.lower()
            if not any(kw.lower() in text_lower for kw in self.keywords):
                return False
        return True

    def to_dict(self) -> dict:
        d = {}
        if self.ticket_type:
            d["ticket_type"] = self.ticket_type
        if self.keywords:
            d["keywords"] = self.keywords
        if self.source:
            d["source"] = self.source
        return d


CONFIDENCE_ORDER = ["low", "medium", "high"]


@dataclass
class Playbook:
    id: str
    name: str
    version: int
    confidence: str  # low, medium, high
    trigger_patterns: list  # list of TriggerPattern
    created_from: str  # session, dictated, pattern-detection
    executions: int
    steps: list  # list of PlaybookStep
    last_executed: Optional[str] = None
    last_updated: Optional[str] = None
    update_history: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> "Playbook":
        triggers = [TriggerPattern.from_dict(t) for t in d.get("trigger_patterns", [])]
        steps = [PlaybookStep.from_dict(s) for s in d.get("steps", [])]
        return cls(
            id=d["id"],
            name=d["name"],
            version=d.get("version", 1),
            confidence=d.get("confidence", "low"),
            trigger_patterns=triggers,
            created_from=d.get("created_from", "session"),
            executions=d.get("executions", 0),
            steps=steps,
            last_executed=d.get("last_executed"),
            last_updated=d.get("last_updated"),
            update_history=d.get("update_history", []),
        )

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "confidence": self.confidence,
            "trigger_patterns": [t.to_dict() for t in self.trigger_patterns],
            "created_from": self.created_from,
            "executions": self.executions,
            "steps": [s.to_dict() for s in self.steps],
        }
        if self.last_executed:
            d["last_executed"] = self.last_executed
        if self.last_updated:
            d["last_updated"] = self.last_updated
        if self.update_history:
            d["update_history"] = self.update_history
        return d

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=False, sort_keys=False)

    @classmethod
    def load(cls, path: str) -> "Playbook":
        with open(path) as f:
            return cls.from_dict(yaml.safe_load(f))

    def matches(self, ticket_type: str = "", text: str = "", source: str = "") -> bool:
        return any(t.matches(ticket_type, text, source) for t in self.trigger_patterns)

    def record_execution(self, success: bool) -> None:
        self.executions += 1
        if success:
            idx = CONFIDENCE_ORDER.index(self.confidence)
            if self.executions >= 3 and idx < 2:
                self.confidence = "high"
            elif self.executions >= 1 and idx < 1:
                self.confidence = "medium"
        else:
            idx = CONFIDENCE_ORDER.index(self.confidence)
            if idx > 0:
                self.confidence = CONFIDENCE_ORDER[idx - 1]
