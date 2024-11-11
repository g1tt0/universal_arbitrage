# amm_arbitrage_lfg.py

import os
import json
import time
import threading
import traceback
from web3 import Web3
from eth_account import Account
from eth_account.signers.local import LocalAccount
from binance.exceptions import BinanceAPIException
from loguru import logger
import dotenv

from helpful_functions import (
    initialize_web3,
    initialize_cex_object,
    find_best_arbitrage_opportunity,
    get_withdrawal_fee,
    convert_format,
)
from telegram import send_message
from config import constants
from lfg_client import LFGclient

dotenv.load_dotenv()

INFINITE = 1000000000
BINANCE_WAITING_DEPOSITS_FILE = "data/binance_waiting_deposits.json"
WITHDRAW_PRECISION = 5
DEFAULT_AVALANCHE_GAS = 1000000

# Глобальная блокировка
file_lock = threading.Lock()


class AmmArbitrageLFG:
    def __init__(self, tokens_to_arbitrage: list) -> None:
        self.running = False

        # Инициализация Web3 для сети Avalanche
        self.network = "avalanche"
        self.w3 = initialize_web3(self.network)

        # Инициализация клиента LFG DEX
        self.lfg_client = LFGclient(self.w3)

        # Инициализация Binance клиента
        self.cex = "binance"
        self.cex_client = initialize_cex_object(self.cex)

        # Получаем ключ к кошельку. Объект содержит address and _private_key
        private_key = os.environ.get("PRIVATE_KEY")
        self.account: LocalAccount = Account.from_key(private_key)
        logger.info(f"Wallet: {self.account.address}")

        # Сохраняем список токенов для арбитража
        self.tokens = tokens_to_arbitrage

        # Проверяем совместимость с Binance
        if not self.check_cex_compatibility():
            logger.error(f"Symbol check failed!")
            time.sleep(INFINITE)
        else:
            logger.info(f"Symbol check is successful.")

    class ThreadWithErrorHandling(threading.Thread):
        # Этот класс нужен, чтобы обрабатывать ошибки и исключения внутри thread
        def run(self):
            try:
                self._target(*self._args, **self._kwargs)
            except Exception as e:
                logger.error(f"Error in CEX selling thread: {str(e)}")
                logger.error(traceback.format_exc())
                send_message(f"Error in CEX selling: {str(e)}")

    def start(self, test_mode=True):
        self.running = True

        # Обновление балансов в отдельном потоке
        update_balances = threading.Thread(target=self.update_balance, args=())
        update_balances.start()
        time.sleep(1)

        # Запуск функции мониторинга депозитов
        self.start_deposit_monitoring()

        while self.running:
            try:
                self.arbitrage(test_mode=test_mode)
            except Exception as e:
                logger.error(e)
                logger.error(traceback.format_exc())
                time.sleep(2)

    def arbitrage(self, test_mode):
        # Сохраняем данные по бирже (депозиты, доступные сети). Обновляется только если предыдущие данные старше 60 секунд (указано в конфиге)
        self.save_exchange_info()

        # Получаем цены CEX
        cex_prices = self.get_cex_prices()

        # Получаем цены AMM
        amm_prices = self.get_amm_prices()

        # Ищем токен для арбитража
        arbitrage_token = find_best_arbitrage_opportunity(cex_prices, amm_prices)

        if not arbitrage_token:
            time.sleep(1)
            return

        # Логгируем и отправляем сообщение в телеграм
        difference = round(arbitrage_token["arbitrage_details"]["difference"] * 100, 1)
        logger.warning(
            f'Token found: {arbitrage_token["token_name"]}. Difference: {difference}%.'
        )
        threading.Thread(
            target=send_message(
                f'Token found: #{arbitrage_token["token_name"]}. Difference: {difference}%.'
            )
        ).start()

        if test_mode:
            time.sleep(10)
            return

        # Покупаем. Возвращает tx_hash в случае успеха и None в случае неудачи.
        tx_hash = self.make_trade(arbitrage_token)
        if not tx_hash:
            return

        # Запускаем в отдельном потоке продажу на CEX (с обработкой исключений)
        sell_on_cex = self.ThreadWithErrorHandling(
            target=self.sell_on_cex, args=(tx_hash, self.cex)
        )
        sell_on_cex.start()

    def save_exchange_info(self):
        """
        Сохраняем данные по бирже, проверяем чтобы не старше 60 секунд.
        """
        try:
            with open(f"data/{self.cex}_exchange_info.json", "r") as file:
                data = json.load(file)
                is_data_old = data["timestamp"] < time.time() - constants.data_is_old
        except FileNotFoundError:
            is_data_old = True

        if is_data_old:
            data = self.cex_client.get_all_coins_info()
            data = convert_format(data, self.cex)
            with open(f"data/{self.cex}_exchange_info.json", "w") as file:
                json.dump({"timestamp": time.time(), "data": data}, file)

    def check_cex_compatibility(self):
        # Проверяем, есть ли токены на Binance
        symbols = [f"{token}USDT" for token in self.tokens]
        available_symbols = self.get_available_symbols()

        missing_symbols = [
            symbol for symbol in symbols if symbol not in available_symbols
        ]
        if missing_symbols:
            logger.error(f"These symbols aren't available: {missing_symbols}")
            return False
        else:
            return True

    def get_available_symbols(self):
        # Получаем список доступных символов на Binance
        data = self.cex_client.get_all_tickers()
        return [item["symbol"] for item in data]

    def get_cex_prices(self):
        # Получаем цены с Binance для нужных токенов
        tickers = self.cex_client.get_orderbook_tickers()
        tickers = {item["symbol"]: item for item in tickers}

        prices = {}
        for token in self.tokens + [constants.network_base_token[self.network]]:
            symbol = f"{token}USDT"
            if symbol in tickers:
                prices[token] = float(tickers[symbol]["bidPrice"])
            else:
                logger.warning(f"Symbol {symbol} not found on Binance.")
        return {self.cex: prices}

    def get_amm_prices(self):
        # Получаем цены с LFG DEX
        amm_prices = {}
        for token in self.tokens:
            price_data = self.get_lfg_price(token)
            amm_prices[token] = price_data
        return amm_prices

    def get_lfg_price(self, token):
        # Получаем цену с LFG DEX
        token_address = constants.chain[self.network][token]
        wavax_address = constants.chain[self.network]["WAVAX"]
        balance = (
            self.get_balance_from_file(self.network)
            - constants.min_balance_for_gas[self.network]
        )
        amount_in = int(
            min(
                constants.chain[self.network]["swap_size"],
                balance,
            )
            * 10**18
        )

        if amount_in <= 0:
            logger.error(f"Not enough balance to perform swap for {token}.")
            return None

        token_path = [wavax_address, token_address]
        quote = self.lfg_client.get_best_path_from_amount_in(token_path, amount_in)

        amount_out = quote["amounts"][-1]
        price = amount_in / amount_out

        return {
            "price": price,
            "network": self.network,
            "data": {
                "amount_in": amount_in,
                "quote": quote,
                "token_address": token_address,
            },
        }

    def make_trade(self, arbitrage_token):
        # Получаем название токена
        token_name = arbitrage_token["token_name"]
        token_data = arbitrage_token["arbitrage_details"]["data"]

        # Получаем адрес токена
        token_address = token_data["token_address"]

        # Получаем количество для свапа
        amount_in = token_data["amount_in"]

        # Получаем recipient
        recipient = os.environ.get("BINANCE_DEPOSIT_ADDRESS")

        # Выполняем свап
        tx_receipt = self.swap_on_lfg(
            amount_in=amount_in,
            token_address=token_address,
            recipient=recipient,
            slippage_percent=constants.slippage * 100,  # Преобразуем в проценты
        )

        if tx_receipt and tx_receipt.status == 1:
            # Обновляем баланс после успешного свапа
            self.manual_update_balance(
                self.network,
                -amount_in / 10**18 + constants.min_balance_for_gas[self.network],
            )
            tx_hash = tx_receipt.transactionHash.hex()
            logger.info(
                f"Swap successful. TX: {constants.explorer[self.network]}/tx/{tx_hash}"
            )
            send_message(
                f"Swap successful. TX: {constants.explorer[self.network]}/tx/{tx_hash}",
                message_type="swap",
            )
            return tx_hash
        else:
            logger.error("Swap failed.")
            return None

    def swap_on_lfg(
        self,
        amount_in: int,
        token_address: str,
        recipient: str,
        slippage_percent: float,
    ):
        # Выполняем свап на LFG DEX
        tx_receipt = self.lfg_client.swap_exact_avax_for_tokens(
            amount_in_wei=amount_in,
            token_address=token_address,
            slippage_percent=slippage_percent,
            recipient=recipient,
        )
        return tx_receipt

    def sell_on_cex(self, tx_hash, cex):
        # Ждем депозита на Binance и продаем токены
        token_name, deposit_amount = self.binance_wait_for_deposit_confirmation(tx_hash)
        if not token_name:
            return

        # Продаем токены
        self.binance_sell_token(token_name, deposit_amount, tx_hash)

    def binance_wait_for_deposit_confirmation(self, tx_hash):
        # Ожидаем подтверждения депозита на Binance
        start_time = time.time()
        logger.info(f"Waiting for binance deposit. TX: {tx_hash}")

        # Добавляем хеш в файл
        self.update_tx_hashes_file(cex_name="binance", tx_hash=tx_hash, add=True)

        filename = "data/binance_deposit_history.json"
        while True:
            if not os.path.exists(filename):
                deposit_history = []
            else:
                with open(filename, "r") as file:
                    deposit_history = json.load(file)

            # Поиск депозита по хешу транзакции
            for deposit in deposit_history:
                if deposit["txId"] == tx_hash and deposit["status"] == 1:
                    token = deposit["coin"]
                    amount = float(deposit["amount"])
                    logger.info(
                        f"Deposit arrived. Token: {token}. Amount: {amount}. TX: {tx_hash}"
                    )
                    self.update_tx_hashes_file(
                        cex_name="binance", tx_hash=tx_hash, add=False
                    )
                    send_message(f"Deposit arrived. TX: #{tx_hash[:8]}.")
                    return token, amount

            # Проверка, не прошел ли час с начала ожидания
            if time.time() - start_time > 3600:
                # Удаляем хеш из файла
                self.update_tx_hashes_file(
                    cex_name="binance", tx_hash=tx_hash, add=False
                )
                return None, None

            # Пауза перед следующим запросом
            time.sleep(2)

    def binance_sell_token(self, token, quantity, tx_hash):
        # Получение знаков после запятой для количества токена
        precision = self.binance_get_asset_precision(f"{token}USDT")
        logger.info(f"Token: {token}. Precision: {precision}")
        if precision is None:
            logger.error("Не удалось получить точность токена.")
            return

        # Форматирование количества с учетом точности
        part_quantity = round(quantity / 3 - 1 / 10**precision, precision)
        logger.info(f"Token: {token}. Quantity: {quantity}. Part: {part_quantity}")

        fills = []
        for _ in range(3):
            try:
                # Создание маркет ордера на продажу
                order = self.cex_client.order_market_sell(
                    symbol=f"{token}USDT", quantity=part_quantity
                )
                fills.extend(order["fills"])
                logger.info(f"The market order sent: {order}")
            except BinanceAPIException as e:
                logger.error(f"Error when sent the market order: {e}")
                return

            # Интервал между ордерами
            time.sleep(1)

        # Расчитываем сколько USDT получили
        total_usdt = round(
            sum(float(fill["price"]) * float(fill["qty"]) for fill in fills) - 0.1, 1
        )
        logger.info(f"Total: {total_usdt} USDT. TX: {tx_hash}")
        send_message(f"Total: {total_usdt} #USDT. TX: #{tx_hash[:8]}")

        # Покупаем AVAX для последующего вывода
        network_base_token = constants.network_base_token[self.network]
        order = self.cex_client.order_market_buy(
            symbol=f"{network_base_token}USDT", quoteOrderQty=total_usdt
        )

        logger.info(f"The market order sent: {order}")

        # Всего куплено AVAX
        total_bought_network_base_token = sum(
            float(fill["qty"]) for fill in order["fills"]
        )

        # Считаем профит и логгируем
        profit = round(
            total_bought_network_base_token
            - constants.chain[self.network]["swap_size"],
            3,
        )

        logger.info(f"Profit: {profit} {network_base_token}. TX: {tx_hash}")
        send_message(f"Profit: {profit} #{network_base_token}. TX: #{tx_hash[:8]}")

        time.sleep(1)
        # Выводим AVAX с Binance
        network_base_token_balance = float(
            self.cex_client.get_asset_balance(network_base_token)["free"]
        )
        if network_base_token_balance > constants.min_withdraw[network_base_token]:
            self.binance_withdraw(
                network_base_token, network_base_token_balance, tx_hash
            )

    def binance_withdraw(self, network_base_token, network_base_token_balance, tx_hash):
        # Получаем название сети на Binance и выводим
        binance_network_name = constants.cex_network_map[self.network]
        withdrawal_fee = get_withdrawal_fee(
            network_base_token, binance_network_name, "binance"
        )
        withdraw_amount = round(
            network_base_token_balance - withdrawal_fee - 1 / 10**WITHDRAW_PRECISION,
            WITHDRAW_PRECISION,
        )
        logger.info(
            f"Binance balance: {network_base_token_balance} {network_base_token}. Withdrawal fee: {withdrawal_fee}. Withdraw amount: {withdraw_amount}. TX: {tx_hash}"
        )
        self.cex_client.withdraw(
            coin=network_base_token,
            network=binance_network_name,
            amount=withdraw_amount,
            address=self.account.address,
        )
        logger.info(
            f"{network_base_token_balance} {network_base_token} withdrawn from Binance. TX: {tx_hash}"
        )
        send_message(
            f"{network_base_token_balance} #{network_base_token} withdrawn from #Binance. TX: #{tx_hash[:8]}"
        )

    def update_balance(self):
        while True:
            try:
                balance = self.w3.eth.get_balance(self.account.address)
                balance_in_eth = round(float(self.w3.from_wei(balance, "ether")), 3)
                self.write_balance_to_file(self.network, balance_in_eth)
            except Exception as e:
                logger.error(f"Error updating balance for {self.network}: {e}")

            time.sleep(600)  # Задержка 10 минут

    @staticmethod
    def write_balance_to_file(network, balance):
        filename = f"data/prices/{constants.network_base_token[network].lower()}_{network}.json"
        with open(filename, "w") as file:
            json.dump({"timestamp": time.time(), "balance": balance}, file)

        GREEN = "\033[32m"
        RESET = "\033[0m"  # Сброс цвета в конце
        logger.info(f"{GREEN}Balance for {network} updated.{RESET}")

    def manual_update_balance(self, network, balance_change):
        try:
            # Чтение текущего баланса из файла
            filename = f"data/prices/{constants.network_base_token[network].lower()}_{network}.json"
            with open(filename, "r") as file:
                data = json.load(file)
                current_balance = data.get("balance", 0)

            # Обновление баланса
            new_balance = current_balance + balance_change

            # Запись обновленного баланса обратно в файл
            self.write_balance_to_file(network, new_balance)
            logger.info(f"Balance updated. New balance: {new_balance}")

        except FileNotFoundError:
            logger.error(
                f"Balance file for {network} not found. Creating a new one with the balance change."
            )
            self.write_balance_to_file(network, balance_change)
        except Exception as e:
            logger.error(f"Error during manual balance update for {network}: {e}")

    def get_balance_from_file(self, network):
        try:
            # Формирование пути к файлу
            filename = f"data/prices/{constants.network_base_token[network].lower()}_{network}.json"

            # Чтение данных из файла
            with open(filename, "r") as file:
                data = json.load(file)
                return data.get("balance", 0)

        except FileNotFoundError:
            logger.error(f"Balance file for {network} not found.")
            return 0
        except Exception as e:
            logger.error(f"Error reading balance for {network}: {e}")
            return 0

    def binance_deposit_monitoring(self):
        while True:
            # Чтение файла с ожидающими депозитами
            waiting_deposits_filename = "data/binance_waiting_deposits.json"
            if not os.path.exists(waiting_deposits_filename):
                # Если файла нет, значит еще не было трейдов никогда.
                waiting_deposits = []
            else:
                with open(waiting_deposits_filename, "r") as file:
                    waiting_deposits = json.load(file)

            # Если в файле есть данные, делаем запрос к API
            if waiting_deposits:
                try:
                    deposit_history = self.cex_client.get_deposit_history()

                    # Запись истории депозитов в файл
                    with open("data/binance_deposit_history.json", "w") as file:
                        json.dump(deposit_history, file)

                except Exception as e:
                    print(f"Ошибка при запросе к API Binance: {e}")

            # Задержка перед следующим проверкой
            time.sleep(5)  # Проверка каждые 5 секунд

    @staticmethod
    def update_tx_hashes_file(cex_name, tx_hash, add=True):
        global file_lock
        filename = f"data/{cex_name}_waiting_deposits.json"

        with file_lock:
            # Проверка существования файла и его создание, если он отсутствует
            if not os.path.exists(filename):
                with open(filename, "w") as file:
                    json.dump([], file)

            # Чтение текущих данных из файла
            with open(filename, "r") as file:
                tx_hashes = json.load(file)

            # Обновление списка хешей
            if add:
                if tx_hash not in tx_hashes:
                    tx_hashes.append(tx_hash)
            else:
                if tx_hash in tx_hashes:
                    tx_hashes.remove(tx_hash)

            # Запись обновленного списка обратно в файл
            with open(filename, "w") as file:
                json.dump(tx_hashes, file)

    def start_deposit_monitoring(self):
        # Создаем новый файл с пустыми ожидающими депозитами
        with open(BINANCE_WAITING_DEPOSITS_FILE, "w") as file:
            json.dump([], file)

        binance_deposit_monitoring = threading.Thread(
            target=self.binance_deposit_monitoring, args=()
        )
        binance_deposit_monitoring.start()

    def binance_get_asset_precision(self, symbol):
        try:
            info = self.cex_client.get_symbol_info(symbol)
            return info["filters"][1]["stepSize"].find("1") - 1
        except BinanceAPIException as e:
            logger.error(f"Ошибка при получении информации о символе: {e}")
            return None
