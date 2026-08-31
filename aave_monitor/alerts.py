"""
Build Telegram alert text for supply-change and utilization-crossing
events, including the "largest activity" and "liquidation context"
sections sourced from aave_monitor.events.

Optional local LLM insights can be appended to alerts. The LLM insight
is supplemental and never determines whether an alert fires.
"""

from .config import get_explorer_tx_url

from .events import (
    MAX_ACTIVITY_EVENTS,
    top_activity_records,
)

from .formatting import chain_label


def format_activity_record(
    chain,
    symbol,
    record,
):
    """
    Format one activity record for Telegram.

    `chain` may be either a chain name or chain configuration dictionary.
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
    don't themselves belong in the supply/utilization impact list.

    Example:

        monitored asset == collateralAsset
        receiveAToken == True

    In that case the liquidation is useful context, but it does not
    reduce total aToken supply.
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
    Build a supply-change Telegram alert.
    """

    from .formatting import fmt_money

    direction = (
        "📈 increased"
        if change_pct > 0
        else "📉 decreased"
    )

    lines = [
        (
            f"{direction} "
            f"*{chain_label(chain)} · {symbol}* "
            f"total supply by "
            f"*{abs(change_pct):.2f}%* since last check."
        ),
        (
            f"Supply: "
            f"{fmt_money(previous_supply)} → "
            f"{fmt_money(current_supply)} {symbol}"
        ),
    ]

    if (
        activity_records is not None
        and from_block is not None
        and to_block is not None
    ):
        append_activity_section(
            lines,
            chain,
            symbol,
            activity_records,
            "supply",
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
    Build a utilization threshold-crossing Telegram alert.
    """

    if crossed_above:
        message = (
            f"⚠️ *{chain_label(chain)} · {symbol}* "
            f"utilization just crossed the optimal point "
            f"({optimal_utilization * 100:.2f}%) "
            f"and entered *slope 2*.\n"
            f"Utilization: "
            f"*{utilization * 100:.2f}%*\n"
            f"Borrow APY: {borrow_apy:.2f}% · "
            f"Supply APY: {supply_apy:.2f}%"
        )
    else:
        message = (
            f"✅ *{chain_label(chain)} · {symbol}* "
            f"utilization dropped back below the optimal point "
            f"({optimal_utilization * 100:.2f}%), "
            f"back into *slope 1*.\n"
            f"Utilization: "
            f"*{utilization * 100:.2f}%*\n"
            f"Borrow APY: {borrow_apy:.2f}% · "
            f"Supply APY: {supply_apy:.2f}%"
        )

    lines = message.splitlines()

    if (
        activity_records is not None
        and from_block is not None
        and to_block is not None
    ):
        append_activity_section(
            lines,
            chain,
            symbol,
            activity_records,
            "utilization",
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
