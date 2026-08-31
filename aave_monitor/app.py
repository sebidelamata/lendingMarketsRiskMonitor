"""Entry point: loads config/state, connects to each chain, runs the
initial startup pass, sends the startup Telegram message, then loops
forever running a monitoring cycle every `poll_interval_seconds`.
"""

import time

from .chain_monitor import DEFAULT_DISCOVERY_INTERVAL_SECONDS, process_chain
from .config import get_chains, load_config, load_state, save_state
from .discovery import format_duration, get_discovery_status
from .events import DEFAULT_MAX_BLOCK_RANGE
from .formatting import chain_label
from .logging_setup import log
from .state import get_previous_chain_state
from .telegram import send_telegram

DEFAULT_POLL_INTERVAL_SECONDS = 30 * 60


def send_startup_message(chains, chain_status, bot_token, chat_id):
    lines = ["🤖 *Aave V3 RPC monitor started*", "", "*Chains:*"]

    for chain in chains:
        name = chain["name"]
        lines.append(f"🟢 {chain_label(name)}" if chain_status.get(name) else f"🔴 {chain_label(name)}")

    lines.extend([
        "",
        "Monitoring:",
        "• Reserve onboarding / removal",
        "• Reserve configuration",
        "• Utilization crossings",
        "• Supply changes",
        "• Interest-rate model changes",
        "• Direction-aware liquidation activity",
        "• Top 5 activity on triggered alerts",
        "",
        "Liquidation handling:",
        "• Collateral liquidation → supply/utilization increase when underlying leaves pool",
        "• Collateral liquidation with receiveAToken → no total supply change",
        "• Debt liquidation → debt/utilization decrease",
        "",
        "Reserve discovery: every 24 hours",
        "Activity logs: only fetched when a threshold fires",
    ])

    send_telegram(bot_token, chat_id, "\n".join(lines))


def _run_startup_pass(chains, state, config, bot_token, chat_id):
    """First pass at process start: uses cached reserves where the
    discovery interval hasn't elapsed yet, otherwise discovers fresh.
    """

    discovery_interval_seconds = config.get(
        "discovery_interval_seconds", DEFAULT_DISCOVERY_INTERVAL_SECONDS
    )

    chain_status = {}

    for chain in chains:
        name = chain["name"]

        try:
            chain_state = get_previous_chain_state(state, name)
            cached_reserves = chain_state.get("discovered_reserves", {})

            if cached_reserves:
                discovery_status = get_discovery_status(
                    chain_state,
                    chain.get("discovery_interval_seconds", discovery_interval_seconds),
                )

                if discovery_status["due"]:
                    log.info(
                        "%s: cached reserves exist but discovery interval is already due; "
                        "running scheduled discovery.",
                        chain_label(name),
                    )
                else:
                    log.info(
                        "%s: startup cache found with %d reserves; skipping discovery and "
                        "continuing existing discovery countdown (%s remaining).",
                        chain_label(name), len(cached_reserves),
                        format_duration(discovery_status["seconds_remaining"]),
                    )
            else:
                log.info("%s: no cached reserves found; initial discovery required.", chain_label(name))

            process_chain(chain, state, config, bot_token, chat_id, force_discovery=False)
            chain_status[name] = True

        except Exception as e:
            chain_status[name] = False
            log.exception("%s: startup processing failed: %s", chain_label(name), e)

    return chain_status


def main():
    config = load_config()
    state = load_state()

    bot_token = config["telegram_bot_token"]
    chat_id = config["telegram_chat_id"]

    poll_seconds = config.get("poll_interval_seconds", DEFAULT_POLL_INTERVAL_SECONDS)
    discovery_interval_seconds = config.get(
        "discovery_interval_seconds", DEFAULT_DISCOVERY_INTERVAL_SECONDS
    )
    max_block_range = config.get("activity_log_max_block_range", DEFAULT_MAX_BLOCK_RANGE)

    chains = get_chains(config)

    log.info(
        "Configured %d Aave chains: %s",
        len(chains), ", ".join(chain_label(c["name"]) for c in chains),
    )
    log.info("Monitoring interval: %d seconds (%.1f minutes)", poll_seconds, poll_seconds / 60)
    log.info(
        "Reserve discovery interval: %d seconds (%.1f hours)",
        discovery_interval_seconds, discovery_interval_seconds / 3600,
    )
    log.info("Activity log max block range: %d", max_block_range)

    # Initial startup.
    #
    # IMPORTANT: we intentionally DO NOT force discovery here. If state.json
    # already contains discovered reserves for a chain, process_chain() uses
    # those cached reserves and respects the existing last_discovery
    # timestamp. A chain with no cached reserves still discovers immediately
    # because discovery_is_due() returns True when no discovery has ever
    # occurred.
    chain_status = _run_startup_pass(chains, state, config, bot_token, chat_id)

    save_state(state)
    send_startup_message(chains, chain_status, bot_token, chat_id)

    # Monitoring loop.
    while True:
        cycle_started = time.time()
        log.info("Starting monitoring cycle.")

        for chain in chains:
            name = chain["name"]

            try:
                process_chain(chain, state, config, bot_token, chat_id, force_discovery=False)
            except Exception as e:
                log.exception("%s: monitoring cycle failed: %s", chain_label(name), e)

        save_state(state)

        elapsed = time.time() - cycle_started
        log.info("Monitoring cycle completed in %.2f seconds.", elapsed)

        sleep_seconds = max(0, poll_seconds - elapsed)
        log.info("Next monitoring cycle in %.2f seconds.", sleep_seconds)

        time.sleep(sleep_seconds)
