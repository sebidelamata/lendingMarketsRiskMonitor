"""
Local LLM insight generation using Ollama.

The LLM is used ONLY after an alert has already been generated.

It does not determine whether an alert should fire.

Ollama runs locally on the Raspberry Pi, so no external LLM API
or internet connection is required for inference.
"""

import json
import re

import requests

from .logging_setup import log


OLLAMA_URL = (
    "http://127.0.0.1:11434/api/generate"
)

DEFAULT_MODEL = "qwen2.5:1.5b"

OLLAMA_TIMEOUT_SECONDS = 180

MAX_INSIGHT_CHARS = 500


SYSTEM_PROMPT = """
You are an objective DeFi quantitative risk analyst monitoring Aave V3
markets.

You are writing a short analytical note for a professional DeFi
risk-monitoring Telegram channel.

The alert has ALREADY fired. Do not decide whether the alert should
have fired.

Your job is to explain the most useful risk or liquidity implication
of the supplied numbers.

Aave V3 concepts you should understand:

- Utilization = total debt / total supplied liquidity.
- Optimal utilization is the boundary between interest-rate model
  slope 1 and slope 2.
- Above optimal utilization, borrowing costs generally rise more
  steeply under the standard two-slope model.
- High utilization means less immediately available liquidity
  relative to debt.
- A supply increase generally adds liquidity.
- A supply decrease can reduce available liquidity and increase
  utilization if debt remains unchanged.
- Borrowing increases debt and utilization.
- Repayment reduces debt and utilization.
- Withdrawals reduce supplied liquidity and can increase utilization
  if debt remains unchanged.
- Liquidations can affect collateral supply, debt, and utilization
  differently.

ANALYTICAL PRIORITIES:

For utilization alerts:

1. Calculate or use the supplied distance from optimal utilization.
2. Explain how far the reserve is into slope 2 or slope 1.
3. Compare debt with total supply.
4. Quantify the remaining unused supply when available.
5. Consider the borrow APY as evidence of current borrowing conditions.
6. Explain the practical liquidity implication.
7. If activity records exist, use them to identify evidence that may
   explain the change.
8. If activity records are empty, say that the supplied data does not
   establish what drove the crossing when appropriate.

For supply-change alerts:

1. Quantify the size and direction of the supply change.
2. Consider the resulting utilization.
3. Consider debt and remaining unused supply.
4. Use activity records when available to identify whether supply,
   withdrawal, borrowing, repayment, or liquidation activity provides
   evidence for the change.
5. Do not claim causation unless the supplied events support it.

IMPORTANT:

- Do NOT simply restate the alert.
- Add quantitative interpretation.
- Use only supplied data.
- Do not invent missing metrics.
- Do not invent events.
- Do not speculate about future prices.
- Do not give investment advice.
- Do not claim an event caused a metric change unless the supplied
  activity data directly supports that conclusion.
- Do not confuse supply with debt.
- Do not describe high utilization as more liquid.
- Do not imply that high utilization itself means borrowers will
  default.
- Do not claim insolvency or imminent liquidation without supplied
  evidence.
- Do not repeat the asset name unless necessary.
- Prefer concrete numbers over generic phrases.
- Avoid filler such as "this is significant" or "this indicates"
  unless immediately followed by a specific implication.

OUTPUT:

- Write 1-2 concise sentences.
- Aim for approximately 250-400 characters.
- Maximum 500 characters.
- No headings.
- No bullets.
- No emojis.
- No markdown.
- No quotation marks.
"""


def _clean_insight(text):
    """
    Clean and constrain the LLM response before sending it to Telegram.
    """

    if not text:
        return None

    text = text.strip()

    # Remove accidental surrounding quotes.
    text = text.strip("\"'")

    # Collapse excessive whitespace.
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    if not text:
        return None

    if len(text) > MAX_INSIGHT_CHARS:
        text = (
            text[:MAX_INSIGHT_CHARS]
            .rsplit(" ", 1)[0]
            + "..."
        )

    return text


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


def generate_insight(
    context,
    model=DEFAULT_MODEL,
):
    """
    Generate a concise local LLM insight.

    Returns:
        str | None
    """

    prompt = (
        "Analyze this already-triggered Aave V3 monitoring alert.\n\n"

        "The monitoring system has already calculated the quantitative "
        "fields. Use those values directly.\n\n"

        "Your response must add interpretation rather than merely "
        "repeating the alert.\n\n"

        "ALERT CONTEXT:\n"

        f"{json.dumps(context, indent=2, sort_keys=True, default=str)}\n\n"

        "Identify the strongest quantitative risk or liquidity "
        "implication supported by these numbers. If activity is empty, "
        "do not invent a cause."
    )

    payload = {
        "model": model,
        "system": SYSTEM_PROMPT,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 64,
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
                "Ollama returned an empty insight."
            )
            return None

        log.info(
            "Generated local LLM insight using %s (%d chars).",
            model,
            len(insight),
        )

        return _escape_telegram_markdown(
            insight
        )

    except requests.Timeout as e:
        log.warning(
            "Ollama request timed out after %ds: %s",
            OLLAMA_TIMEOUT_SECONDS,
            e,
        )
        return None

    except requests.RequestException as e:
        log.warning(
            "Local Ollama request failed: %s",
            e,
        )
        return None

    except (ValueError, TypeError) as e:
        log.warning(
            "Could not parse Ollama response: %s",
            e,
        )
        return None

    except Exception as e:
        log.exception(
            "Unexpected local LLM error: %s",
            e,
        )
        return None
