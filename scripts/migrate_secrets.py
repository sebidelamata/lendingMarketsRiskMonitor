#!/usr/bin/env python3
"""One-time migration for an existing config.json that has real secrets
sitting in it as plaintext (Telegram token/chat id, RPC API keys baked
into rpc_url) -- converts it to the ${placeholder} + encrypted
secrets.enc.json scheme used by setup.py / update_secret.py.

Usage:
    python scripts/migrate_secrets.py

What it does:
    1. Backs up your current config.json to config.json.bak.
    2. Pulls "telegram_bot_token" / "telegram_chat_id" out of config.json.
    3. For every chain's "rpc_url", pulls out the API key segment (the
       part after the last "/", e.g. the Alchemy key in
       ".../v2/<KEY>") as a secret.
    4. If the exact same key is reused across multiple chains, it's
       stored once under a shared name instead of once per chain.
    5. Encrypts everything into secrets.enc.json (generating secret.key
       first if it doesn't exist yet) and rewrites config.json with
       ${name} placeholders in place of the real values.

Safe to re-run: any field that's already a "${...}" placeholder is left
untouched, and existing secrets aren't overwritten without asking.
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aave_monitor.secrets_store import (
    DEFAULT_KEY_PATH,
    DEFAULT_SECRETS_PATH,
    generate_key,
    load_encrypted_secrets,
    set_secret,
)

CONFIG_PATH = Path("config.json")

_PLACEHOLDER_RE = re.compile(r"^\$\{[A-Za-z0-9_]+\}$")


def is_placeholder(value):
    return isinstance(value, str) and bool(_PLACEHOLDER_RE.match(value))


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def extract_rpc_key(rpc_url):
    """Pull the API key segment off the end of an RPC URL.
    Handles Alchemy-style (.../v2/<KEY>), Infura-style (.../v3/<KEY>),
    and anything else where the key is the final path segment.
    """

    return rpc_url.rsplit("/", 1)[-1]


def replace_rpc_key(rpc_url, placeholder):
    prefix = rpc_url.rsplit("/", 1)[0]
    return f"{prefix}/{placeholder}"


def main():
    if not CONFIG_PATH.exists():
        sys.exit(f"{CONFIG_PATH} not found.")

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    backup_path = CONFIG_PATH.with_suffix(".json.bak")
    backup_path.write_text(json.dumps(config, indent=2))
    print(f"Backed up current config to {backup_path}.")

    if not DEFAULT_KEY_PATH.exists():
        generate_key(DEFAULT_KEY_PATH)
        print(f"Generated {DEFAULT_KEY_PATH} (0600 permissions).")
    else:
        print(f"Using existing {DEFAULT_KEY_PATH}.")

    existing_secrets = load_encrypted_secrets(DEFAULT_SECRETS_PATH)

    to_store = {}   # name -> plaintext value, collected before writing
    changed = False

    # -- Telegram fields --

    for field in ("telegram_bot_token", "telegram_chat_id"):
        value = config.get(field)

        if value is None or is_placeholder(value):
            continue

        value = str(value)
        to_store[field] = value
        config[field] = f"${{{field}}}"
        changed = True
        print(f"Found plaintext '{field}' -> will store as secret '{field}'.")

    # -- Per-chain RPC API keys --

    chains = config.get("chains")
    chain_list = chains.values() if isinstance(chains, dict) else (chains or [])

    # First pass: find which raw key values repeat across chains, so
    # identical keys (common with a single Alchemy app key reused across
    # networks) get one shared secret instead of one per chain.
    raw_keys_by_chain = {}

    for chain in chain_list:
        rpc_url = chain.get("rpc_url")

        if not rpc_url or is_placeholder(extract_rpc_key(rpc_url)):
            continue

        raw_keys_by_chain[chain.get("name", "unknown")] = extract_rpc_key(rpc_url)

    value_to_chains = {}
    for chain_name, key_value in raw_keys_by_chain.items():
        value_to_chains.setdefault(key_value, []).append(chain_name)

    key_value_to_secret_name = {}
    for key_value, chain_names in value_to_chains.items():
        if len(chain_names) > 1:
            key_value_to_secret_name[key_value] = "shared_rpc_api_key"
        else:
            key_value_to_secret_name[key_value] = f"{slugify(chain_names[0])}_rpc_api_key"

    for chain in chain_list:
        rpc_url = chain.get("rpc_url")

        if not rpc_url:
            continue

        key_value = extract_rpc_key(rpc_url)

        if is_placeholder(key_value):
            continue

        secret_name = key_value_to_secret_name[key_value]
        to_store[secret_name] = key_value
        chain["rpc_url"] = replace_rpc_key(rpc_url, f"${{{secret_name}}}")
        changed = True

    if not to_store:
        print("Nothing to migrate -- config.json has no plaintext secrets left.")
        return

    print("\nSecrets to store:")
    for name in sorted(to_store.keys()):
        already = name in existing_secrets
        print(f"  - {name}{'  (will overwrite existing)' if already else ''}")

    answer = input("\nProceed with encrypting these and rewriting config.json? [y/N] ").strip().lower()

    if answer != "y":
        print("Aborted -- config.json left unchanged (backup already written, harmless).")
        return

    for name, value in to_store.items():
        set_secret(name, value, DEFAULT_KEY_PATH, DEFAULT_SECRETS_PATH)

    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    print(f"\nDone. {len(to_store)} secret(s) encrypted into {DEFAULT_SECRETS_PATH}.")
    print(f"config.json now uses ${{...}} placeholders. Original saved as {backup_path}.")
    print("Run `python main.py` (or `docker compose up -d --build`) to confirm it starts.")
    print(f"Once you've confirmed it works, delete {backup_path} -- it currently still")
    print("holds your secrets in plaintext.")


if __name__ == "__main__":
    main()
