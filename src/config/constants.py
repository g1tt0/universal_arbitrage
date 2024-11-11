import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTER_ABI_PATH = os.path.join(BASE_DIR, "config", "abis", "lfg22_router.json")
QUOTER_ABI_PATH = os.path.join(BASE_DIR, "config", "abis", "lfg22_quoter.json")

zero_address = "0x0000000000000000000000000000000000000000"
data_is_old = 60
explorer = {
    "avalanche": "https://snowtrace.io",
    "arbitrum": "https://arbiscan.io",
    "optimism": "https://optimistic.etherscan.io",
    "bsc": "https://bscscan.com",
    "polygon": "https://polygonscan.com",
}

chain_id_map = {43114: "avalanche", 42161: "arbitrum", 10: "optimism", 137: "polygon"}

amm_to_network = {
    "pangolin": "avalanche",
    "trader_joe_avalanche": "avalanche",
    "trader_joe_arbitrum": "arbitrum",
    "uniswap_arbitrum": "arbitrum",
    "uniswap_optimism": "optimism",
    "uniswap_polygon": "polygon",
}
network_base_token = {
    "avalanche": "AVAX",
    "arbitrum": "ETH",
    "optimism": "ETH",
    "polygon": "MATIC",
}
min_withdraw = {"AVAX": 1, "ETH": 0.5}

cex_network_map = {
    "avalanche": "avaxc",
    "arbitrum": "arbitrum",
    "optimism": "optimism",
    "polygon": "matic",
}  # Названия сетей на cex для вывода (у кукоина и бинанса одинаковые)

fee = {"ARB": 500, "GMX": 3000, "RNDR": 10000}

default_gas = {"avalanche": 1500000, "arbitrum": 20000000}
min_balance_for_gas = {"avalanche": 0.5, "arbitrum": 0.01}

slippage = 0.005

chain = {
    "avalanche": {
        "network_base_token": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",  # WAVAX
        "WAVAX": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
        "swap_size": 2,
        "USDC": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
        "USDT": "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7",
        "STG": "0x2F6F07CDcf3588944Bf4C42aC74ff24bF56e7590",
        "JOE": "0x6e84a6216eA6dACC71eE8E6b0a5B7322EEbC0fDd",
        "QI": "0x8729438EB15e2C8B576fCc6AeCdA6A148776C0F5",
        "SHRAP": "0xd402298a793948698b9a63311404FBBEe944eAfD",
        "trader_joe_router": "0xb4315e873dBcf96Ffd0acd8EA43f689D8c20fB30",
        "trader_joe_quoter": "0x64b57F4249aA99a812212cee7DAEFEDC40B203cD",
        "BTC.B": "0x152b9d0FdC40C096757F570A51E494bd4b943E50",
        "route": {
            "STG": ["WAVAX", "USDC", "STG"],
            "JOE": ["WAVAX", "JOE"],
            "QI": ["WAVAX", "QI"],
            "SHRAP": ["WAVAX", "USDC", "SHRAP"],
        },
    }
}
