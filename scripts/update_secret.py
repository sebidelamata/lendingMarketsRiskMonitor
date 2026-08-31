#!/usr/bin/env python3
"""Update (or add) a single encrypted secret.

Usage:
    python scripts/update_secret.py telegram_bot_token
    python scripts/update_secret.py              # lists known secret names, then prompts

Never prints existing values -- only lets you overwrite them.
"""

import getpass
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aave_monitor.secrets_store import (
    DEFAULT_KEY_PATH,
    DEFAULT_SECRETS_PATH,
    find_placeholders,
    load_encrypted_secrets,
    set_secret,
)

CONFIG_PATH = Path("config.json")


def known_secret_names():
    if not CONFIG_PATH.exists():
        return set()

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    return find_placeholders(config)


def main():
    if not DEFAULT_KEY_PATH.exists():
        sys.exit(f"{DEFAULT_KEY_PATH} not found. Run `python scripts/setup.py` first.")

    existing = load_encrypted_secrets(DEFAULT_SECRETS_PATH)
    referenced = known_secret_names()

    if len(sys.argv) > 1:
        name = sys.argv[1]
    else:
        all_names = sorted(referenced | set(existing.keys()))

        if not all_names:
            sys.exit("No secrets referenced by config.json and none stored yet.")

        print("Known secret names:")
        for n in all_names:
            flags = []
            if n in existing:
                flags.append("stored")
            if n not in referenced:
                flags.append("no longer referenced by config.json")
            suffix = f" ({', '.join(flags)})" if flags else ""
            print(f"  - {n}{suffix}")

        name = input("\nWhich secret do you want to set/update? ").strip()

        if not name:
            sys.exit("No name given, aborting.")

    if name in existing:
        print(f"'{name}' is currently set. This will overwrite it.")

    value = getpass.getpass(f"Enter new value for '{name}' (input hidden): ").strip()

    if not value:
        sys.exit("Empty value, aborting -- nothing was changed.")

    set_secret(name, value, DEFAULT_KEY_PATH, DEFAULT_SECRETS_PATH)

    print(f"'{name}' updated.")

    if name not in referenced:
        print(
            f"Note: config.json doesn't currently reference \"${{{name}}}\" "
            f"anywhere, so this value won't be used until it does."
        )


if __name__ == "__main__":
    main()
