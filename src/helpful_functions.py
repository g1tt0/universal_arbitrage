from web3 import Web3
from web3.exceptions import TransactionNotFound

from binance import Client
from binance.exceptions import BinanceAPIException


import json
import time
from loguru import logger
import os
import dotenv
import threading

import config.constants as constants

dotenv.load_dotenv()


logger.add("logs.log", level="DEBUG")

AVALANCHE_RPC = os.environ.get("AVALANCHE_RPC")


def initialize_web3(network):
    rpc_urls = {
        "avalanche": AVALANCHE_RPC,
    }
    rpc_url = rpc_urls.get(network)
    web3 = Web3(Web3.HTTPProvider(rpc_url))
    return web3


def initialize_amm_objects(w3: Web3, name, network, type):
    # У всех uniswap один и тот же abi. А адрес контракта сохранен в настройках сети, то есть путаницы не будет.
    if "uniswap" in name:
        name = "uniswap"
    if "trader_joe" in name:
        name = "trader_joe"
    # Проверяем имя и тип контракта
    allowable_names = ["trader_joe", "pangolin", "uniswap", "pancake"]
    allowable_types = ["router", "quoter"]
    if name not in allowable_names or type not in allowable_types:
        raise ValueError("Unknown contract type or name.")

    # Получаем название сети. Можно было просто передать network.
    # chain_id = w3.eth.chain_id
    # network = constants.chain_id_map[chain_id]

    # Загружаем контракт
    contract_address = constants.chain[network][f"{name}_{type}"]
    abi = json.load(open(f"abi/{name}_{type}_abi.json"))
    contract = w3.eth.contract(address=contract_address, abi=abi)
    return contract


def initialize_cex_object(cex):
    if cex == "binance":
        return Client(
            os.environ.get("BINANCE_PUBLIC"), os.environ.get("BINANCE_SECRET")
        )


def get_network_list(config: dict) -> list:
    # Создание множества для уникальных сетей. Если сразу создать список, то там будут повторы.
    unique_networks = set()

    # Перебор значений в конфигурации
    for value in config.values():
        # Получение AMM и добавление соответствующей сети в множество
        amm = value["amm"]
        network = constants.amm_to_network[amm]
        unique_networks.add(network)

    # Преобразование множества в список
    return list(unique_networks)


def get_amm_list(config: dict) -> list:
    # Создаем множество для уникальных пар AMM и сети
    unique_pairs = set()

    # Перебор значений в конфигурации
    for value in config.values():
        # Извлекаем значение AMM
        amm = value["amm"]
        # Получаем соответствующую сеть и создаем пару (amm, network)
        network = constants.amm_to_network[amm]
        unique_pairs.add((amm, network))

    # Преобразуем каждую пару в список и возвращаем их в виде списка списков
    return [list(pair) for pair in unique_pairs]


def get_cex_list(config: dict) -> list:
    # Создание множества для уникальных CEX
    unique_cex = set()

    # Перебор всех токенов в конфигурации
    for token_data in config.values():
        # Добавление CEX в множество
        unique_cex.add(token_data["cex"])

    # Преобразование множества в список
    return list(unique_cex)


def get_list_of_network_base_tokens(config):
    # Возвращает список токенов сети по списку сетей

    # Получаем список сетей
    networks = get_network_list(config)

    return [
        constants.network_base_token[network]
        for network in networks
        if network in constants.network_base_token
    ]


def get_list_of_network_base_tokens(config: dict) -> list:
    # Получение списка уникальных сетей
    networks = get_network_list(config)

    # Создание списка основных токенов для каждой сети
    network_base_tokens = [
        constants.network_base_token[network]
        for network in networks
        if network in constants.network_base_token
    ]

    return network_base_tokens


def get_min_difference(token):
    # Получаем минимальный порог для арбитража по токену. Если в файле нет, ставим 1%
    with open("config/min_difference.json") as f:
        data = json.load(f)

    return data.get(token, 0.01)


def find_best_arbitrage_opportunity(cex_prices, dex_prices):
    discrepancies = []

    for token, dex_info in dex_prices.items():
        max_price_difference = 0
        best_cex = None

        for cex, prices in cex_prices.items():
            if token in prices:
                network_base_token = constants.network_base_token.get(
                    dex_info["network"]
                )

                dex_price_in_usdt = dex_info["price"] * cex_prices[cex].get(
                    network_base_token, 0
                )
                cex_price = prices[token]

                # Логгирование
                price_decimals = len(str(cex_price).split(".")[1])
                logger.info(
                    f"{token}. {cex}: {cex_price}. DEX: {round(dex_price_in_usdt, price_decimals)}"
                )

                price_difference = (cex_price - dex_price_in_usdt) / cex_price
                min_difference = get_min_difference(token)

                if (
                    price_difference > max_price_difference
                    and price_difference > min_difference
                ):
                    max_price_difference = price_difference
                    best_cex = cex

        if max_price_difference > 0:
            discrepancies.append((token, max_price_difference, best_cex))

    # Находим токен с максимальной разницей в цене
    if discrepancies:
        token_with_max_discrepancy = max(discrepancies, key=lambda x: x[1])
        token_data = dex_prices[token_with_max_discrepancy[0]]
        token_data["difference"] = token_with_max_discrepancy[1]
        # TODO: можно еще добавить цену с АММ и цену с СЕХ
        return {
            "token_name": token_with_max_discrepancy[0],
            "arbitrage_details": token_data,
        }
    return None


def get_chain_id(chain_name):
    for key, value in constants.chain_id_map.items():
        if value == chain_name:
            return key


def get_network(amm):
    return constants.amm_to_network[amm]


def get_network_base_token(config: dict, token: str):
    # Получаем AMM для заданного токена
    amm = config[token]["amm"]  # обновлено с учетом новой структуры конфига

    # Получаем сеть для данного AMM
    network = constants.amm_to_network[amm]

    # Получаем основной токен для данной сети
    network_base_token = constants.network_base_token[network]

    return network_base_token


def prepare_transaction(w3: Web3, value, wallet_address, network):
    transaction = {
        "from": wallet_address,
        "value": value,
        "nonce": w3.eth.get_transaction_count(wallet_address),
        "chainId": w3.eth.chain_id,
        "gas": constants.default_gas[network],
    }

    # TODO: газ можно ставить вручную для скорости. Либо монитороить параллельно.
    if network in ["polygon"]:  # надо побольше газа ставить
        transaction["maxFeePerGas"] = int(w3.eth.gas_price * 1.2)
        transaction["maxPriorityFeePerGas"] = w3.to_wei(50, "gwei")

    elif network in ["avalanche"]:
        transaction["maxFeePerGas"] = int(w3.eth.gas_price * 1.2)
        transaction["maxPriorityFeePerGas"] = w3.to_wei(2.5, "gwei")
    else:
        transaction["gasPrice"] = int(w3.eth.gas_price * 1.1)

    return transaction


def wait_for_transaction_receipt(w3: Web3, tx_hash, timeout=300):
    start_time = time.time()

    while True:
        try:
            tx_receipt = w3.eth.get_transaction_receipt(tx_hash)

            # Проверяем статус транзакции
            if tx_receipt["status"] == 1:
                return "confirmed"
            else:
                return "failed"
        except TransactionNotFound:
            # Если транзакция не найдена, ждём и повторяем запрос
            if time.time() - start_time > timeout:
                return "timeout"
            time.sleep(1)


def deposit_is_open(token, network):
    with open("data/all_coins_info.json", "r") as file:
        data = json.load(file)
    data = data["data"]

    binance_network = constants.binance_network_map[network]
    for i in data:
        if i["coin"] == token:
            for j in i["networkList"]:
                if j["network"] == binance_network:
                    return j["depositEnable"]


def get_available_networks(token, cex_name):
    # Возвращает список всех доступных сетей для депозита токена на конкретном СЕХ
    with open(f"data/{cex_name}_exchange_info.json", "r") as file:
        data = json.load(file)

    for i in data["data"]:
        if i["currency"] == token:
            chains = i.get("chains", [])
            return [chain["chainId"] for chain in chains]

    # Возвращаем пустой список, если токен не найден
    return []


def get_tokens_for_cex(config: dict, cex_name: str) -> list:
    # Создаем список для хранения токенов, связанных с заданным CEX
    tokens_for_cex = []

    # Перебираем все токены в конфигурации
    for token, details in config.items():
        # Проверяем, соответствует ли CEX заданному
        if details["cex"] == cex_name:
            # Добавляем токен в список
            tokens_for_cex.append(token)

    return tokens_for_cex


def convert_format(data, cex):
    # Трансформирует binance exchange_info к Kucoin (он короче). Чтобы было одинаково.
    if cex == "binance":
        converted_data = []
        for item in data:
            converted_item = {
                "currency": item.get("coin"),
                "name": item.get("coin"),
                "fullName": item.get("name"),
                "precision": 8,  # или другое подходящее значение
                "confirms": None,  # или другое подходящее значение
                "contractAddress": None,  # или другое подходящее значение
                "isMarginEnabled": False,  # или другое подходящее значение
                "isDebitEnabled": False,  # или другое подходящее значение
                "chains": [],
            }

            for network in item.get("networkList", []):
                chain = {
                    "chainName": network.get("name"),
                    "withdrawalMinSize": network.get("withdrawMin"),
                    "withdrawalMinFee": network.get("withdrawFee"),
                    "isWithdrawEnabled": network.get("withdrawEnable"),
                    "isDepositEnabled": network.get("depositEnable"),
                    "confirms": network.get("minConfirm"),
                    "preConfirms": network.get(
                        "unLockConfirm"
                    ),  # Если такое поле отсутствует, установите подходящее значение
                    "contractAddress": network.get("contractAddress"),
                    "chainId": network.get(
                        "network"
                    ).lower(),  # Преобразование к нижнему регистру
                }
                converted_item["chains"].append(chain)

            converted_data.append(converted_item)

    return converted_data


def get_withdrawal_fee(currency, network, cex_name):
    if cex_name == "binance":
        with open("data/binance_exchange_info.json") as file:
            exchange_info = json.load(file)
            for asset in exchange_info["data"]:
                if asset["currency"] == currency:
                    for chain in asset["chains"]:
                        if chain["chainId"] == network:
                            return float(chain["withdrawalMinFee"])
    return None


def get_min_withdraw(currency, network, cex_name):
    if cex_name == "binance":
        with open("data/binance_exchange_info.json") as file:
            exchange_info = json.load(file)
            for asset in exchange_info["data"]:
                if asset["currency"] == currency:
                    for chain in asset["chains"]:
                        if chain["chainId"] == network:
                            return float(chain["withdrawalMinSize"])
    return None


def calculate_slippage(difference):
    slippage = constants.slippage

    if difference > 6:
        return slippage * 3
    elif difference > 4:
        return slippage * 2
    else:
        return slippage
