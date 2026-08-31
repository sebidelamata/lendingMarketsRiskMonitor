"""
Loading config.json / state.json, and parsing the per-chain settings
(RPC URL, pool address, explorer URL template) out of the config file.
"""

import json

from web3 import Web3

from constants import CONFIG_PATH, STATE_PATH

from .secrets_store import (
    find_placeholders,
    load_resolved_config,
)


# ---------------------------------------------------------------------------
# Config / state files
# ---------------------------------------------------------------------------


def load_config():
    """
    Load config.json and substitute any ${secret_name} placeholders
    (telegram_bot_token, RPC API keys, etc.) with their decrypted values
    from secret.key / secrets.enc.json.

    Run `python scripts/setup.py` once to create those files.
    """

    if not CONFIG_PATH.exists():
        raise SystemExit(
            f"Missing {CONFIG_PATH}. "
            "Copy config.example.json to config.json and run "
            "`python scripts/setup.py`."
        )

    with open(CONFIG_PATH) as f:
        raw_config = json.load(f)

    placeholders = find_placeholders(raw_config)

    if not placeholders:
        # No ${...} placeholders in use -- config.json holds plaintext
        # secrets directly.
        return raw_config

    try:
        return load_resolved_config(raw_config)

    except FileNotFoundError as e:
        raise SystemExit(
            f"config.json references encrypted secrets "
            f"({', '.join(sorted(placeholders))}) "
            f"but they haven't been set up yet.\n"
            f"{e}\n"
            f"Run: python scripts/setup.py"
        )


def load_state():
    """Load persisted monitor state."""

    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return json.load(f)

    return {}


def save_state(state):
    """
    Atomically save monitor state.

    The temporary file is written first and then replaced over the
    destination state.json.
    """

    tmp = STATE_PATH.with_suffix(".tmp")

    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)

    tmp.replace(STATE_PATH)


# ---------------------------------------------------------------------------
# Chain configuration
# ---------------------------------------------------------------------------


def get_chains(config):
    """
    Return chain configuration as a list of dictionaries.

    Supports both:

        "chains": {
            "Ethereum": {...},
            "Monad": {...}
        }

    and:

        "chains": [
            {
                "name": "Ethereum",
                ...
            }
        ]
    """

    chains = config.get("chains")

    if not chains:
        raise SystemExit(
            "config.json is missing the 'chains' section."
        )

    if isinstance(chains, dict):
        result = []

        for name, settings in chains.items():
            chain = dict(settings)
            chain["name"] = name
            result.append(chain)

        return result

    if isinstance(chains, list):
        result = []

        for chain in chains:
            if not isinstance(chain, dict):
                raise SystemExit(
                    "Every chain entry must be an object."
                )

            if "name" not in chain:
                raise SystemExit(
                    "Every chain entry must contain a 'name'."
                )

            result.append(chain)

        return result

    raise SystemExit(
        "'chains' must be either an object or an array."
    )


def get_chain_by_name(chain_name):
    """
    Resolve a chain name such as 'Ethereum' or 'Monad' into its
    chain configuration dictionary.

    This is primarily used by alert/explorer helpers where the caller
    historically passes only the chain name.
    """

    config = load_config()

    for chain in get_chains(config):
        if chain["name"] == chain_name:
            return chain

    raise ValueError(
        f"Unknown chain '{chain_name}'. "
        "Check the 'chains' section of config.json."
    )


def get_chain_rpc(chain):
    """Return the configured RPC URL."""

    rpc_url = chain.get("rpc_url")

    if not rpc_url:
        raise ValueError(
            f"{chain['name']}: missing rpc_url"
        )

    return rpc_url


def get_chain_address(chain, *names):
    """
    Return the first configured address matching one of `names`.

    Supports both:

        chain["pool_address"]

    and:

        chain["addresses"]["pool_address"]
    """

    addresses = chain.get("addresses", {})

    if not isinstance(addresses, dict):
        addresses = {}

    for name in names:
        address = chain.get(name)

        if not address:
            address = addresses.get(name)

        if address:
            return Web3.to_checksum_address(address)

    raise ValueError(
        f"{chain['name']}: missing required address. "
        f"Expected one of: {', '.join(names)}"
    )


def get_explorer_tx_url(chain, tx_hash):
    """
    Return a block-explorer transaction URL.

    `chain` may be either:

        - the complete chain configuration dictionary, or
        - a chain name such as "Ethereum" / "Monad".

    Supporting both forms prevents alert formatting from having to
    carry the entire chain configuration through every function.
    """

    # ------------------------------------------------------------------
    # Resolve chain name -> configuration when necessary.
    # ------------------------------------------------------------------

    if isinstance(chain, str):
        chain = get_chain_by_name(chain)

    if not isinstance(chain, dict):
        raise TypeError(
            "get_explorer_tx_url() expected a chain configuration "
            f"dictionary or chain name, got {type(chain).__name__}"
        )

    tx_hash = str(tx_hash)

    # ------------------------------------------------------------------
    # Explicit transaction URL template
    # ------------------------------------------------------------------

    template = chain.get("explorer_tx_url")

    if template:
        return template.format(tx_hash=tx_hash)

    # ------------------------------------------------------------------
    # Explicit explorer base URL
    # ------------------------------------------------------------------

    base_url = chain.get("explorer_tx_base_url")

    if base_url:
        return (
            base_url.rstrip("/")
            + "/"
            + tx_hash
        )

    # ------------------------------------------------------------------
    # Chain-ID based defaults
    # ------------------------------------------------------------------

    chain_id = chain.get("chain_id")

    if chain_id is None:
        chain_id = chain.get("explorer_chain_id")

    defaults = {
        1: "https://etherscan.io/tx",
        42161: "https://arbiscan.io/tx",
        10: "https://optimistic.etherscan.io/tx",
        8453: "https://basescan.org/tx",
        137: "https://polygonscan.com/tx",
        43114: "https://snowtrace.io/tx",
    }

    if chain_id in defaults:
        return (
            defaults[chain_id]
            + "/"
            + tx_hash
        )

    # Monad should normally use an explicit explorer_tx_url or
    # explorer_tx_base_url in config.json.
    return None
