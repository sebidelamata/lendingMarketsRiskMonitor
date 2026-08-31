"""Reading raw reserve data from the Aave Pool contract."""

from web3 import Web3


def get_pool_reserve_data(pool, asset_address):
    data = pool.functions.getReserveData(asset_address).call()

    return {
        "configuration": int(data[0]),
        "liquidity_index": int(data[1]),
        "current_liquidity_rate": int(data[2]),
        "variable_borrow_index": int(data[3]),
        "current_variable_borrow_rate": int(data[4]),
        "current_stable_borrow_rate": int(data[5]),
        "last_update_timestamp": int(data[6]),
        "id": int(data[7]),
        "a_token_address": Web3.to_checksum_address(data[8]),
        "stable_debt_token_address": Web3.to_checksum_address(data[9]),
        "variable_debt_token_address": Web3.to_checksum_address(data[10]),
        "interest_rate_strategy_address": Web3.to_checksum_address(data[11]),
        "accrued_to_treasury": int(data[12]),
        "unbacked": int(data[13]),
        "isolation_mode_total_debt": int(data[14]),
    }
