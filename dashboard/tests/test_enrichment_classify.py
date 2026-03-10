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

def test_build_classify_prompt_includes_ticket_and_schema():
    mod = _load_module()
    card = {
        "id": 1,
        "summary": "#221901 [Incident] Unable to Change Jira type: Story to Spike",
        "analysis_metadata": json.dumps({
            "ticket_id": 221901, "status": "Open", "priority": "Medium",
            "type": "Incident", "requester_id": 123, "group_id": 456,
        }),
    }
    schema = {"buckets": {}}
    prompt = mod.build_classify_prompt(card, schema)
    assert "221901" in prompt
    assert "Incident" in prompt
    assert "classification schema" in prompt.lower() or "Current schema" in prompt

def test_parse_classify_response_new_bucket():
    mod = _load_module()
    raw = json.dumps({
        "bucket_id": "jira-admin",
        "bucket_description": "Jira configuration and access management",
        "is_new_bucket": True,
        "knowledge_files": ["jira-api-reference.md"],
        "confidence_keywords": ["jira", "project access", "story type"],
        "reasoning": "Ticket involves Jira type change",
    })
    result = mod.parse_classify_response(raw)
    assert result["bucket_id"] == "jira-admin"
    assert result["is_new_bucket"] is True
    assert "jira-api-reference.md" in result["knowledge_files"]

def test_parse_classify_response_handles_garbage():
    mod = _load_module()
    result = mod.parse_classify_response("not json at all")
    assert result is None
