import subprocess
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "bin"))

def test_stage_llm_config_has_all_stages():
    """Config must define CLI + args for each pipeline stage."""
    # Import the module to check config
    spec = __import__("importlib").util.spec_from_file_location(
        "enrichment",
        os.path.join(os.path.dirname(__file__), "..", "..", "bin", "freshservice-enrichment.py"),
    )
    mod = __import__("importlib").util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for stage in ("classify", "enrich", "detect_patterns"):
        assert stage in mod.STAGE_LLM_CONFIG
        assert "cli" in mod.STAGE_LLM_CONFIG[stage]
        assert "args" in mod.STAGE_LLM_CONFIG[stage]
