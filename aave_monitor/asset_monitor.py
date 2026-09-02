"""
Per-reserve Aave V3 risk monitoring.

check_asset() reads live reserve data, compares it against the previous
state snapshot, determines whether a meaningful risk signal has occurred,
optionally fetches the relevant Aave activity events, and returns:

    (messages, updated_state, chart_path)

The monitor remains deterministic:

- The monitor decides whether a signal fires.
- Absolute + relative significance filters reduce noise from small markets.
- Risk signals are derived from quantitative reserve data.
- Activity logs are fetched only when a meaningful signal fires.
- The LLM is used only to interpret an already-determined signal.
- The LLM never determines whether an alert should fire.

The current alert builders are intentionally preserved here. Phase 2 will
redesign those messages around the risk_signal structure created below.
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


# ---------------------------------------------------------------------------
# Risk-signal configuration
# ---------------------------------------------------------------------------

# Supply changes must satisfy BOTH:
#
#   1. the configured relative percentage threshold
#   2. an absolute dollar-equivalent threshold
#
# This prevents tiny markets from generating repeated alerts because a small
# nominal change represents a large percentage of supply.
#
# These are deliberately conservative starting values. We can tune them
# after observing the live feed.

DEFAULT_MIN_ABSOLUTE_SUPPLY_CHANGE = 250_000.0

# Market-size tiers allow the absolute significance requirement to scale with
# the size of the reserve.
#
# Example:
#   < $10M       -> $250K
#   $10M-$100M   -> $1M
#   $100M-$1B    -> $5M
#   >= $1B       -> $10M
#
# The first matching tier is used.

ABSOLUTE_CHANGE_TIERS = (
    (10_000_000.0, 250_000.0),
    (100_000_000.0, 1_000_000.0),
    (1_000_000_000.0, 5_000_000.0),
    (float("inf"), 10_000_000.0),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_min_absolute_supply_change(
    previous_supply,
    current_supply,
    asset_cfg,
):
    """
    Determine the minimum absolute supply change required for an alert.

    Asset-level configuration takes precedence:

        min_absolute_supply_change

    Otherwise a market-size tier is used.

    The market size is based on the larger of the previous and current
    supply values so that a meaningful withdrawal from a large market is not
    accidentally judged using the smaller post-withdrawal size.
    """

    configured = asset_cfg.get("min_absolute_supply_change")

    if configured is not None:
        return float(configured)

    market_size = max(
        float(previous_supply or 0.0),
        float(current_supply or 0.0),
    )

    for max_size, minimum_change in ABSOLUTE_CHANGE_TIERS:
        if market_size < max_size:
            return minimum_change

    return DEFAULT_MIN_ABSOLUTE_SUPPLY_CHANGE


def _safe_pct_change(current, previous):
    """Return percentage change, or None when a percentage is undefined."""

    if previous is None or previous == 0:
        return None

    return ((current - previous) / previous) * 100.0


def _build_activity_context(activity_records):
    """
    Convert activity records into a compact, JSON-serializable structure
    suitable for the local LLM.

    Only include fields that are useful for explaining the signal.

    Transaction hashes are included for traceability, but the LLM should
    not infer unsupported conclusions from them.
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


def _summarize_activity(activity_records):
    """
    Produce deterministic aggregate activity statistics.

    The exact activity-record schema is intentionally handled defensively
    because events.py may evolve during Phase 5.

    Returns totals that can be passed to the risk-signal and LLM layers.
    """

    summary = {
        "supply": 0.0,
        "withdraw": 0.0,
        "borrow": 0.0,
        "repay": 0.0,
        "liquidation": 0.0,
        "net_borrowing": 0.0,
        "largest_borrow": 0.0,
        "largest_withdraw": 0.0,
        "largest_supply": 0.0,
        "largest_repay": 0.0,
        "record_count": 0,
    }

    if not activity_records:
        return summary

    summary["record_count"] = len(activity_records)

    for record in activity_records:
        category = str(record.get("category") or "").lower()

        try:
            amount = float(record.get("amount") or 0.0)
        except (TypeError, ValueError):
            amount = 0.0

        amount = abs(amount)

        if category == "supply":
            summary["supply"] += amount
            summary["largest_supply"] = max(
                summary["largest_supply"],
                amount,
            )

        elif category == "withdraw":
            summary["withdraw"] += amount
            summary["largest_withdraw"] = max(
                summary["largest_withdraw"],
                amount,
            )

        elif category == "borrow":
            summary["borrow"] += amount
            summary["largest_borrow"] = max(
                summary["largest_borrow"],
                amount,
            )

        elif category == "repay":
            summary["repay"] += amount
            summary["largest_repay"] = max(
                summary["largest_repay"],
                amount,
            )

        elif category == "liquidation":
            summary["liquidation"] += amount

    summary["net_borrowing"] = (
        summary["borrow"] - summary["repay"]
    )

    return summary


def _classify_risk_signal(
    *,
    utilization_alert,
    crossed_above,
    utilization_change_pct_points,
    utilization_vs_optimal_pct_points,
    supply_change,
    supply_change_abs,
    supply_absolute_threshold_met,
    activity_summary,
    rate_slope,
):
    """
    Determine the primary deterministic risk-signal classification.

    This is intentionally conservative. It does not attempt to predict
    future prices or protocol failures.

    Possible values:

        utilization_stress
        liquidity_recovery
        borrowing_pressure
        withdrawal_pressure
        deleveraging
        liquidation_activity
        supply_growth
        supply_contraction
        utilization_change
        none
    """

    # Liquidations are intrinsically meaningful activity.
    if activity_summary["liquidation"] > 0:
        return "liquidation_activity"

    # Crossing from below to above optimal utilization is the clearest
    # transition into the steeper rate regime.
    if utilization_alert and crossed_above:
        return "utilization_stress"

    # Crossing back below optimal represents recovery from the higher-rate
    # regime, even if utilization remains high.
    if utilization_alert and not crossed_above:
        return "liquidity_recovery"

    # Large net borrowing combined with increasing utilization indicates
    # borrowing pressure.
    if (
        activity_summary["net_borrowing"] > 0
        and utilization_change_pct_points is not None
        and utilization_change_pct_points > 0
    ):
        return "borrowing_pressure"

    # Large withdrawals combined with falling utilization/supply can indicate
    # liquidity leaving the reserve.
    if (
        activity_summary["withdraw"] > 0
        and supply_change is not None
        and supply_change < 0
        and supply_absolute_threshold_met
    ):
        return "withdrawal_pressure"

    # Falling debt/utilization while repayments dominate borrowing.
    if (
        activity_summary["net_borrowing"] < 0
        and utilization_change_pct_points is not None
        and utilization_change_pct_points < 0
    ):
        return "deleveraging"

    # Significant supply movement without a stronger activity/risk category.
    if supply_change is not None and supply_absolute_threshold_met:
        if supply_change > 0:
            return "supply_growth"

        if supply_change < 0:
            return "supply_contraction"

    # A meaningful utilization move that did not cross optimal.
    if (
        utilization_change_pct_points is not None
        and abs(utilization_change_pct_points) >= 1.0
    ):
        return "utilization_change"

    # Preserve a useful classification when the reserve is already above
    # optimal and the rate curve is in slope 2.
    if (
        utilization_vs_optimal_pct_points > 0
        and rate_slope == 2
    ):
        return "utilization_stress"

    return "none"


def _build_risk_signal(
    *,
    chain_name,
    symbol,
    address,
    utilization_pct,
    optimal_utilization_pct,
    utilization_vs_optimal_pct_points,
    unused_supply_pct,
    total_supply,
    total_debt,
    borrow_apy,
    supply_apy,
    rate_slope,
    was_above,
    is_above,
    utilization_change_pct_points,
    previous_supply,
    supply_change,
    supply_change_abs,
    minimum_absolute_supply_change,
    supply_relative_threshold_met,
    supply_absolute_threshold_met,
    activity_summary,
    activity_records,
    trigger_types,
):
    """
    Build the canonical deterministic risk-signal object.

    This becomes the common data structure for Phase 2 alert formatting and
    the Phase 3 LLM interpretation layer.
    """

    crossed_above = (
        was_above is not None
        and is_above
        and not was_above
    )

    crossed_below = (
        was_above is not None
        and not is_above
        and was_above
    )

    risk_signal_type = _classify_risk_signal(
        utilization_alert=(
            "utilization_crossing" in trigger_types
        ),
        crossed_above=crossed_above,
        utilization_change_pct_points=utilization_change_pct_points,
        utilization_vs_optimal_pct_points=utilization_vs_optimal_pct_points,
        supply_change=supply_change,
        supply_change_abs=supply_change_abs,
        supply_absolute_threshold_met=supply_absolute_threshold_met,
        activity_summary=activity_summary,
        rate_slope=rate_slope,
    )

    if risk_signal_type == "none" and trigger_types:
        risk_signal_type = trigger_types[0]

    return {
        "signal_type": risk_signal_type,
        "trigger_types": list(trigger_types),

        "chain": chain_name,
        "asset": symbol,
        "address": address,

        "utilization_pct": round(utilization_pct, 4),
        "optimal_utilization_pct": round(
            optimal_utilization_pct,
            4,
        ),
        "utilization_vs_optimal_pct_points": round(
            utilization_vs_optimal_pct_points,
            4,
        ),
        "unused_supply_pct": round(
            unused_supply_pct,
            4,
        ),

        "supply": total_supply,
        "debt": total_debt,

        "borrow_apy_pct": round(
            borrow_apy,
            4,
        ),
        "supply_apy_pct": round(
            supply_apy,
            4,
        ),

        "rate_slope": rate_slope,

        "was_above_optimal": was_above,
        "is_above_optimal": is_above,
        "crossed_above_optimal": crossed_above,
        "crossed_below_optimal": crossed_below,

        "utilization_change_pct_points": (
            round(
                utilization_change_pct_points,
                4,
            )
            if utilization_change_pct_points is not None
            else None
        ),

        "previous_supply": previous_supply,
        "supply_change_pct": (
            round(supply_change, 4)
            if supply_change is not None
            else None
        ),
        "supply_change_abs": supply_change_abs,
        "minimum_absolute_supply_change": (
            minimum_absolute_supply_change
        ),
        "supply_relative_threshold_met": (
            supply_relative_threshold_met
        ),
        "supply_absolute_threshold_met": (
            supply_absolute_threshold_met
        ),

        "activity": activity_records,
        "activity_summary": activity_summary,
    }


# ---------------------------------------------------------------------------
# Main reserve monitor
# ---------------------------------------------------------------------------


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

    reserve_data = get_pool_reserve_data(
        pool,
        address,
    )

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

    if (
        stable_debt_token_address.lower()
        == ZERO_ADDRESS.lower()
    ):
        total_stable_debt_raw = 0
    else:
        total_stable_debt_raw = get_token_total_supply(
            w3,
            stable_debt_token_address,
        )

    if (
        variable_debt_token_address.lower()
        == ZERO_ADDRESS.lower()
    ):
        total_variable_debt_raw = 0
    else:
        total_variable_debt_raw = get_token_total_supply(
            w3,
            variable_debt_token_address,
        )

    # ------------------------------------------------------------------
    # Current rates
    # ------------------------------------------------------------------

    liquidity_rate_ray = reserve_data[
        "current_liquidity_rate"
    ]

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
        total_stable_debt_raw
        + total_variable_debt_raw,
        decimals,
    )

    utilization = (
        total_debt / total_supply
        if total_supply > 0
        else 0.0
    )

    supply_apy = (
        liquidity_rate_ray / RAY * 100
    )

    borrow_apy = (
        variable_borrow_rate_ray / RAY * 100
    )

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
    # Previous values
    # ------------------------------------------------------------------

    previous_utilization = (
        prev_state.get("last_utilization")
        if prev_state
        else None
    )

    previous_supply = (
        prev_state.get("total_supply")
        if prev_state
        else None
    )

    was_above = (
        prev_state.get("above_optimal")
        if prev_state
        else None
    )

    is_above = (
        utilization >= optimal_utilization
    )

    # ------------------------------------------------------------------
    # Derived quantitative context
    # ------------------------------------------------------------------

    utilization_pct = utilization * 100

    optimal_utilization_pct = (
        optimal_utilization * 100
    )

    utilization_vs_optimal_pct_points = (
        utilization_pct
        - optimal_utilization_pct
    )

    unused_supply_pct = max(
        0.0,
        (1.0 - utilization) * 100,
    )

    debt_to_supply_pct = utilization_pct

    rate_slope = (
        2
        if utilization >= optimal_utilization
        else 1
    )

    utilization_change_pct_points = None

    if previous_utilization is not None:
        utilization_change_pct_points = (
            utilization_pct
            - previous_utilization * 100
        )

    # ------------------------------------------------------------------
    # Supply change
    # ------------------------------------------------------------------

    supply_change = None
    supply_change_abs = None

    supply_relative_threshold_met = False
    supply_absolute_threshold_met = False

    minimum_absolute_supply_change = (
        None
    )

    if (
        previous_supply is not None
        and previous_supply > 0
    ):
        supply_change = _safe_pct_change(
            total_supply,
            previous_supply,
        )

        supply_change_abs = (
            total_supply
            - previous_supply
        )

        minimum_absolute_supply_change = (
            _get_min_absolute_supply_change(
                previous_supply,
                total_supply,
                asset_cfg,
            )
        )

        supply_relative_threshold_met = (
            abs(supply_change)
            >= supply_change_pct
        )

        supply_absolute_threshold_met = (
            abs(supply_change_abs)
            >= minimum_absolute_supply_change
        )

    # Both conditions must be true.

    supply_alert = (
        supply_relative_threshold_met
        and supply_absolute_threshold_met
    )

    if (
        supply_relative_threshold_met
        and not supply_absolute_threshold_met
    ):
        log.info(
            "%s · %s: supply moved %.2f%% "
            "(%s), below absolute significance "
            "threshold of %s",
            chain_label(chain_name),
            symbol,
            supply_change,
            fmt_money(abs(supply_change_abs)),
            fmt_money(
                minimum_absolute_supply_change
            ),
        )

    # ------------------------------------------------------------------
    # Utilization crossing
    # ------------------------------------------------------------------

    utilization_alert = (
        was_above is not None
        and is_above != was_above
    )

    crossed_above = (
        utilization_alert
        and is_above
        and not was_above
    )

    crossed_below = (
        utilization_alert
        and not is_above
        and was_above
    )

    # ------------------------------------------------------------------
    # Determine deterministic triggers
    # ------------------------------------------------------------------

    trigger_types = []

    if utilization_alert:
        trigger_types.append(
            "utilization_crossing"
        )

    if supply_alert:
        trigger_types.append(
            "significant_supply_change"
        )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    log.info(
        "%s · %s: utilization=%.2f%% | "
        "optimal=%.2f%% | supply=%s | debt=%s | "
        "borrow APY=%.2f%% | slope=%d",
        chain_label(chain_name),
        symbol,
        utilization_pct,
        optimal_utilization_pct,
        fmt_money(total_supply),
        fmt_money(total_debt),
        borrow_apy,
        rate_slope,
    )

    if utilization_change_pct_points is not None:
        log.info(
            "%s · %s: utilization change=%+.2f pp",
            chain_label(chain_name),
            symbol,
            utilization_change_pct_points,
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
    # Activity logs
    #
    # Activity is intentionally still lazy.
    #
    # We do NOT query eth_getLogs every polling cycle.
    # We only fetch activity after a deterministic signal fires.
    # ------------------------------------------------------------------

    activity_records = []
    activity_from_block = None
    activity_to_block = None

    if (
        trigger_types
        and previous_checked_block is not None
        and current_block > previous_checked_block
    ):
        activity_from_block = (
            previous_checked_block + 1
        )

        activity_to_block = current_block

        log.info(
            "%s · %s: risk signal triggered; "
            "fetching activity events for blocks %d-%d",
            chain_label(chain_name),
            symbol,
            activity_from_block,
            activity_to_block,
        )

        activity_records = (
            get_relevant_activity_records(
                w3,
                pool,
                address,
                decimals,
                activity_from_block,
                activity_to_block,
                max_block_range,
            )
        )

        log.info(
            "%s · %s: found %d relevant activity records",
            chain_label(chain_name),
            symbol,
            len(activity_records),
        )

    activity_summary = _summarize_activity(
        activity_records
    )

    # ------------------------------------------------------------------
    # Build the canonical risk signal
    # ------------------------------------------------------------------

    risk_signal = _build_risk_signal(
        chain_name=chain_name,
        symbol=symbol,
        address=address,
        utilization_pct=utilization_pct,
        optimal_utilization_pct=optimal_utilization_pct,
        utilization_vs_optimal_pct_points=(
            utilization_vs_optimal_pct_points
        ),
        unused_supply_pct=unused_supply_pct,
        total_supply=total_supply,
        total_debt=total_debt,
        borrow_apy=borrow_apy,
        supply_apy=supply_apy,
        rate_slope=rate_slope,
        was_above=was_above,
        is_above=is_above,
        utilization_change_pct_points=(
            utilization_change_pct_points
        ),
        previous_supply=previous_supply,
        supply_change=supply_change,
        supply_change_abs=supply_change_abs,
        minimum_absolute_supply_change=(
            minimum_absolute_supply_change
        ),
        supply_relative_threshold_met=(
            supply_relative_threshold_met
        ),
        supply_absolute_threshold_met=(
            supply_absolute_threshold_met
        ),
        activity_summary=activity_summary,
        activity_records=_build_activity_context(
            activity_records
        ),
        trigger_types=trigger_types,
    )

    # ------------------------------------------------------------------
    # Log risk classification
    # ------------------------------------------------------------------

    if trigger_types:
        log.warning(
            "%s · %s: RISK SIGNAL = %s | "
            "utilization=%+.2f pp vs previous | "
            "vs optimal=%+.2f pp",
            chain_label(chain_name),
            symbol,
            risk_signal["signal_type"],
            (
                utilization_change_pct_points
                if utilization_change_pct_points is not None
                else 0.0
            ),
            utilization_vs_optimal_pct_points,
        )

    # ------------------------------------------------------------------
    # Utilization signal
    #
    # Phase 2 will replace the current alert builder with a richer
    # risk-signal presentation. For now, preserve the existing builder.
    # ------------------------------------------------------------------

    if utilization_alert:
        activity_context = _build_activity_context(
            activity_records
        )

        utilization_context = {
            "alert_type": "utilization_crossing",
            "risk_signal": risk_signal,

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

            "previous_utilization_pct": (
                round(
                    previous_utilization * 100,
                    2,
                )
                if previous_utilization is not None
                else None
            ),

            "utilization_change_pct_points": (
                round(
                    utilization_change_pct_points,
                    2,
                )
                if utilization_change_pct_points is not None
                else None
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
            "crossed_below_optimal": crossed_below,

            "activity": activity_context,
            "activity_summary": activity_summary,
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
    # Significant supply signal
    #
    # Important:
    #
    # A percentage change alone is no longer enough.
    # Both relative and absolute thresholds must be satisfied.
    # ------------------------------------------------------------------

    if supply_alert:
        activity_context = _build_activity_context(
            activity_records
        )

        supply_change_context = {
            "alert_type": "supply_change",
            "risk_signal": risk_signal,

            "chain": chain_name,
            "asset": symbol,

            "previous_supply": previous_supply,
            "current_supply": total_supply,

            "supply_change_pct": round(
                supply_change,
                2,
            ),

            "supply_change_abs": (
                supply_change_abs
            ),

            "minimum_absolute_supply_change": (
                minimum_absolute_supply_change
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

            "utilization_change_pct_points": (
                round(
                    utilization_change_pct_points,
                    2,
                )
                if utilization_change_pct_points is not None
                else None
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
            "activity_summary": activity_summary,
        }

        insight = generate_insight(
            supply_change_context
        )

        messages.append(
            build_supply_change_message(
                chain_name,
                symbol,
                previous_supply,
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
    #
    # Keep the existing state keys for compatibility and add the richer
    # quantitative/risk context for future signal detection.
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

    new_state["last_utilization"] = (
        utilization
    )

    new_state["optimal_utilization"] = (
        optimal_utilization
    )

    new_state["strategy_address"] = (
        interest_model["strategy_address"]
    )

    new_state["interest_rate_model"] = (
        interest_model
    )

    new_state["total_supply"] = (
        total_supply
    )

    new_state["total_stable_debt"] = (
        total_stable_debt
    )

    new_state["total_variable_debt"] = (
        total_variable_debt
    )

    new_state["total_debt"] = (
        total_debt
    )

    # ------------------------------------------------------------------
    # New quantitative state
    # ------------------------------------------------------------------

    new_state["last_utilization_pct"] = (
        utilization_pct
    )

    new_state["last_optimal_utilization_pct"] = (
        optimal_utilization_pct
    )

    new_state["last_unused_supply_pct"] = (
        unused_supply_pct
    )

    new_state["last_borrow_apy_pct"] = (
        borrow_apy
    )

    new_state["last_supply_apy_pct"] = (
        supply_apy
    )

    new_state["last_rate_slope"] = (
        rate_slope
    )

    new_state["last_signal_type"] = (
        risk_signal["signal_type"]
    )

    new_state["last_signal_timestamp"] = (
        int(time.time())
    )

    new_state["last_checked"] = int(
        time.time()
    )

    return (
        messages,
        new_state,
        chart_path,
    )
