"""
Connecting to a chain's RPC endpoint, wiring up the Aave Pool contract,
and reading basic ERC20 metadata (symbol/decimals/totalSupply).
"""

from web3 import Web3

from constants import POOL_ABI

from .config import get_chain_rpc, get_chain_address
from .events import ACTIVITY_EVENTS_ABI
from .formatting import chain_label, shorten_address
from .logging_setup import log


TOKEN_METADATA_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
]


def connect_chain(chain):
    name = chain["name"]
    rpc_url = get_chain_rpc(chain)

    log.info(
        "%s: connecting to RPC...",
        chain_label(name),
    )

    w3 = Web3(
        Web3.HTTPProvider(
            rpc_url,
            request_kwargs={"timeout": 30},
        )
    )

    if not w3.is_connected():
        raise ConnectionError(
            f"{name}: could not connect to RPC"
        )

    # eth_chainId is useful for diagnostics, but failure here should
    # not prevent the monitor from starting if the RPC otherwise works.
    try:
        chain_id = w3.eth.chain_id
    except Exception as exc:
        chain_id = None
        log.warning(
            "%s: could not read chain_id: %s",
            chain_label(name),
            exc,
        )

    if chain_id is not None:
        log.info(
            "%s: RPC connected, chain_id=%s",
            chain_label(name),
            chain_id,
        )
    else:
        log.info(
            "%s: RPC connected",
            chain_label(name),
        )

    pool_address = get_chain_address(
        chain,
        "pool_address",
        "aave_pool",
    )

    pool = w3.eth.contract(
        address=Web3.to_checksum_address(pool_address),
        abi=POOL_ABI + ACTIVITY_EVENTS_ABI,
    )

    return {
        "name": name,
        "w3": w3,
        "pool": pool,
        "pool_address": pool_address,
        "chain_id": chain_id,
    }


def get_token_contract(w3, address):
    return w3.eth.contract(
        address=Web3.to_checksum_address(address),
        abi=TOKEN_METADATA_ABI,
    )


def get_asset_metadata(w3, address):
    token = get_token_contract(w3, address)

    try:
        symbol = token.functions.symbol().call()
    except Exception as exc:
        log.warning(
            "Could not read token symbol for %s: %s",
            shorten_address(address),
            exc,
        )
        symbol = shorten_address(address)

    try:
        decimals = token.functions.decimals().call()
    except Exception as exc:
        log.warning(
            "Could not read token decimals for %s: %s",
            shorten_address(address),
            exc,
        )
        decimals = 18

    return symbol, decimals


def get_token_total_supply(w3, address):
    token = get_token_contract(w3, address)

    try:
        return int(
            token.functions.totalSupply().call()
        )
    except Exception:
        log.exception(
            "Could not read totalSupply for token %s",
            shorten_address(address),
        )
        raise
