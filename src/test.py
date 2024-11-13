from amm_arbitrage_lfg import AmmArbitrageLFG

if __name__ == "__main__":
    tokens_to_arbitrage = ["QI", "JOE"]  # Список токенов для арбитража
    amm_arbitrage = AmmArbitrageLFG(tokens_to_arbitrage)
    amm_arbitrage.swap_on_lfg(
        1,
        "0x8729438EB15e2C8B576fCc6AeCdA6A148776C0F5",
        "0x2A6EAC052ef51C034326725CEF33f5Aa0c581a99",
        1.0,
    )
