import json
from web3 import Web3
from web3.middleware import geth_poa_middleware
import os
from config import constants


class LFGclient:
    def __init__(self, web3_object):
        self.web3 = web3_object

        # Добавляем Middleware для поддержки PoA сетей
        self.web3.middleware_onion.inject(geth_poa_middleware, layer=0)

        # Load private key from environment and create account
        private_key = os.getenv("PRIVATE_KEY")
        if not private_key:
            raise ValueError("PRIVATE_KEY environment variable not set")
        self.account = self.web3.eth.account.from_key(private_key)

        self.router_address = "0x18556DA13313f3532c54711497A8FedAC273220E"
        self.quoter_address = "0x9A550a522BBaDFB69019b0432800Ed17855A51C3"

        # Load ABIs
        with open(constants.ROUTER_ABI_PATH) as f:
            self.router_abi = json.load(f)
        with open(constants.QUOTER_ABI_PATH) as f:
            self.quoter_abi = json.load(f)

        self.router = self.web3.eth.contract(
            address=self.web3.to_checksum_address(self.router_address),
            abi=self.router_abi,
        )
        self.quoter = self.web3.eth.contract(
            address=self.web3.to_checksum_address(self.quoter_address),
            abi=self.quoter_abi,
        )

    def get_best_path_from_amount_in(self, token_path, amount_in):
        token_path = [self.web3.to_checksum_address(addr) for addr in token_path]
        print(token_path)
        print(amount_in)
        quote = self.quoter.functions.findBestPathFromAmountIn(
            token_path, amount_in
        ).call()

        return {
            "route": quote[0],
            "pairs": quote[1],
            "bin_steps": quote[2],
            "versions": quote[3],
            "amounts": quote[4],
            "virtual_amounts": quote[5],
            "fees": quote[6],
        }

    def swap_exact_avax_for_tokens(
        self,
        amount_in_wei,
        token_address,
        slippage_percent=1.0,
        recipient=None,
        deadline_minutes=20,
    ):
        # Prepare token path (WAVAX -> token)
        wavax_address = constants.chain["avalanche"]["WAVAX"]
        token_path = [
            self.web3.to_checksum_address(wavax_address),
            self.web3.to_checksum_address(token_address),
        ]

        # Get quote for the swap
        quote = self.get_best_path_from_amount_in(token_path, amount_in_wei)

        # Calculate minimum amount out with slippage
        amount_out = quote["amounts"][-1]  # Last amount is the output amount
        min_amount_out = int(amount_out * (100 - slippage_percent) / 100)

        # Calculate deadline
        deadline = self.web3.eth.get_block("latest").timestamp + (deadline_minutes * 60)

        # Prepare path struct
        path = {
            "tokenPath": token_path,
            "pairBinSteps": quote["bin_steps"],
            "versions": quote["versions"],
        }

        # Get current gas price
        gas_price = self.web3.eth.gas_price

        if recipient is None:
            recipient = self.account.address

        # Build transaction
        tx = self.router.functions.swapExactNATIVEForTokens(
            min_amount_out, path, recipient, deadline
        ).build_transaction(
            {
                "from": self.account.address,
                "value": amount_in_wei,
                "gasPrice": gas_price,
                "nonce": self.web3.eth.get_transaction_count(self.account.address),
                "chainId": 43114,  # Avalanche C-Chain ID
            }
        )

        # Estimate gas
        try:
            gas_estimate = self.web3.eth.estimate_gas(tx)
            tx["gas"] = int(gas_estimate * 1.2)  # Add 20% buffer
        except Exception as e:
            print(f"Gas estimation failed: {e}")
            tx["gas"] = 500000  # Fallback gas limit

        # Sign transaction
        signed_tx = self.web3.eth.account.sign_transaction(tx, self.account.key)

        # Send transaction
        tx_hash = self.web3.eth.send_raw_transaction(signed_tx.rawTransaction)

        # Wait for transaction receipt
        tx_receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)

        return tx_receipt
