"""
Build Telegram alert text from deterministic DeFi risk signals.

The asset monitor is responsible for deciding whether a risk signal exists
and for calculating the quantitative evidence behind it.

This module is presentation-only:
    risk_signal -> Telegram message

Optional local LLM insights may be appended to an alert, but the LLM never
determines whether an alert fires.

Legacy builders are retained as compatibility wrappers for callers that still
use:
    build_supply_change_message()
    build_utilization_crossing_message()
"""

from .config import get_explorer_tx_url
from .events import (
    MAX_ACTIVITY_EVENTS,
    top_activity_records,
)
from .formatting import chain_label, fmt_money


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _pct(value):
    """Format a decimal percentage value such as 0.8123 as 81.23%."""
    if value is None:
        return "—"
    return f"{value * 100:.2f}%"


def _pp(value):
    """Format a decimal utilization change as percentage points."""
    if value is None:
        return "—"

    sign = "+" if value > 0 else ""
    return f"{sign}{value * 100:.2f} pp"


def _money(value, symbol=None):
    """
    Format a monetary/token amount.

    fmt_money() is used for consistency with the existing alert system.
    """
    if value is None:
        return "—"

    text = fmt_money(value)

    if symbol:
        return f"{text} {symbol}"

    return text


def _signed_money(value, symbol=None):
    """Format a signed monetary/token amount."""
    if value is None:
        return "—"

    sign = "+" if value > 0 else ""
    return f"{sign}{_money(abs(value), symbol)}" if value != 0 else _money(
        0,
        symbol,
    )


def _signal_title(signal_type):
    """Return a human-readable title for a deterministic risk regime."""

    titles = {
        "utilization_stress": "⚠️ UTILIZATION STRESS",
        "liquidity_recovery": "✅ LIQUIDITY RECOVERY",
        "borrowing_pressure": "⚠️ BORROWING PRESSURE",
        "withdrawal_pressure": "⚠️ WITHDRAWAL PRESSURE",
        "deleveraging": "📉 DELEVERAGING",
        "liquidation_activity": "🚨 LIQUIDATION ACTIVITY",
        "supply_growth": "📈 SUPPLY GROWTH",
        "supply_contraction": "📉 SUPPLY CONTRACTION",
        "utilization_change": "📊 UTILIZATION CHANGE",
    }

    return titles.get(
        signal_type,
        "📊 DEFI RISK SIGNAL",
    )


def _signal_description(signal_type):
    """Return a concise explanation of what the signal represents."""

    descriptions = {
        "utilization_stress": (
            "Utilization crossed above the optimal point, "
            "moving the reserve into the steeper borrow-rate slope."
        ),
        "liquidity_recovery": (
            "Utilization moved back below the optimal point, "
            "returning the reserve to the lower borrow-rate slope."
        ),
        "borrowing_pressure": (
            "Borrowing activity is increasing utilization and "
            "reducing available liquidity."
        ),
        "withdrawal_pressure": (
            "Liquidity is leaving the reserve while total supply "
            "is declining."
        ),
        "deleveraging": (
            "Repayment activity is reducing outstanding debt "
            "and utilization."
        ),
        "liquidation_activity": (
            "Liquidation activity was detected for the monitored reserve."
        ),
        "supply_growth": (
            "Reserve supply increased by a significant amount."
        ),
        "supply_contraction": (
            "Reserve supply decreased by a significant amount."
        ),
        "utilization_change": (
            "Utilization moved materially since the previous observation."
        ),
    }

    return descriptions.get(
        signal_type,
        "A material change was detected in the monitored reserve.",
    )


# ---------------------------------------------------------------------------
# Activity formatting
# ---------------------------------------------------------------------------

def format_activity_record(
    chain,
    symbol,
    record,
):
    """
    Format one activity record for Telegram.

    `chain` may be either a chain name or a chain configuration dictionary.
    """

    tx_hash = record["transaction_hash"]

    explorer_url = get_explorer_tx_url(
        chain,
        tx_hash,
    )

    if explorer_url:
        transaction_text = (
            f"[View transaction]({explorer_url})"
        )
    else:
        transaction_text = f"`{tx_hash}`"

    direction = record.get("direction")

    direction_text = (
        f" — {direction}"
        if direction
        else ""
    )

    return (
        f"• *{record['label']}* "
        f"{record['amount']:,.2f} {symbol}"
        f"{direction_text} · "
        f"block {record['block_number']} · "
        f"{transaction_text}"
    )


def append_activity_section(
    lines,
    chain,
    symbol,
    records,
    category,
    from_block,
    to_block,
):
    """
    Append the largest activity records for a category.
    """

    top_records = top_activity_records(
        records,
        category,
    )

    if not top_records:
        return

    lines.extend(
        [
            "",
            f"*Largest activity since block {from_block:,}:*",
        ]
    )

    for record in top_records:
        lines.append(
            format_activity_record(
                chain,
                symbol,
                record,
            )
        )


def append_liquidation_context_section(
    lines,
    chain,
    symbol,
    records,
    from_block,
    to_block,
):
    """
    Report liquidation events relevant to the monitored reserve that
    don't themselves belong in the primary supply/utilization activity list.
    """

    relevant = [
        record
        for record in records
        if record.get("category") == "liquidation_context"
    ]

    if not relevant:
        return

    relevant.sort(
        key=lambda record: record.get(
            "amount_raw",
            0,
        ),
        reverse=True,
    )

    relevant = relevant[:MAX_ACTIVITY_EVENTS]

    lines.extend(
        [
            "",
            f"*Liquidation context since block {from_block:,}:*",
        ]
    )

    for record in relevant:
        tx_hash = record["transaction_hash"]

        explorer_url = get_explorer_tx_url(
            chain,
            tx_hash,
        )

        if explorer_url:
            transaction_text = (
                f"[View transaction]({explorer_url})"
            )
        else:
            transaction_text = f"`{tx_hash}`"

        direction = record.get(
            "direction",
            "",
        )

        lines.append(
            f"• *{record['label']}* "
            f"{record['amount']:,.2f} {symbol} "
            f"— {direction} · "
            f"block {record['block_number']} · "
            f"{transaction_text}"
        )


def _append_activity_evidence(
    lines,
    signal,
):
    """
    Append aggregate activity evidence from the canonical risk signal.

    This is deliberately separate from the individual transaction section.
    The aggregate numbers explain WHY the signal matters; transaction records
    provide supporting detail.
    """

    activity = signal.get("activity") or {}

    supply = activity.get("supply", 0.0)
    withdraw = activity.get("withdraw", 0.0)
    borrow = activity.get("borrow", 0.0)
    repay = activity.get("repay", 0.0)
    liquidation = activity.get("liquidation", 0.0)
    net_borrowing = activity.get("net_borrowing")

    largest_borrow = activity.get("largest_borrow")
    largest_withdraw = activity.get("largest_withdraw")
    largest_supply = activity.get("largest_supply")
    largest_repay = activity.get("largest_repay")

    record_count = activity.get("record_count")

    has_activity = any(
        value
        for value in (
            supply,
            withdraw,
            borrow,
            repay,
            liquidation,
        )
    )

    if not has_activity:
        return

    lines.extend(
        [
            "",
            "*Activity evidence:*",
        ]
    )

    if supply:
        lines.append(
            f"• Supply deposits: {_money(supply)}"
        )

    if withdraw:
        lines.append(
            f"• Withdrawals: {_money(withdraw)}"
        )

    if borrow:
        lines.append(
            f"• Borrowed: {_money(borrow)}"
        )

    if repay:
        lines.append(
            f"• Repaid: {_money(repay)}"
        )

    if liquidation:
        lines.append(
            f"• Liquidations: {_money(liquidation)}"
        )

    if net_borrowing is not None:
        lines.append(
            f"• Net borrowing: {_signed_money(net_borrowing)}"
        )

    if largest_borrow:
        lines.append(
            f"• Largest borrow: {_money(largest_borrow)}"
        )

    if largest_withdraw:
        lines.append(
            f"• Largest withdrawal: {_money(largest_withdraw)}"
        )

    if largest_supply:
        lines.append(
            f"• Largest supply: {_money(largest_supply)}"
        )

    if largest_repay:
        lines.append(
            f"• Largest repayment: {_money(largest_repay)}"
        )

    if record_count:
        lines.append(
            f"• Activity events: {record_count}"
        )


# ---------------------------------------------------------------------------
# Market-state evidence
# ---------------------------------------------------------------------------

def _append_market_evidence(
    lines,
    signal,
):
    """
    Append the quantitative market state associated with a risk signal.
    """

    utilization = signal.get("utilization")
    optimal = signal.get("optimal")
    supply = signal.get("supply")
    debt = signal.get("debt")
    unused_supply = signal.get("unused_supply")

    borrow_apy = signal.get("borrow_apy")
    supply_apy = signal.get("supply_apy")

    rate_slope = signal.get("rate_slope")

    utilization_change = signal.get(
        "utilization_change"
    )

    previous_utilization = signal.get(
        "previous_utilization"
    )

    previous_supply = signal.get(
        "previous_supply"
    )

    supply_change = signal.get(
        "supply_change"
    )

    supply_change_pct = signal.get(
        "supply_change_pct"
    )

    lines.extend(
        [
            "",
            "*Market state:*",
        ]
    )

    if (
        previous_utilization is not None
        and utilization is not None
    ):
        lines.append(
            f"• Utilization: "
            f"{_pct(previous_utilization)} → "
            f"*{_pct(utilization)}*"
        )
    elif utilization is not None:
        lines.append(
            f"• Utilization: *{_pct(utilization)}*"
        )

    if optimal is not None:
        lines.append(
            f"• Optimal utilization: {_pct(optimal)}"
        )

    if (
        utilization is not None
        and optimal is not None
    ):
        difference = utilization - optimal

        if difference >= 0:
            lines.append(
                f"• Above optimal by: {_pp(difference)}"
            )
        else:
            lines.append(
                f"• Below optimal by: {_pp(abs(difference))}"
            )

    if utilization_change is not None:
        lines.append(
            f"• Utilization change: {_pp(utilization_change)}"
        )

    if supply is not None:
        if previous_supply is not None:
            lines.append(
                f"• Supply: "
                f"{_money(previous_supply)} → "
                f"*{_money(supply)}*"
            )
        else:
            lines.append(
                f"• Supply: *{_money(supply)}*"
            )

    if supply_change is not None:
        lines.append(
            f"• Absolute supply change: "
            f"{_signed_money(supply_change)}"
        )

    if supply_change_pct is not None:
        sign = "+" if supply_change_pct > 0 else ""

        lines.append(
            f"• Supply change: "
            f"{sign}{supply_change_pct:.2f}%"
        )

    if debt is not None:
        lines.append(
            f"• Debt: {_money(debt)}"
        )

    if unused_supply is not None:
        lines.append(
            f"• Available liquidity: "
            f"{_money(unused_supply)}"
        )

    if borrow_apy is not None:
        lines.append(
            f"• Borrow APY: {borrow_apy:.2f}%"
        )

    if supply_apy is not None:
        lines.append(
            f"• Supply APY: {supply_apy:.2f}%"
        )

    if rate_slope is not None:
        lines.append(
            f"• Rate slope: {rate_slope}"
        )


def _append_threshold_evidence(
    lines,
    signal,
):
    """
    Show the deterministic thresholds that were relevant to the signal.

    This is intentionally secondary to the actual market evidence.
    """

    supply_threshold = signal.get(
        "min_absolute_supply_change"
    )

    relative_threshold = signal.get(
        "supply_change_threshold"
    )

    supply_change = signal.get(
        "supply_change"
    )

    supply_change_pct = signal.get(
        "supply_change_pct"
    )

    if (
        supply_threshold is None
        and relative_threshold is None
    ):
        return

    lines.extend(
        [
            "",
            "*Signal criteria:*",
        ]
    )

    if relative_threshold is not None:
        lines.append(
            f"• Relative threshold: "
            f"≥{relative_threshold:.2f}%"
        )

    if supply_threshold is not None:
        lines.append(
            f"• Absolute threshold: "
            f"≥{_money(supply_threshold)}"
        )

    if (
        supply_change is not None
        and supply_change_pct is not None
    ):
        lines.append(
            f"• Observed: "
            f"{abs(supply_change_pct):.2f}% / "
            f"{_money(abs(supply_change))}"
        )


# ---------------------------------------------------------------------------
# LLM insight
# ---------------------------------------------------------------------------

def append_insight_section(
    lines,
    insight,
):
    """
    Append an optional local LLM insight.

    The insight has already been cleaned and Telegram-Markdown escaped
    by aave_monitor.llm.
    """

    if not insight:
        return

    lines.extend(
        [
            "",
            f"*Insight:* {insight}",
        ]
    )


# ---------------------------------------------------------------------------
# Risk-signal message builder
# ---------------------------------------------------------------------------

def build_risk_signal_message(
    risk_signal,
    insight=None,
):
    """
    Build a Telegram message from a canonical deterministic risk signal.

    The risk signal is expected to be produced by asset_monitor.py.

    The function is deliberately defensive so that a missing optional field
    does not prevent a deterministic alert from being delivered.
    """

    if not risk_signal:
        return ""

    signal_type = risk_signal.get(
        "signal_type",
        "unknown",
    )

    chain = risk_signal.get(
        "chain",
        "",
    )

    symbol = risk_signal.get(
        "asset",
        risk_signal.get(
            "symbol",
            "",
        ),
    )

    title = _signal_title(signal_type)

    lines = [
        title,
        "",
        f"*{chain_label(chain)} · {symbol}*",
        "",
        _signal_description(signal_type),
    ]

    # Core quantitative evidence.
    _append_market_evidence(
        lines,
        risk_signal,
    )

    # Activity evidence.
    _append_activity_evidence(
        lines,
        risk_signal,
    )

    # Show thresholds only when they are actually relevant.
    if signal_type in {
        "supply_growth",
        "supply_contraction",
    }:
        _append_threshold_evidence(
            lines,
            risk_signal,
        )

    # Individual transaction evidence.
    activity_records = risk_signal.get(
        "activity_records"
    )

    if activity_records is None:
        activity_records = risk_signal.get(
            "records"
        )

    from_block = risk_signal.get(
        "from_block"
    )

    to_block = risk_signal.get(
        "to_block"
    )

    if (
        activity_records is not None
        and from_block is not None
        and to_block is not None
    ):
        category = {
            "supply_growth": "supply",
            "supply_contraction": "supply",
            "borrowing_pressure": "utilization",
            "withdrawal_pressure": "supply",
            "deleveraging": "utilization",
            "utilization_stress": "utilization",
            "liquidity_recovery": "utilization",
            "utilization_change": "utilization",
            "liquidation_activity": "utilization",
        }.get(
            signal_type,
            "utilization",
        )

        append_activity_section(
            lines,
            chain,
            symbol,
            activity_records,
            category,
            from_block,
            to_block,
        )

        append_liquidation_context_section(
            lines,
            chain,
            symbol,
            activity_records,
            from_block,
            to_block,
        )

    append_insight_section(
        lines,
        insight,
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Compatibility wrappers
# ---------------------------------------------------------------------------

def build_supply_change_message(
    chain,
    symbol,
    previous_supply,
    current_supply,
    change_pct,
    activity_records=None,
    from_block=None,
    to_block=None,
    insight=None,
):
    """
    Compatibility wrapper for the previous supply-change alert API.

    New code should preferably pass a canonical risk_signal to
    build_risk_signal_message().
    """

    absolute_change = (
        current_supply - previous_supply
    )

    signal_type = (
        "supply_growth"
        if absolute_change > 0
        else "supply_contraction"
    )

    risk_signal = {
        "signal_type": signal_type,
        "chain": chain,
        "asset": symbol,
        "previous_supply": previous_supply,
        "supply": current_supply,
        "supply_change": absolute_change,
        "supply_change_pct": change_pct,
        "activity_records": activity_records,
        "from_block": from_block,
        "to_block": to_block,
    }

    return build_risk_signal_message(
        risk_signal,
        insight=insight,
    )


def build_utilization_crossing_message(
    chain,
    symbol,
    utilization,
    optimal_utilization,
    borrow_apy,
    supply_apy,
    crossed_above,
    activity_records=None,
    from_block=None,
    to_block=None,
    insight=None,
):
    """
    Compatibility wrapper for the previous utilization-crossing API.

    New code should preferably pass a canonical risk_signal to
    build_risk_signal_message().
    """

    signal_type = (
        "utilization_stress"
        if crossed_above
        else "liquidity_recovery"
    )

    risk_signal = {
        "signal_type": signal_type,
        "chain": chain,
        "asset": symbol,
        "utilization": utilization,
        "optimal": optimal_utilization,
        "borrow_apy": borrow_apy,
        "supply_apy": supply_apy,
        "rate_slope": 2 if crossed_above else 1,
        "activity_records": activity_records,
        "from_block": from_block,
        "to_block": to_block,
    }

    return build_risk_signal_message(
        risk_signal,
        insight=insight,
    )
