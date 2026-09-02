"""
Local LLM insight generation using Ollama.

The LLM is used ONLY to interpret an already-generated deterministic
DeFi risk signal.

The deterministic monitoring system decides:
    - whether an alert fires
    - what risk regime was detected
    - the quantitative metrics supporting that signal

The LLM does NOT decide whether something is risky.

Ollama runs locally on the Raspberry Pi, so no external LLM API
or internet connection is required for inference.
"""

import json
import os
import re

import requests

from .logging_setup import log


OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://127.0.0.1:11434/api/generate",
)

DEFAULT_MODEL = "qwen2.5:1.5b"

OLLAMA_TIMEOUT_SECONDS = 180

MAX_INSIGHT_CHARS = 500


SYSTEM_PROMPT = """
You are a senior DeFi risk analyst writing a short analytical insight
for a professional Aave V3 risk-monitoring channel.

The monitoring system has ALREADY detected and classified a risk signal.

Your job is NOT to decide whether the signal is valid or risky.

Your job is to provide ANALYSIS BEYOND THE STATISTICS ALREADY SHOWN
IN THE ALERT.

This distinction is critical.

The alert already displays the important numbers.

DO NOT simply repeat those numbers.

DO NOT restate what the alert says.

DO NOT write sentences such as:

"The utilization is 82.17%, above the 80% optimal level."

That is NOT an insight. That is a restatement.

Instead, explain what the RELATIONSHIP BETWEEN THE NUMBERS implies.

Think like a risk analyst, not a summarizer.

GOOD ANALYSIS:

"Borrowing is outpacing repayment, indicating the utilization increase
is being driven by expanding debt rather than a contraction in supply.
Because the reserve has entered the steeper rate regime, continued
borrowing would face progressively higher marginal borrowing costs."

This adds interpretation instead of repeating the alert.

ANALYTICAL FRAMEWORK:

Ask yourself:

1. What is driving the observed change?

2. Which supplied metrics support that interpretation?

3. What second-order consequence follows from the current state?

4. Does the activity reinforce, weaken, or explain the detected signal?

5. Is there a meaningful interaction between liquidity, debt,
   utilization, rates, and activity?

Only state conclusions supported by the supplied data.

UTILIZATION:

For utilization stress, do not merely say utilization increased.

Determine whether the evidence points toward:

- borrowing-driven utilization pressure
- supply-withdrawal-driven utilization pressure
- a combination of both
- insufficient evidence to identify the driver

Then explain the consequence.

For example:

- Borrowing increasing faster than repayment means debt is expanding.
- Withdrawals reducing supply while debt remains elevated reduce the
  liquidity buffer available against outstanding debt.
- Entering slope 2 means marginal borrowing becomes more expensive,
  creating a stronger rate response to additional utilization.
- If utilization rises while borrowing activity is small relative to
  the reserve, do not exaggerate the activity as the cause.
- If activity data does not establish the driver, explicitly say so.

SUPPLY CHANGES:

Do not merely say supply increased or decreased.

Consider what that means relative to debt and utilization.

For example:

- Supply growth can provide additional liquidity headroom.
- Supply contraction can make existing debt represent a larger share
  of available liquidity.
- If debt is also changing, consider whether the two movements offset
  or reinforce each other.
- Do not claim causation unless the supplied activity data supports it.

BORROWING:

Do not merely repeat the borrow amount.

Compare borrowing with repayment when both are supplied.

A positive net borrowing flow means debt is expanding over the
observation window.

A negative net borrowing flow means repayments exceed borrowing.

Explain how that interacts with utilization or available liquidity.

WITHDRAWALS:

Do not merely repeat the withdrawal amount.

Consider whether withdrawals are reducing the liquidity buffer while
debt remains elevated.

LIQUIDATIONS:

Do not automatically describe liquidation activity as evidence of
systemic risk.

Explain what the liquidation activity means in the context of the
supplied debt, supply, and utilization data.

IMPORTANT:

The alert itself already shows:

- utilization
- optimal utilization
- supply
- debt
- available liquidity
- APYs
- rate slope
- activity amounts

Therefore, your insight should NOT simply repeat those values.

Use numbers only when they are necessary to establish a relationship
or support an analytical conclusion.

For example:

BAD:
"Utilization increased to 82.17% and is 2.17 percentage points above
optimal."

GOOD:
"Net borrowing exceeded repayment by $9.4M, supporting a debt-driven
increase in utilization rather than a supply contraction."

BAD:
"Available liquidity is $222M."

GOOD:
"The reserve's liquidity buffer is being consumed by continued net
borrowing, leaving less capacity to absorb additional demand before
utilization moves further into the steep rate regime."

The GOOD examples add interpretation.

Do not invent anything.

Do not infer external market conditions.

Do not speculate about token prices.

Do not predict liquidation.

Do not claim insolvency.

Do not give investment advice.

Do not claim an activity caused a change unless the supplied data
supports that conclusion.

If the supplied data cannot establish a driver, say that the driver
cannot be determined from the observed activity.

OUTPUT:

Write exactly 1-2 sentences.

Target approximately 250-400 characters.

Maximum 500 characters.

The insight should answer:

"Why does this combination of observations matter?"

NOT:

"What are the observations?"

Do not start with:

- "The signal indicates..."
- "The utilization is..."
- "The supply is..."
- "This means..."
- "This suggests..."

Avoid generic AI language such as:

- "This is significant"
- "This highlights"
- "This demonstrates"
- "This indicates increased risk"

unless immediately followed by genuinely new analytical reasoning.

No headings.
No bullets.
No emojis.
No markdown.
No quotation marks.
"""


def _clean_insight(text):
    """
    Clean and constrain the LLM response before sending it to Telegram.

    Prefer complete sentences when enforcing the character limit.
    """

    if not text:
        return None

    text = text.strip()

    # Remove accidental surrounding quotes.
    text = text.strip("\"'")

    # Collapse excessive whitespace.
    text = re.sub(r"\s+", " ", text)

    if not text:
        return None

    # Remove accidental markdown formatting.
    text = text.replace("**", "")
    text = text.replace("__", "")

    # Split into complete sentences.
    sentences = re.split(
        r"(?<=[.!?])\s+",
        text,
    )

    sentences = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
    ]

    # Keep at most two sentences.
    sentences = sentences[:2]

    if not sentences:
        return None

    result = ""

    for sentence in sentences:
        candidate = (
            sentence
            if not result
            else f"{result} {sentence}"
        )

        if len(candidate) > MAX_INSIGHT_CHARS:
            break

        result = candidate

    if result:
        return result

    # Last-resort fallback for an unusually long first sentence.
    return (
        sentences[0][:MAX_INSIGHT_CHARS]
        .rsplit(" ", 1)[0]
        .rstrip(".,;:")
        + "..."
    )


def _escape_telegram_markdown(text):
    """
    Escape characters that could interfere with Telegram legacy Markdown.
    """

    if not text:
        return text

    for char in (
        "\\",
        "_",
        "*",
        "`",
        "[",
    ):
        text = text.replace(
            char,
            "\\" + char,
        )

    return text


def _prepare_risk_signal(risk_signal):
    """
    Prepare the deterministic risk signal for the LLM.

    Large transaction-level record lists are removed because the LLM
    should reason from the aggregate evidence rather than attempting
    to summarize every transaction.
    """

    if not isinstance(risk_signal, dict):
        return risk_signal

    signal = dict(risk_signal)

    activity_records = signal.pop(
        "activity_records",
        None,
    )

    if activity_records is not None:
        signal["activity_record_count"] = len(
            activity_records
        )

    signal.pop(
        "records",
        None,
    )

    return signal


def generate_insight(
    risk_signal,
    model=DEFAULT_MODEL,
):
    """
    Generate a concise analytical interpretation of an already-triggered
    deterministic risk signal.

    Parameters
    ----------
    risk_signal : dict
        Canonical risk signal produced by asset_monitor.py.

    model : str
        Ollama model name.

    Returns
    -------
    str | None
        Telegram-Markdown-safe insight, or None if generation fails.
    """

    if not risk_signal:
        log.warning(
            "Cannot generate LLM insight: empty risk signal."
        )
        return None

    if not isinstance(risk_signal, dict):
        log.warning(
            "Cannot generate LLM insight: risk signal is not a dict."
        )
        return None

    structured_signal = _prepare_risk_signal(
        risk_signal
    )

    signal_type = structured_signal.get(
        "signal_type",
        "unknown",
    )

    signal_json = json.dumps(
        structured_signal,
        indent=2,
        sort_keys=True,
        default=str,
    )

    prompt = (
        "You are analyzing an already-triggered deterministic "
        "Aave V3 risk signal.\n\n"

        "IMPORTANT: The alert already displays the statistics. "
        "Do NOT restate them.\n\n"

        "Your task is to identify the most useful SECOND-ORDER "
        "INTERPRETATION of the supplied data.\n\n"

        "Ask:\n"
        "- What is driving the observed change?\n"
        "- Do borrowing, repayment, withdrawals, or supply changes "
        "support that explanation?\n"
        "- What consequence follows from the interaction of these "
        "metrics?\n"
        "- What does this imply for liquidity, borrowing conditions, "
        "or rate sensitivity?\n\n"

        "Do not simply repeat utilization, supply, debt, or liquidity "
        "values that are already visible in the alert.\n\n"

        f"DETERMINISTIC RISK SIGNAL: {signal_type}\n\n"

        "RISK SIGNAL DATA:\n"
        f"{signal_json}\n\n"

        "Write exactly 1-2 concise sentences explaining WHY the "
        "combination of observations matters.\n\n"

        "The output must contain analysis rather than a statistical "
        "summary. Use a number only when it supports a relationship "
        "or analytical conclusion.\n\n"

        "If the data does not establish a driver, say so rather than "
        "inventing one."
    )

    payload = {
        "model": model,
        "system": SYSTEM_PROMPT,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 80,
            "top_p": 0.9,
        },
    }

    try:
        response = requests.post(
            OLLAMA_URL,
            json=payload,
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )

        response.raise_for_status()

        data = response.json()

        insight = _clean_insight(
            data.get("response")
        )

        if not insight:
            log.warning(
                "Ollama returned an empty insight for risk signal %s.",
                signal_type,
            )
            return None

        log.info(
            "Generated local LLM insight for %s using %s (%d chars).",
            signal_type,
            model,
            len(insight),
        )

        return _escape_telegram_markdown(
            insight
        )

    except requests.Timeout as e:
        log.warning(
            "Ollama request timed out after %ds for %s: %s",
            OLLAMA_TIMEOUT_SECONDS,
            signal_type,
            e,
        )
        return None

    except requests.RequestException as e:
        log.warning(
            "Local Ollama request failed for %s: %s",
            signal_type,
            e,
        )
        return None

    except (ValueError, TypeError) as e:
        log.warning(
            "Could not parse Ollama response for %s: %s",
            signal_type,
            e,
        )
        return None

    except Exception as e:
        log.exception(
            "Unexpected local LLM error for %s: %s",
            signal_type,
            e,
        )
        return None
