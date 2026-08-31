"""Rendering the before/after variable-borrow-rate curve chart that
accompanies an interest-rate model change alert.
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from constants import RAY

from .formatting import chain_label
from .rate_model import calculate_variable_borrow_rate

BASE_DIR = Path(__file__).resolve().parent.parent


def generate_model_chart(chain, symbol, old_model, new_model):
    utilizations = [i / 1000 for i in range(1001)]
    utilization_percent = [u * 100 for u in utilizations]

    old_rates = [calculate_variable_borrow_rate(u, old_model) * 100 for u in utilizations]
    new_rates = [calculate_variable_borrow_rate(u, new_model) * 100 for u in utilizations]

    old_optimal = old_model["optimal_usage_ratio"] / RAY
    new_optimal = new_model["optimal_usage_ratio"] / RAY

    old_kink_rate = (
        old_model["base_variable_borrow_rate"] / RAY
        + old_model["variable_rate_slope1"] / RAY
    ) * 100

    new_kink_rate = (
        new_model["base_variable_borrow_rate"] / RAY
        + new_model["variable_rate_slope1"] / RAY
    ) * 100

    old_base_rate = old_model["base_variable_borrow_rate"] / RAY * 100
    new_base_rate = new_model["base_variable_borrow_rate"] / RAY * 100

    filename = f"{chain.lower()}_{symbol.lower()}_interest_rate_model.png"
    chart_path = BASE_DIR / filename

    fig, ax = plt.subplots(figsize=(10, 6), dpi=150)

    ax.plot(utilization_percent, old_rates, linestyle=":", linewidth=2.5, label="Previous model")
    ax.plot(utilization_percent, new_rates, linestyle="-", linewidth=2.5, label="New model")

    ax.scatter(
        [old_optimal * 100], [old_kink_rate], s=45, zorder=5,
        label=f"Previous kink ({old_optimal * 100:.2f}%)",
    )
    ax.scatter(
        [new_optimal * 100], [new_kink_rate], s=45, zorder=5,
        label=f"New kink ({new_optimal * 100:.2f}%)",
    )

    ax.scatter([0], [old_base_rate], s=35, zorder=5)
    ax.scatter([0], [new_base_rate], s=35, zorder=5)

    ax.annotate(
        f"Old kink\n{old_optimal * 100:.2f}% / {old_kink_rate:.2f}%",
        xy=(old_optimal * 100, old_kink_rate),
        xytext=(8, 8), textcoords="offset points", fontsize=8,
    )
    ax.annotate(
        f"New kink\n{new_optimal * 100:.2f}% / {new_kink_rate:.2f}%",
        xy=(new_optimal * 100, new_kink_rate),
        xytext=(8, -28), textcoords="offset points", fontsize=8,
    )

    ax.set_xlabel("Utilization (%)")
    ax.set_ylabel("Variable Borrow APR (%)")
    ax.set_title(f"{chain_label(chain)} · {symbol} Variable Borrow Interest Rate Model")
    ax.set_xlim(0, 100)

    max_rate = max(max(old_rates), max(new_rates))
    min_rate = min(min(old_rates), min(new_rates))
    rate_range = max_rate - min_rate

    if rate_range <= 0:
        rate_range = max(abs(max_rate), 1)

    lower_bound = max(0, min_rate - rate_range * 0.08)
    upper_bound = max_rate + rate_range * 0.12

    ax.set_ylim(lower_bound, upper_bound)
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=9)

    fig.tight_layout()
    fig.savefig(chart_path, bbox_inches="tight")
    plt.close(fig)

    return chart_path
