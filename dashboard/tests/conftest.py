import sys
from pathlib import Path

# Add dashboard/ to path (for server.py and related modules)
sys.path.insert(0, str(Path(__file__).parent.parent))

# Add bin/planner/ to path so 'from store import PlanStore' works during pytest
_planner_path = str(Path(__file__).parent.parent.parent / "bin" / "planner")
if _planner_path not in sys.path:
    sys.path.insert(0, _planner_path)
