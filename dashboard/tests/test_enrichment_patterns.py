import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bin"))

def _load_module():
    spec = __import__("importlib").util.spec_from_file_location(
        "enrichment",
        os.path.join(os.path.dirname(__file__), "..", "..", "bin", "freshservice-enrichment.py"),
    )
    mod = __import__("importlib").util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_build_pattern_prompt_includes_bucket_and_tickets():
    mod = _load_module()
    bucket_id = "jira-admin"
    tickets = [
        {"summary": "#1 [Service Request] Jira Access for Alice", "actions": ["grant_access"]},
        {"summary": "#2 [Service Request] Jira Access for Bob", "actions": ["grant_access"]},
        {"summary": "#3 [Service Request] Jira Access for Carol", "actions": ["grant_access"]},
    ]
    prompt = mod.build_pattern_prompt(bucket_id, tickets)
    assert "jira-admin" in prompt
    assert "Alice" in prompt
    assert "pattern" in prompt.lower()

def test_parse_pattern_response_with_playbook():
    mod = _load_module()
    raw = json.dumps({
        "pattern_detected": True,
        "confidence": "high",
        "playbook_draft": {
            "name": "jira-project-access",
            "description": "Grant Jira project access to a user",
            "trigger_keywords": ["jira", "project access"],
            "steps": [
                {"name": "Look up user in Jira", "tool": "jira_search", "requires_human": False},
                {"name": "Add user to project", "tool": "jira_update_issue", "requires_human": True},
            ],
        },
        "reasoning": "3 identical access request tickets",
    })
    result = mod.parse_pattern_response(raw)
    assert result["pattern_detected"] is True
    assert result["playbook_draft"]["name"] == "jira-project-access"

def test_parse_pattern_response_no_pattern():
    mod = _load_module()
    raw = json.dumps({"pattern_detected": False, "confidence": "low", "playbook_draft": None, "reasoning": "too few tickets"})
    result = mod.parse_pattern_response(raw)
    assert result["pattern_detected"] is False
    assert result["playbook_draft"] is None
