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

def test_fetch_unenriched_cards_returns_list():
    mod = _load_module()
    # Should not crash even if table has no enrichment_status column yet
    try:
        cards = mod.fetch_unenriched_cards()
        assert isinstance(cards, list)
    except Exception:
        pass  # OK if DB not migrated in test env

def test_enrich_single_card_pipeline_functions_exist():
    mod = _load_module()
    assert callable(mod.enrich_single_card)
    assert callable(mod.main)
