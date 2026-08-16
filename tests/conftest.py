"""Test-session defaults applied before anything imports `app`.

pytest loads conftest before collecting test modules, which is the only window
in which these take effect — `app.core.config.settings` is a module-level
singleton, so by the first `from app...` the values are already frozen.
"""

import os

# A LANGSMITH_API_KEY in .env would otherwise switch tracing on for the whole
# suite: every traced call spawns a background upload, and a key that is expired
# or wrong-region turns that into 403 log spam loud enough to bury a real
# failure. Env wins over .env in pydantic-settings, so this is authoritative.
os.environ.setdefault("LANGSMITH_TRACING", "false")
