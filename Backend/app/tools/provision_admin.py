"""Internal interactive bootstrap. Importing this module never accesses Firebase."""
import argparse
import getpass
import hmac
import os
from pathlib import Path
import sys
import warnings

from dotenv import load_dotenv

from app.services.admin_bootstrap_service import provision_first_owner
from app.services.firebase_service import get_firestore_client

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_TEST_ENVIRONMENT_VARIABLES = (
    "FIRESTORE_EMULATOR_HOST", "DATASTORE_EMULATOR_HOST", "FIRESTORE_TEST_PROJECT_ID",
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Provision the first owner only (internal tool).")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args(argv)
    if not args.bootstrap or os.getenv("ADMIN_BOOTSTRAP_ENABLED") != "true":
        print("Bootstrap disabled: explicit flag and process opt-in are required.", file=sys.stderr)
        return 1
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        print("Bootstrap requires an interactive terminal.", file=sys.stderr)
        return 1
    try:
        # Match Firebase's effective environment before initializing its client.
        # Keep opt-in process-only: the gate above intentionally precedes .env.
        load_dotenv(_BACKEND_ROOT / ".env", override=False)
        if any(name in os.environ for name in _TEST_ENVIRONMENT_VARIABLES):
            print("Definitive provisioning cannot run with emulator or test environment configurations.", file=sys.stderr)
            return 1
        confirmation = input(f"Type 'BOOTSTRAP {args.project_id}' to confirm the target project: ")
        if confirmation != f"BOOTSTRAP {args.project_id}":
            print("Bootstrap canceled.", file=sys.stderr)
            return 1
        client = get_firestore_client()
        if args.project_id != client.project:
            print("Bootstrap project confirmation failed.", file=sys.stderr)
            return 1
        email = input("Owner email: ")
        with warnings.catch_warnings():
            # Refuse getpass fallback rather than allow a password to be echoed.
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("Owner password: ")
            repeated = getpass.getpass("Repeat owner password: ")
        if not hmac.compare_digest(password.encode("utf-8"), repeated.encode("utf-8")):
            print("Password confirmation failed.", file=sys.stderr)
            return 1
        provision_first_owner(client=client, email=email, password=password,
                              bootstrap_enabled=True, expected_project_id=args.project_id)
    except (Exception, KeyboardInterrupt):
        # No traceback, input, credential, hash or raw SDK error leaves this tool.
        print("Bootstrap not confirmed. Check the target state through trusted internal access before retrying.", file=sys.stderr)
        return 1
    print("First owner provisioned successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
