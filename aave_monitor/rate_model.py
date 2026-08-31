"""Reading a reserve's interest-rate strategy parameters, detecting changes
to them, and calculating the variable borrow rate curve (base + slope1 up
to the optimal utilization kink, then + slope2 beyond it).
"""

from constants import INTEREST_RATE_STRATEGY_ABI, RAY, ZERO_ADDRESS

from .formatting import fmt_rate, fmt_ratio, shorten_address, chain_label
from .pool_data import get_pool_reserve_data


def get_interest_rate_model(w3, pool, asset_address, reserve_data=None):
    if reserve_data is None:
        reserve_data = get_pool_reserve_data(pool, asset_address)

    strategy_address = reserve_data["interest_rate_strategy_address"]

    if strategy_address.lower() == ZERO_ADDRESS.lower():
        raise ValueError(f"No interest rate strategy configured for {asset_address}")

    strategy = w3.eth.contract(address=strategy_address, abi=INTEREST_RATE_STRATEGY_ABI)
    rate_data = strategy.functions.getInterestRateData(asset_address).call()

    return {
        "strategy_address": strategy_address,
        "optimal_usage_ratio": int(rate_data[0]),
        "base_variable_borrow_rate": int(rate_data[1]),
        "variable_rate_slope1": int(rate_data[2]),
        "variable_rate_slope2": int(rate_data[3]),
    }


def model_parameters_changed(old_model, new_model):
    if old_model is None:
        return False

    fields = [
        "strategy_address",
        "optimal_usage_ratio",
        "base_variable_borrow_rate",
        "variable_rate_slope1",
        "variable_rate_slope2",
    ]

    return any(old_model.get(f) != new_model.get(f) for f in fields)


def model_changes(old_model, new_model):
    changes = []

    if old_model.get("strategy_address") != new_model.get("strategy_address"):
        changes.append((
            "Strategy",
            shorten_address(old_model["strategy_address"]),
            shorten_address(new_model["strategy_address"]),
        ))

    if old_model.get("optimal_usage_ratio") != new_model.get("optimal_usage_ratio"):
        changes.append((
            "Optimal utilization",
            f"{fmt_ratio(old_model['optimal_usage_ratio']):.2f}%",
            f"{fmt_ratio(new_model['optimal_usage_ratio']):.2f}%",
        ))

    if old_model.get("base_variable_borrow_rate") != new_model.get("base_variable_borrow_rate"):
        changes.append((
            "Base variable borrow rate",
            f"{fmt_rate(old_model['base_variable_borrow_rate']):.2f}%",
            f"{fmt_rate(new_model['base_variable_borrow_rate']):.2f}%",
        ))

    if old_model.get("variable_rate_slope1") != new_model.get("variable_rate_slope1"):
        changes.append((
            "Variable slope 1",
            f"{fmt_rate(old_model['variable_rate_slope1']):.2f}%",
            f"{fmt_rate(new_model['variable_rate_slope1']):.2f}%",
        ))

    if old_model.get("variable_rate_slope2") != new_model.get("variable_rate_slope2"):
        changes.append((
            "Variable slope 2",
            f"{fmt_rate(old_model['variable_rate_slope2']):.2f}%",
            f"{fmt_rate(new_model['variable_rate_slope2']):.2f}%",
        ))

    return changes


def calculate_variable_borrow_rate(utilization, model):
    optimal = model["optimal_usage_ratio"] / RAY
    base = model["base_variable_borrow_rate"] / RAY
    slope1 = model["variable_rate_slope1"] / RAY
    slope2 = model["variable_rate_slope2"] / RAY

    if optimal <= 0:
        return base

    if optimal >= 1:
        return base + slope1

    if utilization <= optimal:
        return base + slope1 * utilization / optimal

    return base + slope1 + slope2 * (utilization - optimal) / (1 - optimal)


def build_model_change_message(chain, symbol, old_model, new_model):
    changes = model_changes(old_model, new_model)

    lines = [
        f"⚠️ *{chain_label(chain)} · {symbol} interest-rate model changed*",
        "",
    ]

    for name, old_value, new_value in changes:
        lines.append(f"*{name}:* {old_value} → {new_value}")

    lines.extend(["", f"Strategy: `{new_model['strategy_address']}`"])

    return "\n".join(lines)
