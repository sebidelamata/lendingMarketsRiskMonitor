#!/usr/bin/env python3
"""Interactive first-time setup.

Run this once after cloning the repo:

    python scripts/setup.py

What it does:
    1. Creates config.json from config.example.json if it doesn't exist yet.
    2. Generates secret.key (a random encryption key, chmod 600, gitignored).
    3. Scans config.json for ${placeholder} values (e.g. "${telegram_bot_token}")
       and prompts you for each one, storing it encrypted in secrets.enc.json.

Safe to re-run: it won't overwrite an existing key or already-set secrets
without asking first.
"""

import getpass
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aave_monitor.secrets_store import (
    DEFAULT_KEY_PATH,
    DEFAULT_SECRETS_PATH,
    find_placeholders,
    generate_key,
    load_encrypted_secrets,
    set_secret,
)

CONFIG_PATH = Path("config.json")
CONFIG_EXAMPLE_PATH = Path("config.example.json")


def banner(text):
    print()
    print(f"== {text} ==")


def ensure_config_json():
    banner("config.json")

    if CONFIG_PATH.exists():
        print(f"Found existing {CONFIG_PATH}.")
        return

    if not CONFIG_EXAMPLE_PATH.exists():
        sys.exit(
            f"Neither {CONFIG_PATH} nor {CONFIG_EXAMPLE_PATH} exist. "
            "Nothing to base setup on."
        )

    shutil.copy(CONFIG_EXAMPLE_PATH, CONFIG_PATH)

    print(f"Created {CONFIG_PATH} from {CONFIG_EXAMPLE_PATH}.")
    print(
        f"Edit {CONFIG_PATH} now if you want to add/remove chains, RPC "
        f"URLs, or thresholds -- this script only handles the secret "
        f"values. Press Enter once you're ready to continue."
    )
    input()


def ensure_key():
    banner("Encryption key")

    if DEFAULT_KEY_PATH.exists():
        print(f"Found existing {DEFAULT_KEY_PATH}. Reusing it.")
        return

    generate_key(DEFAULT_KEY_PATH)

    print(f"Generated {DEFAULT_KEY_PATH} (0600 permissions).")
    print(
        "IMPORTANT: back this file up somewhere safe and OUTSIDE the repo "
        "(e.g. a password manager). If you lose it, every stored secret "
        "becomes unrecoverable and you'll need to re-enter them all."
    )


def _looks_like_plaintext_secrets(config):
    """Heuristic: does this config have a non-empty, non-placeholder
    Telegram token, or an rpc_url whose last path segment doesn't look
    like a placeholder? If so it's probably an un-migrated plaintext
    config rather than one with nothing sensitive in it.
    """

    token = config.get("telegram_bot_token")
    if token and not (isinstance(token, str) and token.startswith("${")):
        return True

    chains = config.get("chains")
    chain_list = chains.values() if isinstance(chains, dict) else (chains or [])

    for chain in chain_list:
        rpc_url = chain.get("rpc_url", "")
        last_segment = rpc_url.rsplit("/", 1)[-1] if rpc_url else ""
        if last_segment and not last_segment.startswith("${"):
            return True

    return False


def collect_secrets():
    banner("Secrets")

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    placeholders = sorted(find_placeholders(config))

    if not placeholders:
        if _looks_like_plaintext_secrets(config):
            print(
                f"{CONFIG_PATH} has no ${{placeholders}}, but it looks like it "
                f"still has real secrets sitting in it as plaintext "
                f"(a Telegram token/chat id and/or RPC URLs with an API key "
                f"baked in).\n\n"
                f"Run this instead to migrate it:\n"
                f"    python scripts/migrate_secrets.py"
            )
        else:
            print(
                f"{CONFIG_PATH} doesn't reference any ${{placeholders}}. "
                "Nothing to encrypt -- either you're storing secrets in "
                "plaintext directly (not recommended) or there's nothing "
                "sensitive in this config."
            )
        return

    existing = load_encrypted_secrets(DEFAULT_SECRETS_PATH)

    print(f"{CONFIG_PATH} references {len(placeholders)} secret(s):")
    for name in placeholders:
        status = "already set" if name in existing else "MISSING"
        print(f"  - {name}  [{status}]")
    print()

    for name in placeholders:
        if name in existing:
            answer = input(f"'{name}' is already set. Overwrite it? [y/N] ").strip().lower()
            if answer != "y":
                continue

        value = getpass.getpass(f"Enter value for '{name}' (input hidden): ").strip()

        if not value:
            print(f"  Skipped '{name}' (empty input).")
            continue

        set_secret(name, value, DEFAULT_KEY_PATH, DEFAULT_SECRETS_PATH)
        print(f"  Stored '{name}' (encrypted).")


def main():
    print("Aave Monitor -- first-time setup")

    ensure_config_json()
    ensure_key()
    collect_secrets()

    banner("Done")
    print("Next steps:")
    print("  - Review config.json (chains, thresholds, poll interval).")
    print("  - Run locally:      python main.py")
    print("  - Run with Docker:  docker compose up -d --build")
    print("  - Update a secret later: python scripts/update_secret.py <name>")


if __name__ == "__main__":
    main()
