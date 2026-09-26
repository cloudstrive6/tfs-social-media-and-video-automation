"""CI helper: turn the repository secrets JSON (from `toJSON(secrets)`) into a .env file."""
import json
import os
from pathlib import Path

secrets = json.loads(os.environ.get("SECRETS_JSON", "{}"))
secrets = {k: v for k, v in secrets.items() if k.lower() != "github_token" and not k.startswith("VM_")}
lines = [f"{k}={v}" for k, v in secrets.items() if "\n" not in str(v)]
Path(__file__).resolve().parents[1].joinpath(".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {len(lines)} variables to .env")
