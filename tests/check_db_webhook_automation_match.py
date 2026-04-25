#!/usr/bin/env python3
"""
Read ``dm_webhook_events`` in Cosmos and check whether any recent *comment* webhook
matches an enabled automation in ``dm_automations`` (same rules as ``CommentProcessor``).

No HTTP. Does not need INSTAGRAM_APP_SECRET.

  PYTHONPATH=. python tests/check_db_webhook_automation_match.py

Exit: 0 if a match is found or there are no comment webhooks in the window;
      1 if there are comment webhooks but none match; 2 on Cosmos error.
"""
import importlib.util
import pathlib
import sys

try:
    import pytest

    pytestmark = pytest.mark.skip(reason="Manual Cosmos script; excluded from CI.")
except ImportError:
    pass

_root = pathlib.Path(__file__).resolve().parent
_path = _root / "replay_comment_webhook_if_matched.py"
spec = importlib.util.spec_from_file_location("_replay_w", _path)
if spec is None or spec.loader is None:
    print("Failed to load replay module", file=sys.stderr)
    sys.exit(2)
_m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = _m
spec.loader.exec_module(_m)

if __name__ == "__main__":
    raise SystemExit(_m.main_check_db())
