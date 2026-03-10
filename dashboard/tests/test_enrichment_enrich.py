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

def test_build_enrich_prompt_includes_description_and_knowledge():
    mod = _load_module()
    card = {
        "id": 1,
        "summary": "#231844 [Service Request] Request for Jon Ross : Jira Project Access",
        "analysis_metadata": json.dumps({
            "ticket_id": 231844, "status": "Open", "priority": "Medium",
            "type": "Service Request", "classification_bucket": "jira-admin",
            "classification_knowledge_files": ["jira-api-reference.md"],
        }),
    }
    classification = {
        "bucket_id": "jira-admin",
        "knowledge_files": ["jira-api-reference.md"],
    }
    prompt = mod.build_enrich_prompt(card, classification, "User needs Jira access", [])
    assert "231844" in prompt
    assert "Jira Project Access" in prompt
    assert "jira-admin" in prompt
    assert "proposed_actions" in prompt

def test_parse_enrich_response_valid():
    mod = _load_module()
    raw = json.dumps({
        "proposed_actions": [
            {"type": "grant_access", "draft": "Grant Jira project access to Jon Ross"},
            {"type": "reply_to_requester", "draft": "Confirm access has been granted"},
        ],
        "playbook_match": None,
    })
    result = mod.parse_enrich_response(raw)
    assert len(result["proposed_actions"]) == 2
    assert result["proposed_actions"][0]["type"] == "grant_access"

def test_parse_enrich_response_caps_at_6_actions():
    mod = _load_module()
    actions = [{"type": f"action_{i}", "draft": f"Do thing {i}"} for i in range(10)]
    raw = json.dumps({"proposed_actions": actions, "playbook_match": None})
    result = mod.parse_enrich_response(raw)
    assert len(result["proposed_actions"]) <= 6

def test_parse_enrich_response_handles_garbage():
    mod = _load_module()
    result = mod.parse_enrich_response("not json")
    assert result is None
