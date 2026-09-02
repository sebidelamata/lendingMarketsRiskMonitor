"""
Aave Pool activity events:

    Supply
    Withdraw
    Borrow
    Repay
    LiquidationCall

Activity logs are NOT indexed continuously and are NOT stored in
state.json.

eth_getLogs is used ONLY when a supply or utilization alert fires
(see aave_monitor.asset_monitor.check_asset).

The largest relevant events are included in the alert.

LiquidationCall handling is direction-aware.

Borrow decoding follows the standard Aave V3 event layout:

    Topics:
        topic0 = event signature
        topic1 = reserve
        topic2 = onBehalfOf
        topic3 = referralCode

    Data:
        user
        amount
        interestRateMode
        borrowRate

IMPORTANT:
    `user` is NOT indexed in the Aave V3 Borrow event.

Therefore Borrow has 4 topics total, not 5.
"""

from eth_abi import decode as abi_decode
from web3 import Web3

from .formatting import fmt_amount
from .logging_setup import log


DEFAULT_MAX_BLOCK_RANGE = 10
MAX_ACTIVITY_EVENTS = 5


# ---------------------------------------------------------------------------
# Event ABI
# ---------------------------------------------------------------------------

ACTIVITY_EVENTS_ABI = [
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "reserve",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "address",
                "name": "user",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "onBehalfOf",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256",
            },
            {
                "indexed": True,
                "internalType": "uint16",
                "name": "referralCode",
                "type": "uint16",
            },
        ],
        "name": "Supply",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "reserve",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "user",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "to",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256",
            },
        ],
        "name": "Withdraw",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "reserve",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "address",
                "name": "user",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "onBehalfOf",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256",
            },
            {
                "indexed": False,
                "internalType": "uint8",
                "name": "interestRateMode",
                "type": "uint8",
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "borrowRate",
                "type": "uint256",
            },
            {
                "indexed": True,
                "internalType": "uint16",
                "name": "referralCode",
                "type": "uint16",
            },
        ],
        "name": "Borrow",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "reserve",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "user",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "repayer",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "amount",
                "type": "uint256",
            },
            {
                "indexed": False,
                "internalType": "bool",
                "name": "useATokens",
                "type": "bool",
            },
        ],
        "name": "Repay",
        "type": "event",
    },
    {
        "anonymous": False,
        "inputs": [
            {
                "indexed": True,
                "internalType": "address",
                "name": "collateralAsset",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "debtAsset",
                "type": "address",
            },
            {
                "indexed": True,
                "internalType": "address",
                "name": "user",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "debtToCover",
                "type": "uint256",
            },
            {
                "indexed": False,
                "internalType": "uint256",
                "name": "liquidatedCollateralAmount",
                "type": "uint256",
            },
            {
                "indexed": False,
                "internalType": "address",
                "name": "liquidator",
                "type": "address",
            },
            {
                "indexed": False,
                "internalType": "bool",
                "name": "receiveAToken",
                "type": "bool",
            },
        ],
        "name": "LiquidationCall",
        "type": "event",
    },
]


# ---------------------------------------------------------------------------
# Event topics
# ---------------------------------------------------------------------------


def get_activity_event_topics():
    """
    Calculate topic0 hashes from the event signatures.

    IMPORTANT:
    Indexed vs non-indexed parameters do not affect topic0.
    """

    signatures = {
        "Supply": "Supply(address,address,address,uint256,uint16)",
        "Withdraw": "Withdraw(address,address,address,uint256)",
        "Borrow": (
            "Borrow("
            "address,address,address,uint256,uint8,uint256,uint16"
            ")"
        ),
        "Repay": "Repay(address,address,address,uint256,bool)",
        "LiquidationCall": (
            "LiquidationCall("
            "address,address,address,uint256,uint256,address,bool"
            ")"
        ),
    }

    return {
        name: Web3.keccak(text=signature).hex()
        for name, signature in signatures.items()
    }


# ---------------------------------------------------------------------------
# Log fetching
# ---------------------------------------------------------------------------


def get_activity_logs(
    w3,
    pool,
    from_block,
    to_block,
    max_block_range=DEFAULT_MAX_BLOCK_RANGE,
):
    """
    Query Aave Pool activity events using eth_getLogs, chunked to
    max_block_range blocks per request.

    A small range is intentional because some RPC providers impose
    restrictions on eth_getLogs requests.
    """

    if from_block > to_block:
        return []

    if max_block_range <= 0:
        raise ValueError("max_block_range must be greater than zero")

    topic0_list = list(get_activity_event_topics().values())

    logs = []
    current_from = from_block

    while current_from <= to_block:
        chunk_to = min(
            current_from + max_block_range - 1,
            to_block,
        )

        log.info(
            "Fetching Aave activity logs: blocks %d-%d",
            current_from,
            chunk_to,
        )

        try:
            chunk_logs = w3.eth.get_logs(
                {
                    "address": pool.address,
                    "fromBlock": current_from,
                    "toBlock": chunk_to,
                    "topics": [topic0_list],
                }
            )
        except Exception as exc:
            log.warning(
                "Failed to fetch Aave activity logs for blocks "
                "%d-%d: %s",
                current_from,
                chunk_to,
                exc,
            )
            raise

        logs.extend(chunk_logs)
        current_from = chunk_to + 1

    return logs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _topic_to_hex(topic):
    """Convert a Web3 topic value to a hex string."""

    if hasattr(topic, "hex"):
        return topic.hex()

    return str(topic)


def _tx_hash_from_log(raw_log):
    """Extract a transaction hash from a raw Web3 log."""

    tx_hash = raw_log.get("transactionHash")

    if hasattr(tx_hash, "hex"):
        return tx_hash.hex()

    return str(tx_hash)


def _decode_address_topic(topic):
    """
    Decode an indexed address from a 32-byte event topic.
    """

    topic_hex = _topic_to_hex(topic)

    return Web3.to_checksum_address(
        "0x" + topic_hex[-40:]
    )


def _decode_address_data_word(value):
    """
    Decode an address stored as a 32-byte ABI data word.
    """

    if isinstance(value, bytes):
        address_bytes = value[-20:]
    else:
        address_bytes = bytes(value)[-20:]

    return Web3.to_checksum_address(
        "0x" + address_bytes.hex()
    )


def _normalize_log_data(data):
    """
    Convert Web3 log data into bytes.
    """

    if isinstance(data, bytes):
        return data

    if isinstance(data, bytearray):
        return bytes(data)

    if isinstance(data, str):
        return bytes.fromhex(
            data[2:] if data.startswith("0x") else data
        )

    return bytes(data)


# ---------------------------------------------------------------------------
# Borrow decoding
# ---------------------------------------------------------------------------


def _decode_borrow_log(raw_log):
    """
    Decode the standard Aave V3 Borrow event.

    Aave V3 Borrow:

        event Borrow(
            address indexed reserve,
            address user,
            address indexed onBehalfOf,
            uint256 amount,
            InterestRateMode interestRateMode,
            uint256 borrowRate,
            uint16 indexed referralCode
        );

    Therefore:

        topics[0] = event signature
        topics[1] = reserve
        topics[2] = onBehalfOf
        topics[3] = referralCode

    And data contains:

        user
        amount
        interestRateMode
        borrowRate

    This is 4 topics total.

    Returns None if the log cannot be safely decoded.
    """

    topics = raw_log.get("topics", [])

    if len(topics) != 4:
        log.warning(
            "Skipping Borrow with unexpected topic count: "
            "expected 4, got %d "
            "(block=%s, tx=%s)",
            len(topics),
            raw_log.get("blockNumber"),
            _tx_hash_from_log(raw_log),
        )
        return None

    data = _normalize_log_data(
        raw_log.get("data", b"")
    )

    # Four ABI words:
    #
    #   address user
    #   uint256 amount
    #   uint8 interestRateMode
    #   uint256 borrowRate
    #
    expected_length = 32 * 4

    if len(data) != expected_length:
        log.warning(
            "Skipping 4-topic Borrow with unexpected data length: "
            "expected %d bytes, got %d "
            "(block=%s, tx=%s)",
            expected_length,
            len(data),
            raw_log.get("blockNumber"),
            _tx_hash_from_log(raw_log),
        )
        return None

    try:
        (
            user,
            amount,
            interest_rate_mode,
            borrow_rate,
        ) = abi_decode(
            [
                "address",
                "uint256",
                "uint8",
                "uint256",
            ],
            data,
        )
    except Exception as exc:
        log.warning(
            "Skipping undecodable Borrow log: %s "
            "(block=%s, tx=%s)",
            exc,
            raw_log.get("blockNumber"),
            _tx_hash_from_log(raw_log),
        )
        return None

    # Aave V3 currently uses:
    #
    #   1 = Stable
    #   2 = Variable
    #
    # Mode 1 is deprecated in newer Aave versions, but keeping it
    # accepted makes the decoder compatible with older deployments.
    if int(interest_rate_mode) not in (1, 2, 3):
        log.warning(
            "Skipping Borrow with unexpected interestRateMode=%s "
            "(block=%s, tx=%s)",
            interest_rate_mode,
            raw_log.get("blockNumber"),
            _tx_hash_from_log(raw_log),
        )
        return None

    # referralCode is indexed and therefore stored in topic[3].
    #
    # It is uint16, so the upper 30 bytes must be zero.
    referral_topic = _normalize_log_data(
        _topic_to_hex(topics[3])
    )

    if len(referral_topic) != 32:
        log.warning(
            "Skipping Borrow with malformed referralCode topic "
            "(block=%s, tx=%s)",
            raw_log.get("blockNumber"),
            _tx_hash_from_log(raw_log),
        )
        return None

    try:
        referral_code = int.from_bytes(
            referral_topic,
            byteorder="big",
        )
    except Exception as exc:
        log.warning(
            "Skipping Borrow with invalid referralCode topic: %s "
            "(block=%s, tx=%s)",
            exc,
            raw_log.get("blockNumber"),
            _tx_hash_from_log(raw_log),
        )
        return None

    if referral_code > 0xFFFF:
        log.warning(
            "Skipping Borrow with invalid referralCode=%s "
            "(block=%s, tx=%s)",
            referral_code,
            raw_log.get("blockNumber"),
            _tx_hash_from_log(raw_log),
        )
        return None

    return {
        "reserve": _decode_address_topic(topics[1]),
        "user": Web3.to_checksum_address(user),
        "onBehalfOf": _decode_address_topic(topics[2]),
        "amount": int(amount),
        "interestRateMode": int(interest_rate_mode),
        "borrowRate": int(borrow_rate),
        "referralCode": referral_code,
    }


# ---------------------------------------------------------------------------
# Log decoding
# ---------------------------------------------------------------------------


def decode_activity_log(pool, raw_log):
    """
    Decode a single Aave Pool activity event log.

    Standard Aave events are decoded using the Pool ABI.

    Borrow is decoded explicitly because its 4-topic layout must be
    handled correctly:

        topic0 = signature
        topic1 = reserve
        topic2 = onBehalfOf
        topic3 = referralCode

        data = user, amount, interestRateMode, borrowRate

    Unknown or malformed logs return None rather than propagating
    decoding exceptions.
    """

    topics = raw_log.get("topics", [])

    if not topics:
        return None

    topic0 = _topic_to_hex(topics[0])

    event_topics = get_activity_event_topics()

    event_name = None

    for name, event_topic in event_topics.items():
        if topic0.lower() == event_topic.lower():
            event_name = name
            break

    if event_name is None:
        return None

    expected_topics = {
        "Supply": 4,
        "Withdraw": 4,
        "Borrow": 4,
        "Repay": 4,
        "LiquidationCall": 4,
    }

    actual = len(topics)

    # ------------------------------------------------------------------
    # Borrow
    # ------------------------------------------------------------------

    if event_name == "Borrow":
        if actual != 4:
            log.warning(
                "Skipping malformed Borrow log: "
                "expected 4 topics, got %d "
                "(block=%s, tx=%s)",
                actual,
                raw_log.get("blockNumber"),
                _tx_hash_from_log(raw_log),
            )
            return None

        args = _decode_borrow_log(raw_log)

        if args is None:
            return None

        return {
            "event_type": "Borrow",
            "args": args,
            "block_number": int(
                raw_log["blockNumber"]
            ),
            "transaction_hash": _tx_hash_from_log(
                raw_log
            ),
        }

    # ------------------------------------------------------------------
    # Standard event validation
    # ------------------------------------------------------------------

    expected = expected_topics[event_name]

    if actual != expected:
        log.warning(
            "Skipping malformed/unexpected %s log: "
            "expected %d topics, got %d "
            "(block=%s, tx=%s)",
            event_name,
            expected,
            actual,
            raw_log.get("blockNumber"),
            _tx_hash_from_log(raw_log),
        )
        return None

    # ------------------------------------------------------------------
    # Decode using the actual Pool event ABI
    # ------------------------------------------------------------------

    try:
        event = getattr(
            pool.events,
            event_name,
        )()

        decoded = event.process_log(
            raw_log
        )

    except Exception as exc:
        log.warning(
            "Skipping undecodable Aave %s log: %s "
            "(block=%s, tx=%s)",
            event_name,
            exc,
            raw_log.get("blockNumber"),
            _tx_hash_from_log(raw_log),
        )
        return None

    tx_hash = decoded["transactionHash"]

    if hasattr(tx_hash, "hex"):
        tx_hash = tx_hash.hex()

    return {
        "event_type": event_name,
        "args": dict(decoded["args"]),
        "block_number": int(
            decoded["blockNumber"]
        ),
        "transaction_hash": tx_hash,
    }


# ---------------------------------------------------------------------------
# Asset matching
# ---------------------------------------------------------------------------


def event_matches_asset(
    event,
    asset_address,
):
    """
    LiquidationCall can affect a reserve as either collateralAsset or
    debtAsset, so both are checked.

    Other events use the reserve field.
    """

    asset_address = asset_address.lower()

    event_type = event["event_type"]
    args = event["args"]

    if event_type == "LiquidationCall":
        return (
            args["collateralAsset"].lower()
            == asset_address
            or
            args["debtAsset"].lower()
            == asset_address
        )

    return (
        args["reserve"].lower()
        == asset_address
    )


# ---------------------------------------------------------------------------
# Activity record construction
# ---------------------------------------------------------------------------


def build_activity_records_for_event(
    event,
    asset_address,
    decimals,
):
    """
    Convert an Aave event into one or more relevant activity records.

    Supply:
        increases total supply
        generally decreases utilization

    Withdraw:
        decreases total supply
        generally increases utilization

    Borrow:
        increases debt
        increases utilization

    Repay:
        decreases debt
        decreases utilization

    LiquidationCall:
        If monitored reserve == collateralAsset:

            receiveAToken == False:
                collateral leaves the pool,
                aTokens are burned,
                total supply decreases,
                utilization increases.

            receiveAToken == True:
                aTokens are transferred,
                total aToken supply does not change.

        If monitored reserve == debtAsset:

            debtToCover is repaid,
            debt decreases,
            utilization decreases.

    A single liquidation can therefore produce two utilization
    records when the monitored asset is both collateral and debt.
    """

    event_type = event["event_type"]
    args = event["args"]

    asset_address = asset_address.lower()

    records = []

    base = {
        "block_number": event["block_number"],
        "transaction_hash": event["transaction_hash"],
        "event_type": event_type,
    }

    # ------------------------------------------------------------------
    # Supply
    # ------------------------------------------------------------------

    if event_type == "Supply":
        amount_raw = int(args["amount"])

        amount = fmt_amount(
            amount_raw,
            decimals,
        )

        records.append(
            {
                **base,
                "category": "supply",
                "amount_raw": amount_raw,
                "amount": amount,
                "label": "Supply",
                "direction": "increases supply",
                "utilization_direction": (
                    "decreases utilization"
                ),
            }
        )

        records.append(
            {
                **base,
                "category": "utilization",
                "amount_raw": amount_raw,
                "amount": amount,
                "label": "Supply",
                "direction": "decreases utilization",
                "utilization_direction": (
                    "decreases utilization"
                ),
            }
        )

    # ------------------------------------------------------------------
    # Withdraw
    # ------------------------------------------------------------------

    elif event_type == "Withdraw":
        amount_raw = int(args["amount"])

        amount = fmt_amount(
            amount_raw,
            decimals,
        )

        records.append(
            {
                **base,
                "category": "supply",
                "amount_raw": amount_raw,
                "amount": amount,
                "label": "Withdraw",
                "direction": "decreases supply",
                "utilization_direction": (
                    "increases utilization"
                ),
            }
        )

        records.append(
            {
                **base,
                "category": "utilization",
                "amount_raw": amount_raw,
                "amount": amount,
                "label": "Withdraw",
                "direction": "increases utilization",
                "utilization_direction": (
                    "increases utilization"
                ),
            }
        )

    # ------------------------------------------------------------------
    # Borrow
    # ------------------------------------------------------------------

    elif event_type == "Borrow":
        amount_raw = int(args["amount"])

        amount = fmt_amount(
            amount_raw,
            decimals,
        )

        records.append(
            {
                **base,
                "category": "utilization",
                "amount_raw": amount_raw,
                "amount": amount,
                "label": "Borrow",
                "direction": "increases utilization",
                "utilization_direction": (
                    "increases utilization"
                ),
            }
        )

    # ------------------------------------------------------------------
    # Repay
    # ------------------------------------------------------------------

    elif event_type == "Repay":
        amount_raw = int(args["amount"])

        amount = fmt_amount(
            amount_raw,
            decimals,
        )

        records.append(
            {
                **base,
                "category": "utilization",
                "amount_raw": amount_raw,
                "amount": amount,
                "label": "Repay",
                "direction": "decreases utilization",
                "utilization_direction": (
                    "decreases utilization"
                ),
            }
        )

    # ------------------------------------------------------------------
    # LiquidationCall
    # ------------------------------------------------------------------

    elif event_type == "LiquidationCall":
        collateral_asset = (
            args["collateralAsset"].lower()
        )

        debt_asset = (
            args["debtAsset"].lower()
        )

        debt_to_cover_raw = int(
            args["debtToCover"]
        )

        collateral_amount_raw = int(
            args["liquidatedCollateralAmount"]
        )

        receive_a_token = bool(
            args["receiveAToken"]
        )

        # --------------------------------------------------------------
        # Collateral side
        # --------------------------------------------------------------

        if collateral_asset == asset_address:
            collateral_amount = fmt_amount(
                collateral_amount_raw,
                decimals,
            )

            if receive_a_token:
                records.append(
                    {
                        **base,
                        "category": "liquidation_context",
                        "amount_raw": collateral_amount_raw,
                        "amount": collateral_amount,
                        "label": (
                            "Liquidation "
                            "(collateral; aToken transfer)"
                        ),
                        "direction": (
                            "no total supply change"
                        ),
                        "utilization_direction": (
                            "no collateral-side "
                            "utilization change"
                        ),
                    }
                )

            else:
                records.append(
                    {
                        **base,
                        "category": "supply",
                        "amount_raw": collateral_amount_raw,
                        "amount": collateral_amount,
                        "label": (
                            "Liquidation (collateral)"
                        ),
                        "direction": "decreases supply",
                        "utilization_direction": (
                            "increases utilization"
                        ),
                    }
                )

                records.append(
                    {
                        **base,
                        "category": "utilization",
                        "amount_raw": collateral_amount_raw,
                        "amount": collateral_amount,
                        "label": (
                            "Liquidation (collateral)"
                        ),
                        "direction": (
                            "increases utilization"
                        ),
                        "utilization_direction": (
                            "increases utilization"
                        ),
                    }
                )

        # --------------------------------------------------------------
        # Debt side
        # --------------------------------------------------------------

        if debt_asset == asset_address:
            debt_amount = fmt_amount(
                debt_to_cover_raw,
                decimals,
            )

            records.append(
                {
                    **base,
                    "category": "utilization",
                    "amount_raw": debt_to_cover_raw,
                    "amount": debt_amount,
                    "label": (
                        "Liquidation (debt repaid)"
                    ),
                    "direction": (
                        "decreases utilization"
                    ),
                    "utilization_direction": (
                        "decreases utilization"
                    ),
                }
            )

    return records


# ---------------------------------------------------------------------------
# Public activity retrieval
# ---------------------------------------------------------------------------


def get_relevant_activity_records(
    w3,
    pool,
    asset_address,
    decimals,
    from_block,
    to_block,
    max_block_range,
):
    """
    Fetch and decode activity logs for a reserve.

    This function is only invoked after a supply/utilization threshold
    has fired.
    """

    if from_block > to_block:
        return []

    try:
        raw_logs = get_activity_logs(
            w3,
            pool,
            from_block,
            to_block,
            max_block_range=max_block_range,
        )

    except Exception as exc:
        log.error(
            "Failed to fetch Aave activity logs for %s, "
            "blocks %d-%d: %s",
            asset_address,
            from_block,
            to_block,
            exc,
        )
        return []

    records = []

    for raw_log in raw_logs:
        try:
            event = decode_activity_log(
                pool,
                raw_log,
            )

            if event is None:
                continue

            if not event_matches_asset(
                event,
                asset_address,
            ):
                continue

            records.extend(
                build_activity_records_for_event(
                    event,
                    asset_address,
                    decimals,
                )
            )

        except Exception as exc:
            log.warning(
                "Could not process Aave activity log "
                "(block=%s, tx=%s): %s",
                raw_log.get("blockNumber"),
                _tx_hash_from_log(raw_log),
                exc,
            )

    return records


# ---------------------------------------------------------------------------
# Alert ranking
# ---------------------------------------------------------------------------


def top_activity_records(
    records,
    category,
):
    """
    Return the largest MAX_ACTIVITY_EVENTS records for a category.
    """

    relevant = [
        record
        for record in records
        if record.get("category") == category
    ]

    relevant.sort(
        key=lambda record: record.get(
            "amount_raw",
            0,
        ),
        reverse=True,
    )

    return relevant[:MAX_ACTIVITY_EVENTS]
