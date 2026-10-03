"""Checks that every database's MCP Toolbox is up and serving tools.
No OpenAI calls. Run: uv run --env-file .env python scripts/check.py"""

import os
import sys
import tomllib
from pathlib import Path

from toolbox_langchain import ToolboxClient

dbs = tomllib.loads((Path(__file__).parent.parent / "app" / "databases.toml").read_text())["database"]
# Databases with requires_env are only checked when that variable is set.
dbs = [d for d in dbs if not d.get("requires_env") or os.getenv(d["requires_env"])]
ok = 0
for db in dbs:
    # same override the agent uses (TOOLBOX_URL_<KEY>, e.g. TOOLBOX_URL_ORACLE)
    db["toolbox_url"] = os.getenv(f"TOOLBOX_URL_{db['key'].upper()}", db["toolbox_url"])
    try:
        with ToolboxClient(db["toolbox_url"]) as client:
            tools = client.load_toolset()
        print(f"OK    {db['key']:11} {len(tools):3} tools  {db['toolbox_url']}")
        ok += 1
    except Exception as e:
        print(f"FAIL  {db['key']:11}            {db['toolbox_url']}  {type(e).__name__}: {str(e)[:100]}")
print(f"\n{ok}/{len(dbs)} databases reachable.")
sys.exit(0 if ok == len(dbs) else 1)
