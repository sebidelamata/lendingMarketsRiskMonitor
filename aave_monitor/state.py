"""Per-chain state.json sub-tree access."""


def get_previous_chain_state(state, chain):
    return state.setdefault("chains", {}).setdefault(
        chain,
        {
            "discovered_reserves": {},
            "assets": {},
            "last_discovery": 0,
            "last_metrics_block": None,
        },
    )
