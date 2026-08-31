"""Per-cycle orchestration for a single chain: run discovery if due, then
call check_asset() for every known reserve and dispatch any resulting
alerts to Telegram.
"""

from .asset_monitor import check_asset
from .discovery import discovery_is_due, get_discovery_status, format_duration, update_chain_discovery
from .events import DEFAULT_MAX_BLOCK_RANGE
from .formatting import chain_label
from .logging_setup import log
from .state import get_previous_chain_state
from .telegram import send_telegram, send_telegram_photo
from .web3_client import connect_chain

DEFAULT_DISCOVERY_INTERVAL_SECONDS = 24 * 60 * 60


def monitor_chain(chain, context, reserves, state, config, bot_token, chat_id):
    name = chain["name"]

    if context is None:
        raise ValueError(f"{name}: no RPC context available")

    w3 = context["w3"]
    pool = context["pool"]

    chain_state = get_previous_chain_state(state, name)

    default_supply_change_pct = chain.get(
        "default_supply_change_alert_pct",
        config.get("default_supply_change_alert_pct", 5.0),
    )

    max_block_range = int(
        chain.get(
            "activity_log_max_block_range",
            config.get("activity_log_max_block_range", DEFAULT_MAX_BLOCK_RANGE),
        )
    )

    previous_assets = chain_state.setdefault("assets", {})

    # One block number for the whole monitoring cycle.
    current_block = w3.eth.block_number
    previous_checked_block = chain_state.get("last_metrics_block")

    if previous_checked_block is None:
        log.info("%s: establishing activity block baseline at %d", chain_label(name), current_block)
    else:
        log.info(
            "%s: activity baseline block=%d, current block=%d",
            chain_label(name), previous_checked_block, current_block,
        )

    for address, reserve in reserves.items():
        symbol = reserve["symbol"]
        previous_asset_state = previous_assets.get(address, {})

        asset_cfg = {
            "symbol": symbol,
            "address": address,
            "decimals": reserve["decimals"],
            "supply_change_alert_pct": reserve.get(
                "supply_change_alert_pct", default_supply_change_pct
            ),
        }

        try:
            messages, new_asset_state, chart_path = check_asset(
                name, w3, pool, asset_cfg, previous_asset_state, default_supply_change_pct,
                previous_checked_block, current_block, max_block_range,
            )

            previous_assets[address] = new_asset_state

            for index, message in enumerate(messages):
                log.info(
                    "ALERT [%s · %s]: %s", chain_label(name), symbol, message.splitlines()[0]
                )

                if chart_path is not None and index == 0:
                    send_telegram_photo(bot_token, chat_id, chart_path, message)
                else:
                    send_telegram(bot_token, chat_id, message)

            if chart_path is not None:
                try:
                    chart_path.unlink(missing_ok=True)
                except OSError:
                    pass

        except Exception as e:
            log.exception("Error checking %s · %s: %s", chain_label(name), symbol, e)

    # Advance monitoring block after all reserves have been attempted.
    chain_state["last_metrics_block"] = current_block


def process_chain(chain, state, config, bot_token, chat_id, force_discovery=False):
    name = chain["name"]
    chain_state = get_previous_chain_state(state, name)

    discovery_interval_seconds = chain.get(
        "discovery_interval_seconds",
        config.get("discovery_interval_seconds", DEFAULT_DISCOVERY_INTERVAL_SECONDS),
    )

    cached_reserves = chain_state.get("discovered_reserves", {})
    has_cached_reserves = bool(cached_reserves)

    should_discover = discovery_is_due(chain_state, discovery_interval_seconds, force=force_discovery)

    context = None
    reserves = cached_reserves

    if should_discover:
        log.info("%s: reserve discovery is due.", chain_label(name))

        context, discovered_reserves, discovery_succeeded = update_chain_discovery(
            chain, state, bot_token, chat_id
        )

        reserves = discovered_reserves

        if discovery_succeeded:
            log.info("%s: reserve discovery completed successfully.", chain_label(name))
        else:
            log.warning(
                "%s: discovery failed; continuing with %d cached reserves.",
                chain_label(name), len(reserves),
            )

    elif has_cached_reserves:
        discovery_status = get_discovery_status(chain_state, discovery_interval_seconds)

        log.info(
            "%s: using %d cached reserves; next discovery in %s.",
            chain_label(name), len(reserves),
            format_duration(discovery_status["seconds_remaining"]),
        )

    if context is None:
        context = connect_chain(chain)

    if not reserves:
        log.warning("%s: no discovered reserves available to monitor.", chain_label(name))
        return context

    log.info("%s: monitoring %d known reserves.", chain_label(name), len(reserves))

    monitor_chain(chain, context, reserves, state, config, bot_token, chat_id)

    return context
