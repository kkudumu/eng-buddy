import pytest
import yaml
import tempfile
import os
from models import Playbook, PlaybookStep, ActionBinding, ParamSource

def test_playbook_from_yaml():
    raw = {
        "id": "sso-onboarding",
        "name": "SSO Onboarding",
        "version": 1,
        "confidence": "low",
        "trigger_patterns": [
            {"ticket_type": "Service Request", "keywords": ["SSO", "SAML"], "source": ["freshservice"]}
        ],
        "created_from": "session",
        "executions": 0,
        "steps": [
            {
                "id": 1,
                "name": "Create Jira ticket",
                "action": {
                    "tool": "mcp__mcp-atlassian__jira_create_issue",
                    "params": {"project": "ITWORK2", "summary": "[SSO] {{app_name}}"},
                    "param_sources": {"app_name": {"from": "trigger_ticket", "field": "subject", "extract": "app name"}}
                },
                "auth_required": False,
                "human_required": False,
            }
        ],
    }
    pb = Playbook.from_dict(raw)
    assert pb.id == "sso-onboarding"
    assert pb.confidence == "low"
    assert len(pb.steps) == 1
    assert pb.steps[0].action.tool == "mcp__mcp-atlassian__jira_create_issue"
    assert pb.steps[0].action.param_sources["app_name"].field == "subject"

def test_playbook_round_trip_yaml(tmp_path):
    raw = {
        "id": "test-pb",
        "name": "Test Playbook",
        "version": 1,
        "confidence": "medium",
        "trigger_patterns": [],
        "created_from": "dictated",
        "executions": 0,
        "steps": [],
    }
    pb = Playbook.from_dict(raw)
    path = tmp_path / "test-pb.yml"
    pb.save(str(path))
    loaded = Playbook.load(str(path))
    assert loaded.id == pb.id
    assert loaded.version == pb.version

def test_playbook_matches_ticket():
    raw = {
        "id": "sso",
        "name": "SSO",
        "version": 1,
        "confidence": "high",
        "trigger_patterns": [
            {"ticket_type": "Service Request", "keywords": ["SSO", "SAML"], "source": ["freshservice"]}
        ],
        "created_from": "session",
        "executions": 3,
        "steps": [],
    }
    pb = Playbook.from_dict(raw)
    assert pb.matches(ticket_type="Service Request", text="Set up SSO for Linear", source="freshservice")
    assert not pb.matches(ticket_type="Incident", text="Server is down", source="freshservice")
    assert not pb.matches(ticket_type="Service Request", text="New laptop request", source="freshservice")

def test_confidence_progression():
    raw = {
        "id": "t",
        "name": "T",
        "version": 1,
        "confidence": "low",
        "trigger_patterns": [],
        "created_from": "session",
        "executions": 0,
        "steps": [],
    }
    pb = Playbook.from_dict(raw)
    pb.record_execution(success=True)
    assert pb.confidence == "medium"
    assert pb.executions == 1
    pb.record_execution(success=True)
    pb.record_execution(success=True)
    assert pb.confidence == "high"
    assert pb.executions == 3
