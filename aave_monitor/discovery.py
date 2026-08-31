"""Reserve discovery: listing an Aave Pool's reserves, detecting reserves
that were onboarded/removed since the last discovery pass, and deciding
when discovery is next due (default: every 24 hours).
"""

import time

from web3 import Web3

from .formatting import chain_label
from .logging_setup import log
from .state import get_previous_chain_state
from .telegram import send_telegram
from .web3_client import connect_chain, get_asset_metadata


def discover_reserves(w3, pool):
    reserve_addresses = pool.functions.getReservesList().call()

    reserves = {}

    for raw_address in reserve_addresses:
        address = Web3.to_checksum_address(raw_address)

        try:
            symbol, decimals = get_asset_metadata(w3, address)
            reserves[address] = {"address": address, "symbol": symbol, "decimals": decimals}
        except Exception as e:
            log.error("Could not discover reserve %s: %s", address, e)

    return reserves


def discover_chain(chain):
    context = connect_chain(chain)
    reserves = discover_reserves(context["w3"], context["pool"])
    return context, reserves


def build_reserve_added_message(chain, reserve):
    return (
        f"🟢 *{chain_label(chain)} · {reserve['symbol']} reserve onboarded*\n\n"
        f"*Asset:* {reserve['symbol']}\n"
        f"*Address:* `{reserve['address']}`\n"
        f"*Decimals:* {reserve['decimals']}"
    )


def build_reserve_removed_message(chain, reserve):
    return (
        f"🔴 *{chain_label(chain)} · {reserve['symbol']} reserve offboarded*\n\n"
        f"*Asset:* {reserve['symbol']}\n"
        f"*Address:* `{reserve['address']}`"
    )


def detect_chain_reserve_changes(chain_state, reserves):
    previous_reserves = chain_state.get("discovered_reserves", {})
    previous_addresses = set(previous_reserves.keys())
    current_addresses = set(reserves.keys())

    return (
        current_addresses - previous_addresses,
        previous_addresses - current_addresses,
    )


def discovery_is_due(chain_state, discovery_interval_seconds, force=False):
    if force:
        return True

    last_discovery = int(chain_state.get("last_discovery", 0))

    if last_discovery <= 0:
        return True

    elapsed = time.time() - last_discovery
    return elapsed >= discovery_interval_seconds


def get_discovery_status(chain_state, discovery_interval_seconds):
    """Human-readable description of the current discovery schedule.

    Cached reserves are considered the active reserve set between discovery
    periods. Restarting the process does not reset last_discovery.
    """

    last_discovery = int(chain_state.get("last_discovery", 0))
    discovered_reserves = chain_state.get("discovered_reserves", {})

    if not discovered_reserves:
        return {"has_cache": False, "due": True, "seconds_remaining": 0}

    if last_discovery <= 0:
        return {"has_cache": True, "due": True, "seconds_remaining": 0}

    next_discovery = last_discovery + discovery_interval_seconds
    seconds_remaining = max(0, next_discovery - time.time())

    return {
        "has_cache": True,
        "due": seconds_remaining <= 0,
        "seconds_remaining": seconds_remaining,
    }


def format_duration(seconds):
    seconds = max(0, int(seconds))

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h {minutes}m"

    if hours > 0:
        return f"{hours}h {minutes}m"

    return f"{minutes}m"


def update_chain_discovery(chain, state, bot_token, chat_id):
    name = chain["name"]
    chain_state = get_previous_chain_state(state, name)

    try:
        context, reserves = discover_chain(chain)

        log.info("%s: discovered %d Aave reserves.", chain_label(name), len(reserves))

        previous_reserves = chain_state.get("discovered_reserves", {})
        added, removed = detect_chain_reserve_changes(chain_state, reserves)

        if not previous_reserves:
            log.info("%s: establishing initial reserve baseline.", chain_label(name))
        else:
            for address in added:
                reserve = reserves[address]

                log.warning(
                    "%s: NEW AAVE RESERVE: %s (%s)", chain_label(name), reserve["symbol"], address
                )

                send_telegram(bot_token, chat_id, build_reserve_added_message(name, reserve))

            for address in removed:
                reserve = previous_reserves[address]

                log.warning(
                    "%s: AAVE RESERVE REMOVED: %s (%s)", chain_label(name), reserve["symbol"], address
                )

                send_telegram(bot_token, chat_id, build_reserve_removed_message(name, reserve))

                chain_state.setdefault("assets", {}).pop(address, None)

        chain_state["discovered_reserves"] = reserves
        chain_state["last_discovery"] = int(time.time())

        return context, reserves, True

    except Exception:
        log.exception("%s: reserve discovery failed.", chain_label(name))
        return None, chain_state.get("discovered_reserves", {}), False
