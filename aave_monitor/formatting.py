"""Small, dependency-free string/number formatting helpers."""

from constants import RAY


def fmt_amount(raw, decimals):
    return raw / (10 ** decimals)


def fmt_money(n):
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"

    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"

    if n >= 1_000:
        return f"{n / 1_000:.2f}K"

    return f"{n:.2f}"


def fmt_rate(ray):
    return ray / RAY * 100


def fmt_ratio(ray):
    return ray / RAY * 100


def shorten_address(address):
    return f"{address[:6]}...{address[-4:]}"


def chain_label(chain_name):
    return chain_name.replace("_", " ").title()
