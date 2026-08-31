from pathlib import Path


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "data" / "config.json"

STATE_PATH = BASE_DIR / "data" / "state.json"


# ---------------------------------------------------------------------------
# Aave V3 Ethereum mainnet addresses
# ---------------------------------------------------------------------------

AAVE_PROTOCOL_DATA_PROVIDER = (
    "0x0a16f2FCC0D44FaE41cc54e079281D84A363bECD"
)

AAVE_POOL = (
    "0x87870Bca3F3fD6335C3F4CE8392D69350B4fA4E2"
)


# ---------------------------------------------------------------------------
# Aave Protocol Data Provider ABI
# ---------------------------------------------------------------------------

DATA_PROVIDER_ABI = [
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "asset",
                "type": "address",
            }
        ],
        "name": "getReserveData",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "unbacked",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "accruedToTreasuryScaled",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "totalAToken",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "totalStableDebt",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "totalVariableDebt",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "liquidityRate",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "variableBorrowRate",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "stableBorrowRate",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "averageStableBorrowRate",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "liquidityIndex",
                "type": "uint256",
            },
            {
                "internalType": "uint256",
                "name": "variableBorrowIndex",
                "type": "uint256",
            },
            {
                "internalType": "uint40",
                "name": "lastUpdateTimestamp",
                "type": "uint40",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


# ---------------------------------------------------------------------------
# Aave Pool ABI
#
# getReservesList() returns every reserve currently configured in the Pool.
#
# getReserveData() returns:
#
#   configuration
#   current rates
#   token addresses
#   interest-rate strategy address
# ---------------------------------------------------------------------------

POOL_ABI = [
    {
        "inputs": [],
        "name": "getReservesList",
        "outputs": [
            {
                "internalType": "address[]",
                "name": "",
                "type": "address[]",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "asset",
                "type": "address",
            }
        ],
        "name": "getReserveData",
        "outputs": [
            {
                "internalType": "uint256",
                "name": "configuration",
                "type": "uint256",
            },
            {
                "internalType": "uint128",
                "name": "liquidityIndex",
                "type": "uint128",
            },
            {
                "internalType": "uint128",
                "name": "currentLiquidityRate",
                "type": "uint128",
            },
            {
                "internalType": "uint128",
                "name": "variableBorrowIndex",
                "type": "uint128",
            },
            {
                "internalType": "uint128",
                "name": "currentVariableBorrowRate",
                "type": "uint128",
            },
            {
                "internalType": "uint128",
                "name": "currentStableBorrowRate",
                "type": "uint128",
            },
            {
                "internalType": "uint40",
                "name": "lastUpdateTimestamp",
                "type": "uint40",
            },
            {
                "internalType": "uint16",
                "name": "id",
                "type": "uint16",
            },
            {
                "internalType": "address",
                "name": "aTokenAddress",
                "type": "address",
            },
            {
                "internalType": "address",
                "name": "stableDebtTokenAddress",
                "type": "address",
            },
            {
                "internalType": "address",
                "name": "variableDebtTokenAddress",
                "type": "address",
            },
            {
                "internalType": "address",
                "name": "interestRateStrategyAddress",
                "type": "address",
            },
            {
                "internalType": "uint128",
                "name": "accruedToTreasury",
                "type": "uint128",
            },
            {
                "internalType": "uint128",
                "name": "unbacked",
                "type": "uint128",
            },
            {
                "internalType": "uint128",
                "name": "isolationModeTotalDebt",
                "type": "uint128",
            },
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


# ---------------------------------------------------------------------------
# ERC20 ABI
#
# Used to dynamically obtain symbol and decimals for every reserve.
# ---------------------------------------------------------------------------

ERC20_ABI = [
    {
        "inputs": [],
        "name": "symbol",
        "outputs": [
            {
                "internalType": "string",
                "name": "",
                "type": "string",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [
            {
                "internalType": "uint8",
                "name": "",
                "type": "uint8",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


# ---------------------------------------------------------------------------
# Aave DefaultReserveInterestRateStrategyV2 ABI
#
# getInterestRateData(address reserve) returns:
#
#   optimalUsageRatio
#   baseVariableBorrowRate
#   variableRateSlope1
#   variableRateSlope2
#
# All rate values are returned in ray (1e27).
# ---------------------------------------------------------------------------

INTEREST_RATE_STRATEGY_ABI = [
    {
        "inputs": [
            {
                "internalType": "address",
                "name": "reserve",
                "type": "address",
            }
        ],
        "name": "getInterestRateData",
        "outputs": [
            {
                "components": [
                    {
                        "internalType": "uint256",
                        "name": "optimalUsageRatio",
                        "type": "uint256",
                    },
                    {
                        "internalType": "uint256",
                        "name": "baseVariableBorrowRate",
                        "type": "uint256",
                    },
                    {
                        "internalType": "uint256",
                        "name": "variableRateSlope1",
                        "type": "uint256",
                    },
                    {
                        "internalType": "uint256",
                        "name": "variableRateSlope2",
                        "type": "uint256",
                    },
                ],
                "internalType": (
                    "struct "
                    "IDefaultInterestRateStrategyV2."
                    "InterestRateDataRay"
                ),
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


# ---------------------------------------------------------------------------
# General constants
# ---------------------------------------------------------------------------

RAY = 10**27

ZERO_ADDRESS = (
    "0x0000000000000000000000000000000000000000"
)


# ---------------------------------------------------------------------------
# ReserveConfiguration bit positions
#
# Based directly on Aave V3 ReserveConfiguration.sol.
#
#   bits   0-15    LTV
#   bits  16-31    liquidation threshold
#   bits  32-47    liquidation bonus
#   bits  48-55    reserve decimals
#   bit       56    active
#   bit       57    frozen
#   bit       58    borrowing enabled
#   bit       59    stable borrowing enabled
#   bit       60    paused
#   bit       61    borrowable in isolation
#   bit       62    siloed borrowing
#   bit       63    flashloan enabled
#   bits  64-79    reserve factor
#   bits 80-115    borrow cap
#   bits 116-151  supply cap
#   bits 152-167  liquidation protocol fee
#   bits 168-175  eMode category
#   bits 176-211  unbacked mint cap
#   bits 212-251  debt ceiling
# ---------------------------------------------------------------------------

LTV_START_BIT_POSITION = 0

LIQUIDATION_THRESHOLD_START_BIT_POSITION = 16

LIQUIDATION_BONUS_START_BIT_POSITION = 32

RESERVE_DECIMALS_START_BIT_POSITION = 48

IS_ACTIVE_START_BIT_POSITION = 56

IS_FROZEN_START_BIT_POSITION = 57

BORROWING_ENABLED_START_BIT_POSITION = 58

STABLE_BORROWING_ENABLED_START_BIT_POSITION = 59

IS_PAUSED_START_BIT_POSITION = 60

BORROWABLE_IN_ISOLATION_START_BIT_POSITION = 61

SILOED_BORROWING_START_BIT_POSITION = 62

FLASHLOAN_ENABLED_START_BIT_POSITION = 63

RESERVE_FACTOR_START_BIT_POSITION = 64

BORROW_CAP_START_BIT_POSITION = 80

SUPPLY_CAP_START_BIT_POSITION = 116

LIQUIDATION_PROTOCOL_FEE_START_BIT_POSITION = 152

EMODE_CATEGORY_START_BIT_POSITION = 168

UNBACKED_MINT_CAP_START_BIT_POSITION = 176

DEBT_CEILING_START_BIT_POSITION = 212


# ---------------------------------------------------------------------------
# ReserveConfiguration masks
#
# These are the same masks used by Aave's ReserveConfiguration library.
# ---------------------------------------------------------------------------

LTV_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000
)

LIQUIDATION_THRESHOLD_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000FFFF
)

LIQUIDATION_BONUS_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000FFFFFFFF
)

DECIMALS_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00FFFFFFFFFFFF
)

ACTIVE_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFFFFFFFFFF
)

FROZEN_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFDFFFFFFFFFFFFFF
)

BORROWING_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFBFFFFFFFFFFFFFF
)

STABLE_BORROWING_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF7FFFFFFFFFFFFFF
)

PAUSED_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFFFFFFFFFFF
)

BORROWABLE_IN_ISOLATION_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFDFFFFFFFFFFFFFFF
)

SILOED_BORROWING_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFBFFFFFFFFFFFFFFF
)

FLASHLOAN_ENABLED_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF7FFFFFFFFFFFFFFF
)

RESERVE_FACTOR_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000FFFFFFFFFFFFFFFF
)

BORROW_CAP_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF000000000FFFFFFFFFFFFFFFFFFFF
)

SUPPLY_CAP_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFFFFFF000000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFF
)

LIQUIDATION_PROTOCOL_FEE_MASK = (
    0xFFFFFFFFFFFFFFFFFFFFFF0000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
)

EMODE_CATEGORY_MASK = (
    0xFFFFFFFFFFFFFFFFFFFF00FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
)

UNBACKED_MINT_CAP_MASK = (
    0xFFFFFFFFFFF000000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
)

DEBT_CEILING_MASK = (
    0xF0000000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
)


# ---------------------------------------------------------------------------
# Reserve configuration maximum values
# ---------------------------------------------------------------------------

MAX_VALID_LTV = 65535

MAX_VALID_LIQUIDATION_THRESHOLD = 65535

MAX_VALID_LIQUIDATION_BONUS = 65535

MAX_VALID_DECIMALS = 255

MAX_VALID_RESERVE_FACTOR = 65535

MAX_VALID_BORROW_CAP = 68719476735

MAX_VALID_SUPPLY_CAP = 68719476735

MAX_VALID_LIQUIDATION_PROTOCOL_FEE = 65535

MAX_VALID_EMODE_CATEGORY = 255

MAX_VALID_UNBACKED_MINT_CAP = 68719476735

MAX_VALID_DEBT_CEILING = 1099511627775


# ---------------------------------------------------------------------------
# Other Aave reserve constants
# ---------------------------------------------------------------------------

DEBT_CEILING_DECIMALS = 2

MAX_RESERVES_COUNT = 128
