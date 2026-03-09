"""Playbook Extractor — converts workflow traces into draft playbooks."""

import re
from typing import Optional
from models import Playbook, PlaybookStep, ActionBinding, ParamSource, TriggerPattern
from registry import ToolRegistry


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class PlaybookExtractor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry
        self.pending_default_updates: list = []  # rules that should update tool defaults

    def extract_from_trace(self, trace: dict, name: str) -> Playbook:
        events = trace.get("events", [])
        steps = []
        step_id = 1

        for event in events:
            etype = event.get("type")

            if etype == "tool_call":
                step = self._step_from_tool_call(event, step_id)
                if step:
                    steps.append(step)
                    step_id += 1

            elif etype == "user_manual_action":
                step = self._step_from_manual_action(event, step_id)
                steps.append(step)
                step_id += 1

            elif etype in ("user_instruction", "user_rule"):
                if event.get("persist"):
                    self.pending_default_updates.append({
                        "content": event.get("content", ""),
                        "applies_to": event.get("applies_to", []),
                    })

        # Infer trigger patterns from first user_instruction
        trigger_patterns = []
        for event in events:
            if event.get("type") == "user_instruction" and event.get("content"):
                content = event["content"]
                keywords = self._extract_keywords(content)
                if keywords:
                    trigger_patterns.append(TriggerPattern(keywords=keywords, source=["freshservice", "jira"]))
                break

        return Playbook(
            id=_slugify(name),
            name=name,
            version=1,
            confidence="low",
            trigger_patterns=trigger_patterns,
            created_from="session",
            executions=0,
            steps=steps,
        )

    def _step_from_tool_call(self, event: dict, step_id: int) -> Optional[PlaybookStep]:
        tool_name = event.get("tool", "")
        params = dict(event.get("params", {}))

        resolved_name, action = self.registry.resolve_tool_name(tool_name)
        if resolved_name is None:
            # Unknown tool — still record it
            return PlaybookStep(
                id=step_id,
                name=f"Execute {tool_name}",
                action=ActionBinding(tool=tool_name, params=params),
            )

        # Separate default params from ticket-specific params
        defaults = self.registry.get_defaults(resolved_name, action) if action else {}
        playbook_params = {}
        param_sources = {}

        for k, v in params.items():
            if k in defaults and defaults[k] == v:
                continue  # matches default, don't include in playbook
            playbook_params[k] = v

        auth_req = self.registry.get_auth_requirement(resolved_name)

        return PlaybookStep(
            id=step_id,
            name=f"{action.replace('_', ' ').title() if action else tool_name}",
            action=ActionBinding(
                tool=tool_name,
                params=playbook_params,
                param_sources=param_sources,
            ),
            auth_required=auth_req == "per_domain",
        )

    def _step_from_manual_action(self, event: dict, step_id: int) -> PlaybookStep:
        return PlaybookStep(
            id=step_id,
            name=event.get("inferred_step", event.get("content", "Manual step")),
            action=ActionBinding(
                tool=event.get("action_binding", "human"),
                params={},
            ),
            auth_required=bool(event.get("auth_note")),
            auth_method="human_handoff",
            human_required=True,
        )

    def _extract_keywords(self, text: str) -> list:
        """Extract likely trigger keywords from a user instruction."""
        # Common IT task keywords
        known_keywords = [
            "SSO", "SAML", "SCIM", "OIDC", "onboarding", "offboarding",
            "certificate", "renewal", "provisioning", "deprovisioning",
            "access", "permissions", "MFA", "2FA", "password", "reset",
            "account", "license", "audit", "compliance",
        ]
        found = [kw for kw in known_keywords if kw.lower() in text.lower()]
        return found if found else []

    def extract_from_description(self, name: str, steps_text: list) -> Playbook:
        """Path 2: Create playbook from user-described steps."""
        steps = []
        for i, desc in enumerate(steps_text, 1):
            tool, action = self._infer_tool_for_description(desc)
            steps.append(PlaybookStep(
                id=i,
                name=desc,
                action=ActionBinding(tool=tool, params={}),
                auth_required=self.registry.get_auth_requirement(tool.split("__")[0] if "__" in tool else tool) == "per_domain",
            ))
        return Playbook(
            id=_slugify(name),
            name=name,
            version=1,
            confidence="medium",
            trigger_patterns=[],
            created_from="dictated",
            executions=0,
            steps=steps,
        )

    def _infer_tool_for_description(self, description: str) -> tuple:
        """Given a step description, infer which tool handles it."""
        desc_lower = description.lower()
        tool_hints = {
            "jira": ["jira", "ticket", "issue", "sprint", "epic", "story"],
            "freshservice": ["freshservice", "service request", "service desk"],
            "slack": ["slack", "message", "notify", "dm", "channel"],
            "gmail": ["email", "gmail", "mail", "send email"],
            "confluence": ["confluence", "wiki", "documentation", "page"],
            "playwright": ["browser", "configure", "admin console", "login", "navigate", "okta", "google admin"],
            "google_calendar": ["calendar", "meeting", "schedule", "event"],
        }
        for tool_name, hints in tool_hints.items():
            if any(h in desc_lower for h in hints):
                info = self.registry.get_tool_info(tool_name)
                prefix = info.get("prefix", tool_name) if info else tool_name
                return (prefix, None)
        return ("claude", None)  # default to AI for unknown steps
