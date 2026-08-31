"""Encrypted-at-rest storage for sensitive config values (Telegram bot
token, chat id, RPC provider API keys, etc.).

WHY NOT bcrypt
--------------
bcrypt (and password hashing in general) is a ONE-WAY function: it's built
so you can *verify* a password without ever being able to recover it. That's
the wrong shape here -- we need to send the real Telegram bot token to the
Telegram API, so we must be able to decrypt it back to plaintext. This
module uses Fernet (AES-128-CBC + HMAC, from the `cryptography` package
maintained by the Python Cryptographic Authority) instead, which is
reversible symmetric encryption -- the right primitive for "encrypt this,
decrypt it later."

THREAT MODEL, HONESTLY STATED
------------------------------
This protects secrets from:
  - Someone browsing the SD card / repo / backups without the key file.
  - Accidentally committing secrets to git (only ciphertext + key *path*
    would ever be at risk, never the key file itself, since it's gitignored).

This does NOT protect secrets from:
  - Anyone who can read files as the same OS user the monitor runs as
    (they can just read the key file too).
  - Root on the Pi.
For a single-user Raspberry Pi, this is a reasonable, honest bar: it stops
casual exposure (backups, git, a shared drive) without pretending to be a
hardware security module. If you need stronger guarantees later, look at
a TPM-backed key or a secrets manager (Vault, AWS Secrets Manager, etc.).

FILE LAYOUT
-----------
    secret.key         -- random 32-byte Fernet key, chmod 600, gitignored
    secrets.enc.json    -- {"telegram_bot_token": "<ciphertext>", ...}, gitignored

config.json stays free of secrets. Anywhere config.json needs a secret
value, use a placeholder like "${telegram_bot_token}" and call
resolve_placeholders() to substitute in the decrypted value at runtime.
"""

import json
import os
import re
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

DEFAULT_KEY_PATH = Path("secret.key")
DEFAULT_SECRETS_PATH = Path("secrets.enc.json")

_PLACEHOLDER_RE = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


def generate_key(key_path: Path = DEFAULT_KEY_PATH, overwrite: bool = False) -> bytes:
    """Generate a new random Fernet key and write it with 0600 permissions.

    Refuses to overwrite an existing key unless overwrite=True, since
    overwriting it would make every currently-encrypted secret undecryptable.
    """

    if key_path.exists() and not overwrite:
        raise FileExistsError(
            f"{key_path} already exists. Re-encrypting with a new key would "
            f"make existing secrets unreadable -- pass overwrite=True only "
            f"if you're intentionally rotating the key (and are ready to "
            f"re-enter every secret afterwards)."
        )

    key = Fernet.generate_key()

    key_path.write_bytes(key)
    os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600: owner read/write only

    return key


def load_key(key_path: Path = DEFAULT_KEY_PATH) -> bytes:
    if not key_path.exists():
        raise FileNotFoundError(
            f"{key_path} not found. Run `python scripts/setup.py` first."
        )

    return key_path.read_bytes()


# ---------------------------------------------------------------------------
# Encrypt / decrypt single values
# ---------------------------------------------------------------------------


def encrypt_value(key: bytes, plaintext: str) -> str:
    return Fernet(key).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(key: bytes, ciphertext: str) -> str:
    try:
        return Fernet(key).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError(
            "Could not decrypt secret -- wrong key, or the ciphertext is "
            "corrupted/truncated."
        ) from e


# ---------------------------------------------------------------------------
# Encrypted secrets file (a flat dict of name -> ciphertext)
# ---------------------------------------------------------------------------


def load_encrypted_secrets(secrets_path: Path = DEFAULT_SECRETS_PATH) -> dict:
    if not secrets_path.exists():
        return {}

    with open(secrets_path) as f:
        return json.load(f)


def save_encrypted_secrets(secrets: dict, secrets_path: Path = DEFAULT_SECRETS_PATH) -> None:
    tmp = secrets_path.with_suffix(".tmp")

    with open(tmp, "w") as f:
        json.dump(secrets, f, indent=2, sort_keys=True)

    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(secrets_path)


def set_secret(
    name: str,
    plaintext: str,
    key_path: Path = DEFAULT_KEY_PATH,
    secrets_path: Path = DEFAULT_SECRETS_PATH,
) -> None:
    key = load_key(key_path)
    secrets = load_encrypted_secrets(secrets_path)
    secrets[name] = encrypt_value(key, plaintext)
    save_encrypted_secrets(secrets, secrets_path)


def get_secret(
    name: str,
    key_path: Path = DEFAULT_KEY_PATH,
    secrets_path: Path = DEFAULT_SECRETS_PATH,
) -> str:
    key = load_key(key_path)
    secrets = load_encrypted_secrets(secrets_path)

    if name not in secrets:
        raise KeyError(f"No secret named '{name}' in {secrets_path}.")

    return decrypt_value(key, secrets[name])


def decrypt_all_secrets(
    key_path: Path = DEFAULT_KEY_PATH,
    secrets_path: Path = DEFAULT_SECRETS_PATH,
) -> dict:
    """Return {name: plaintext} for every stored secret."""

    key = load_key(key_path)
    secrets = load_encrypted_secrets(secrets_path)

    return {name: decrypt_value(key, ciphertext) for name, ciphertext in secrets.items()}


# ---------------------------------------------------------------------------
# Placeholder substitution: "${telegram_bot_token}" -> decrypted value
# ---------------------------------------------------------------------------


def find_placeholders(obj) -> set:
    """Recursively collect every ${name} placeholder used in a config
    structure (dict/list/str), for the setup script to know what to prompt
    for.
    """

    found = set()

    if isinstance(obj, dict):
        for value in obj.values():
            found |= find_placeholders(value)
    elif isinstance(obj, list):
        for item in obj:
            found |= find_placeholders(item)
    elif isinstance(obj, str):
        found |= set(_PLACEHOLDER_RE.findall(obj))

    return found


def resolve_placeholders(obj, secrets: dict):
    """Recursively substitute ${name} placeholders in a config structure
    with decrypted values from `secrets` (name -> plaintext).
    """

    if isinstance(obj, dict):
        return {k: resolve_placeholders(v, secrets) for k, v in obj.items()}

    if isinstance(obj, list):
        return [resolve_placeholders(v, secrets) for v in obj]

    if isinstance(obj, str):
        def _sub(match):
            name = match.group(1)

            if name not in secrets:
                raise KeyError(
                    f"config.json references \"${{{name}}}\" but no such "
                    f"secret is stored. Run `python scripts/update_secret.py "
                    f"{name}` to add it."
                )

            return secrets[name]

        return _PLACEHOLDER_RE.sub(_sub, obj)

    return obj


def load_resolved_config(
    config: dict,
    key_path: Path = DEFAULT_KEY_PATH,
    secrets_path: Path = DEFAULT_SECRETS_PATH,
) -> dict:
    """Load config.json's dict with every ${placeholder} substituted for
    its decrypted value. This is what app.py calls at startup.
    """

    secrets = decrypt_all_secrets(key_path, secrets_path)
    return resolve_placeholders(config, secrets)
