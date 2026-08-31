"""Decoding the packed Aave reserve `configuration` bitmap, and detecting
+ formatting changes to it (active/frozen/paused/borrowing flags, etc.).
"""

from constants import (
    IS_ACTIVE_START_BIT_POSITION,
    IS_FROZEN_START_BIT_POSITION,
    BORROWING_ENABLED_START_BIT_POSITION,
    STABLE_BORROWING_ENABLED_START_BIT_POSITION,
    IS_PAUSED_START_BIT_POSITION,
    BORROWABLE_IN_ISOLATION_START_BIT_POSITION,
    SILOED_BORROWING_START_BIT_POSITION,
)

from .formatting import chain_label

CONFIG_ACTIVE_BIT = IS_ACTIVE_START_BIT_POSITION
CONFIG_FROZEN_BIT = IS_FROZEN_START_BIT_POSITION
CONFIG_BORROWING_ENABLED_BIT = BORROWING_ENABLED_START_BIT_POSITION
CONFIG_STABLE_BORROWING_ENABLED_BIT = STABLE_BORROWING_ENABLED_START_BIT_POSITION
CONFIG_PAUSED_BIT = IS_PAUSED_START_BIT_POSITION
CONFIG_BORROWABLE_IN_ISOLATION_BIT = BORROWABLE_IN_ISOLATION_START_BIT_POSITION
CONFIG_SILOED_BORROWING_BIT = SILOED_BORROWING_START_BIT_POSITION

RESERVE_CONFIG_LABELS = {
    "active": "Active",
    "frozen": "Frozen",
    "borrowing_enabled": "Borrowing",
    "stable_borrowing_enabled": "Stable borrowing",
    "paused": "Paused",
    "borrowable_in_isolation": "Borrowable in isolation",
    "siloed_borrowing_enabled": "Siloed borrowing",
}


def bit_is_set(configuration, bit):
    return bool((configuration >> bit) & 1)


def decode_reserve_configuration(configuration):
    return {
        "active": bit_is_set(configuration, CONFIG_ACTIVE_BIT),
        "frozen": bit_is_set(configuration, CONFIG_FROZEN_BIT),
        "borrowing_enabled": bit_is_set(configuration, CONFIG_BORROWING_ENABLED_BIT),
        "stable_borrowing_enabled": bit_is_set(
            configuration, CONFIG_STABLE_BORROWING_ENABLED_BIT
        ),
        "paused": bit_is_set(configuration, CONFIG_PAUSED_BIT),
        "borrowable_in_isolation": bit_is_set(
            configuration, CONFIG_BORROWABLE_IN_ISOLATION_BIT
        ),
        "siloed_borrowing_enabled": bit_is_set(configuration, CONFIG_SILOED_BORROWING_BIT),
    }


def detect_configuration_changes(old_config, new_config):
    changes = []

    for field, label in RESERVE_CONFIG_LABELS.items():
        old_value = old_config.get(field)
        new_value = new_config.get(field)

        if old_value is not None and new_value is not None and old_value != new_value:
            changes.append((label, old_value, new_value))

    return changes


def build_configuration_change_message(chain, symbol, address, changes):
    lines = [
        f"⚙️ *{chain_label(chain)} · {symbol} reserve configuration changed*",
        "",
    ]

    for label, old_value, new_value in changes:
        old_text = "enabled" if old_value else "disabled"
        new_text = "enabled" if new_value else "disabled"
        lines.append(f"*{label}:* {old_text} → {new_text}")

    lines.extend(["", f"Asset: `{address}`"])

    return "\n".join(lines)
