"""Read the Terraform outputs, so no value is ever copied by hand."""

import json
import subprocess
from pathlib import Path

TERRAFORM_DIR = Path(__file__).resolve().parent.parent / "terraform"


def load_outputs() -> dict[str, object]:
    """Return {output name: value}, sensitive outputs included. Nothing is written to disk."""
    result = subprocess.run(
        ["terraform", f"-chdir={TERRAFORM_DIR}", "output", "-json"],
        check=True,
        capture_output=True,
        text=True,
    )
    outputs = {name: entry["value"] for name, entry in json.loads(result.stdout).items()}
    if not outputs:
        raise RuntimeError("No Terraform outputs found: run 'python scripts/env.py up' first.")
    return outputs
