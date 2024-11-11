# main.py

from amm_arbitrage_lfg import AmmArbitrageLFG

if __name__ == "__main__":
    tokens_to_arbitrage = ["QI", "JOE"]  # Список токенов для арбитража
    amm_arbitrage = AmmArbitrageLFG(tokens_to_arbitrage)
    amm_arbitrage.start(test_mode=False)
