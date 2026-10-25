"""Run the environment lifecycle in the right order.

    python scripts/env.py up     # terraform init + apply, then URLs and credentials
    python scripts/env.py test   # pytest -m e2e
    python scripts/env.py down   # cleanup.py --yes, then terraform destroy

Only existing commands are called; apply and destroy stay interactive. The point is
the order in "down": the VPCs created by the API are deleted before terraform
destroy, because Terraform does not know about them, and after destroy the table
(and DELETE through the API) is gone. The only local actions are creating build/
(git-ignored, where Terraform writes the Lambda ZIP) before the first plan, and
printing the URLs and the test users' credentials after a successful apply.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from tf_outputs import load_outputs

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = REPO_ROOT / "build"
TERRAFORM = ["terraform", "-chdir=terraform"]


def run(command: list[str]) -> int:
    print(f"> {' '.join(command)}", flush=True)
    return subprocess.call(command, cwd=REPO_ROOT)


def run_or_exit(command: list[str]) -> None:
    code = run(command)
    if code != 0:
        sys.exit(code)


def up() -> None:
    # build/ is git-ignored, so a fresh clone does not have it; archive_file writes
    # the Lambda ZIP there during the first plan.
    BUILD_DIR.mkdir(exist_ok=True)
    run_or_exit([*TERRAFORM, "init"])
    run_or_exit([*TERRAFORM, "apply"])
    print_summary()


def print_summary() -> None:
    # The password outputs stay sensitive in Terraform, so they never show up in
    # plan / apply; they are printed only here, on request, and never written to disk.
    try:
        outputs = load_outputs()
    except (subprocess.CalledProcessError, RuntimeError) as error:
        print(f"Could not read the Terraform outputs: {error}", file=sys.stderr)
        return
    print()
    print("Environment ready")
    print(f"  web_url : {outputs['web_url']}")
    print(f"  api_url : {outputs['api_url']}")
    for user in ("demo_owner", "reviewer"):
        print()
        print(f"  {user.replace('_', '-')}")
        print(f"    username : {outputs[f'{user}_username']}")
        print(f"    password : {outputs[f'{user}_password']}")
    print()
    print("Passwords are shown in clear text: clear the terminal before sharing your screen.")


def test() -> None:
    run_or_exit([sys.executable, "-m", "pytest", "-m", "e2e"])


def down() -> None:
    code = run([sys.executable, "scripts/cleanup.py", "--yes"])
    if code != 0:
        print(
            "Cleanup did not finish: resolve the resources listed above, then run "
            "'python scripts/env.py down' again. terraform destroy was NOT run.",
            file=sys.stderr,
        )
        sys.exit(code)
    run_or_exit([*TERRAFORM, "destroy"])


COMMANDS = {"up": up, "test": test, "down": down}


def main() -> None:
    parser = argparse.ArgumentParser(description="Environment lifecycle: up, test, down.")
    parser.add_argument("command", choices=list(COMMANDS))
    args = parser.parse_args()
    COMMANDS[args.command]()


if __name__ == "__main__":
    main()
