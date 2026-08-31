"""
check_asset(): the per-reserve monitoring pass. Reads live reserve data
from the Pool + token contracts, compares it against the previous
state.json snapshot, and returns any alert messages plus the updated
snapshot to persist.

Activity logs (Supply/Withdraw/Borrow/Repay/LiquidationCall) are only
queried here -- via aave_monitor.events -- after a supply or utilization
threshold has actually fired.

Local LLM insights are also generated only after an alert has fired.

The LLM does not determine whether an alert should fire.
"""

import time

from web3 import Web3

from constants import RAY, ZERO_ADDRESS

from .alerts import (
    build_supply_change_message,
    build_utilization_crossing_message,
)
from .charts import generate_model_chart
from .events import get_relevant_activity_records
from .formatting import (
    chain_label,
    fmt_amount,
    fmt_money,
    shorten_address,
)
from .logging_setup import log
from .llm import generate_insight
from .pool_data import get_pool_reserve_data
from .rate_model import (
    build_model_change_message,
    get_interest_rate_model,
    model_parameters_changed,
)
from .reserve_config import (
    build_configuration_change_message,
    decode_reserve_configuration,
    detect_configuration_changes,
)
from .web3_client import get_token_total_supply


def _build_activity_context(activity_records):
    """
    Convert activity records into a compact, JSON-serializable structure
    suitable for the local LLM.

    Only include fields that are useful for explaining the alert.
    Transaction hashes are included because they provide traceability,
    but the LLM is explicitly instructed not to invent conclusions
    from them.
    """
    if not activity_records:
        return []

    activity = []

    for record in activity_records:
        item = {
            "category": record.get("category"),
            "label": record.get("label"),
            "amount": record.get("amount"),
            "direction": record.get("direction"),
            "block_number": record.get("block_number"),
            "transaction_hash": record.get("transaction_hash"),
        }

        activity.append(item)

    return activity


def check_asset(
    chain_name,
    w3,
    pool,
    asset_cfg,
    prev_state,
    default_supply_change_pct,
    previous_checked_block,
    current_block,
    max_block_range,
):
    symbol = asset_cfg["symbol"]
    address = Web3.to_checksum_address(asset_cfg["address"])
    decimals = asset_cfg["decimals"]
    supply_change_pct = asset_cfg.get(
        "supply_change_alert_pct",
        default_supply_change_pct,
    )

    messages = []
    chart_path = None
    new_state = dict(prev_state) if prev_state else {}

    # ------------------------------------------------------------------
    # Read Aave Pool reserve data
    # ------------------------------------------------------------------

    reserve_data = get_pool_reserve_data(pool, address)

    configuration = decode_reserve_configuration(
        reserve_data["configuration"]
    )

    # ------------------------------------------------------------------
    # Reserve configuration
    # ------------------------------------------------------------------

    previous_configuration = (
        prev_state.get("reserve_configuration")
        if prev_state
        else None
    )

    if previous_configuration is None:
        log.info(
            "%s · %s: initial reserve configuration recorded",
            chain_label(chain_name),
            symbol,
        )
    else:
        config_changes = detect_configuration_changes(
            previous_configuration,
            configuration,
        )

        if config_changes:
            log.warning(
                "%s · %s: RESERVE CONFIGURATION CHANGED",
                chain_label(chain_name),
                symbol,
            )

            messages.append(
                build_configuration_change_message(
                    chain_name,
                    symbol,
                    address,
                    config_changes,
                )
            )

    # ------------------------------------------------------------------
    # Token addresses
    # ------------------------------------------------------------------

    a_token_address = reserve_data["a_token_address"]

    stable_debt_token_address = reserve_data[
        "stable_debt_token_address"
    ]

    variable_debt_token_address = reserve_data[
        "variable_debt_token_address"
    ]

    # ------------------------------------------------------------------
    # Current supply / debt
    # ------------------------------------------------------------------

    total_a_token_raw = get_token_total_supply(
        w3,
        a_token_address,
    )

    if stable_debt_token_address.lower() == ZERO_ADDRESS.lower():
        total_stable_debt_raw = 0
    else:
        total_stable_debt_raw = get_token_total_supply(
            w3,
            stable_debt_token_address,
        )

    if variable_debt_token_address.lower() == ZERO_ADDRESS.lower():
        total_variable_debt_raw = 0
    else:
        total_variable_debt_raw = get_token_total_supply(
            w3,
            variable_debt_token_address,
        )

    # ------------------------------------------------------------------
    # Current rates
    # ------------------------------------------------------------------

    liquidity_rate_ray = reserve_data["current_liquidity_rate"]

    variable_borrow_rate_ray = reserve_data[
        "current_variable_borrow_rate"
    ]

    # ------------------------------------------------------------------
    # Supply / debt / utilization
    # ------------------------------------------------------------------

    total_supply = fmt_amount(
        total_a_token_raw,
        decimals,
    )

    total_stable_debt = fmt_amount(
        total_stable_debt_raw,
        decimals,
    )

    total_variable_debt = fmt_amount(
        total_variable_debt_raw,
        decimals,
    )

    total_debt = fmt_amount(
        total_stable_debt_raw + total_variable_debt_raw,
        decimals,
    )

    utilization = (
        total_debt / total_supply
        if total_supply > 0
        else 0.0
    )

    supply_apy = liquidity_rate_ray / RAY * 100
    borrow_apy = variable_borrow_rate_ray / RAY * 100

    # ------------------------------------------------------------------
    # Interest-rate model
    # ------------------------------------------------------------------

    interest_model = get_interest_rate_model(
        w3,
        pool,
        address,
        reserve_data=reserve_data,
    )

    optimal_utilization = (
        interest_model["optimal_usage_ratio"] / RAY
    )

    # ------------------------------------------------------------------
    # Derived quantitative context
    # ------------------------------------------------------------------

    utilization_pct = utilization * 100
    optimal_utilization_pct = optimal_utilization * 100

    utilization_vs_optimal_pct_points = (
        utilization_pct - optimal_utilization_pct
    )

    unused_supply_pct = max(
        0.0,
        (1.0 - utilization) * 100,
    )

    debt_to_supply_pct = (
        utilization_pct
    )

    rate_slope = (
        2
        if utilization >= optimal_utilization
        else 1
    )

    # ------------------------------------------------------------------
    # Interest-rate model change
    # ------------------------------------------------------------------

    previous_model = (
        prev_state.get("interest_rate_model")
        if prev_state
        else None
    )

    if previous_model is None:
        log.info(
            "%s · %s: initial interest-rate model recorded "
            "(strategy=%s, optimal=%.2f%%)",
            chain_label(chain_name),
            symbol,
            shorten_address(
                interest_model["strategy_address"]
            ),
            optimal_utilization * 100,
        )

    elif model_parameters_changed(
        previous_model,
        interest_model,
    ):
        log.warning(
            "%s · %s: INTEREST-RATE MODEL CHANGED",
            chain_label(chain_name),
            symbol,
        )

        messages.append(
            build_model_change_message(
                chain_name,
                symbol,
                previous_model,
                interest_model,
            )
        )

        chart_path = generate_model_chart(
            chain_name,
            symbol,
            previous_model,
            interest_model,
        )

    # ------------------------------------------------------------------
    # Determine utilization crossing
    # ------------------------------------------------------------------

    was_above = (
        prev_state.get("above_optimal")
        if prev_state
        else None
    )

    is_above = utilization >= optimal_utilization

    log.info(
        "%s · %s: utilization=%.2f%% | optimal=%.2f%% | "
        "supply=%s | debt=%s | borrow APY=%.2f%%",
        chain_label(chain_name),
        symbol,
        utilization_pct,
        optimal_utilization_pct,
        fmt_money(total_supply),
        fmt_money(total_debt),
        borrow_apy,
    )

    utilization_alert = (
        was_above is not None
        and is_above != was_above
    )

    # ------------------------------------------------------------------
    # Supply threshold
    # ------------------------------------------------------------------

    prev_supply = (
        prev_state.get("total_supply")
        if prev_state
        else None
    )

    supply_alert = False
    supply_change = None

    if prev_supply is not None and prev_supply > 0:
        supply_change = (
            (total_supply - prev_supply)
            / prev_supply
            * 100
        )

        supply_alert = (
            abs(supply_change) >= supply_change_pct
        )

    # ------------------------------------------------------------------
    # Activity logs
    #
    # IMPORTANT:
    # eth_getLogs is queried ONLY when a supply/utilization
    # threshold actually fires.
    # ------------------------------------------------------------------

    activity_records = []
    activity_from_block = None
    activity_to_block = None

    if (
        (utilization_alert or supply_alert)
        and previous_checked_block is not None
        and current_block > previous_checked_block
    ):
        activity_from_block = previous_checked_block + 1
        activity_to_block = current_block

        log.info(
            "%s · %s: threshold crossed; fetching activity "
            "events for blocks %d-%d",
            chain_label(chain_name),
            symbol,
            activity_from_block,
            activity_to_block,
        )

        activity_records = get_relevant_activity_records(
            w3,
            pool,
            address,
            decimals,
            activity_from_block,
            activity_to_block,
            max_block_range,
        )

        log.info(
            "%s · %s: found %d relevant activity records",
            chain_label(chain_name),
            symbol,
            len(activity_records),
        )

    # ------------------------------------------------------------------
    # Utilization alert
    # ------------------------------------------------------------------

    if utilization_alert:
        crossed_above = (
            is_above
            and not was_above
        )

        activity_context = _build_activity_context(
            activity_records
        )

        utilization_context = {
            "alert_type": "utilization_crossing",
            "chain": chain_name,
            "asset": symbol,

            "utilization_pct": round(
                utilization_pct,
                2,
            ),

            "optimal_utilization_pct": round(
                optimal_utilization_pct,
                2,
            ),

            "utilization_vs_optimal_pct_points": round(
                utilization_vs_optimal_pct_points,
                2,
            ),

            "supply": total_supply,
            "debt": total_debt,

            "debt_to_supply_pct": round(
                debt_to_supply_pct,
                2,
            ),

            "unused_supply_pct": round(
                unused_supply_pct,
                2,
            ),

            "borrow_apy_pct": round(
                borrow_apy,
                2,
            ),

            "supply_apy_pct": round(
                supply_apy,
                2,
            ),

            "rate_slope": rate_slope,

            "crossed_above_optimal": crossed_above,

            "activity": activity_context,
        }

        insight = generate_insight(
            utilization_context
        )

        messages.append(
            build_utilization_crossing_message(
                chain_name,
                symbol,
                utilization,
                optimal_utilization,
                borrow_apy,
                supply_apy,
                crossed_above,
                activity_records=activity_records,
                from_block=activity_from_block,
                to_block=activity_to_block,
                insight=insight,
            )
        )

    # ------------------------------------------------------------------
    # Supply alert
    # ------------------------------------------------------------------

    if supply_alert:
        activity_context = _build_activity_context(
            activity_records
        )

        supply_change_context = {
            "alert_type": "supply_change",
            "chain": chain_name,
            "asset": symbol,

            "previous_supply": prev_supply,
            "current_supply": total_supply,

            "supply_change_pct": round(
                supply_change,
                2,
            ),

            "supply_change_abs": (
                total_supply - prev_supply
            ),

            "utilization_pct": round(
                utilization_pct,
                2,
            ),

            "optimal_utilization_pct": round(
                optimal_utilization_pct,
                2,
            ),

            "utilization_vs_optimal_pct_points": round(
                utilization_vs_optimal_pct_points,
                2,
            ),

            "debt": total_debt,

            "debt_to_supply_pct": round(
                debt_to_supply_pct,
                2,
            ),

            "unused_supply_pct": round(
                unused_supply_pct,
                2,
            ),

            "borrow_apy_pct": round(
                borrow_apy,
                2,
            ),

            "supply_apy_pct": round(
                supply_apy,
                2,
            ),

            "rate_slope": rate_slope,

            "activity": activity_context,
        }

        insight = generate_insight(
            supply_change_context
        )

        messages.append(
            build_supply_change_message(
                chain_name,
                symbol,
                prev_supply,
                total_supply,
                supply_change,
                activity_records=activity_records,
                from_block=activity_from_block,
                to_block=activity_to_block,
                insight=insight,
            )
        )

    # ------------------------------------------------------------------
    # Save state
    # ------------------------------------------------------------------

    new_state["address"] = address
    new_state["symbol"] = symbol
    new_state["decimals"] = decimals

    new_state["a_token_address"] = (
        a_token_address
    )

    new_state["stable_debt_token_address"] = (
        stable_debt_token_address
    )

    new_state["variable_debt_token_address"] = (
        variable_debt_token_address
    )

    new_state["reserve_configuration"] = (
        configuration
    )

    new_state["above_optimal"] = is_above

    new_state["last_utilization"] = utilization

    new_state["optimal_utilization"] = (
        optimal_utilization
    )

    new_state["strategy_address"] = (
        interest_model["strategy_address"]
    )

    new_state["interest_rate_model"] = (
        interest_model
    )

    new_state["total_supply"] = total_supply

    new_state["total_stable_debt"] = (
        total_stable_debt
    )

    new_state["total_variable_debt"] = (
        total_variable_debt
    )

    new_state["total_debt"] = total_debt

    new_state["last_checked"] = int(
        time.time()
    )

    return messages, new_state, chart_path
