import asyncio
from typing import Dict, List, Optional
from pycoingecko import CoinGeckoAPI
from structlog import get_logger

from example_publisher.provider import Price, Provider, Symbol
from ..config import CoinGeckoConfig

log = get_logger()

Id = str  # The "API id" of the CoinGecko price, listed on CoinGecko page for each coin.

USD = "usd"

eth_btc_symbol = 'USDB/USD'
eth_btc_id = 'eth/btc'  # 特殊处理的产品标识
ethereum_id = 'ethereum'  # 以太坊的ID，用于获取价格
bitcoin_id = 'bitcoin'


class CoinGecko(Provider):
    def __init__(self, config: CoinGeckoConfig) -> None:
        self._api: CoinGeckoAPI = CoinGeckoAPI(api_key=config.api_key)
        self._prices: Dict[Id, float] = {}
        self._symbol_to_id: Dict[Symbol, Id] = {
            product.symbol: product.coin_gecko_id for product in config.products
        }
        self._config = config

    def upd_products(self, product_symbols: List[Symbol]) -> None:
        new_prices = {}
        process_eth_btc_last = eth_btc_symbol in product_symbols
        for coin_gecko_product in self._config.products:
            if coin_gecko_product.symbol in product_symbols:
                id = coin_gecko_product.coin_gecko_id
                if id != eth_btc_id:
                    new_prices[id] = self._prices.get(id, None)
            else:
                raise ValueError(
                    f"{coin_gecko_product.symbol} not found in available products"  # noqa: E713
                )

        if process_eth_btc_last:
            if ethereum_id in self._prices and bitcoin_id in self._prices:
                ethereum_price = self._prices[ethereum_id]
                bitcoin_price = self._prices[bitcoin_id]

            # 避免除以零
                if bitcoin_price != 0:
                    new_prices[eth_btc_id] = ethereum_price / bitcoin_price
                else:
                    new_prices[eth_btc_id] = 0  # 或者设定一个错误值/标记
                    log.error("Bitcoin price is zero. Skipping 'eth/btc'.")
        else:
            # 如果没有 ethereum 或 bitcoin 的价格，可以选择记录错误或跳过
            log.error("Ethereum or Bitcoin price not found. Skipping 'eth/btc'.")

        self._prices = new_prices

    async def _update_loop(self) -> None:
        while True:
            self._update_prices()
            await asyncio.sleep(self._config.update_interval_secs)

    def _update_prices(self) -> None:

        product_ids = [id_ for id_ in self._prices.keys() if id_ != eth_btc_id]
        result = self._api.get_price(
            ids=product_ids, vs_currencies=USD, precision=18
        )
        for id_, prices in result.items():
            self._prices[id_] = prices[USD]

        if eth_btc_id in self._prices:
            # 确保我们有以太坊和比特币的价格
            if ethereum_id in self._prices and bitcoin_id in self._prices:
                ethereum_price = self._prices[ethereum_id]
                bitcoin_price = self._prices[bitcoin_id]

                if bitcoin_price != 0:
                    self._prices[eth_btc_id] = ethereum_price / bitcoin_price
                else:
                    self._prices[eth_btc_id] = 0  # 或设置为一个错误值/标记
                    log.error("Bitcoin price is zero. Skipping 'eth/btc'.")
            else:
                log.error("Ethereum or Bitcoin price not found. Skipping 'eth/btc'.")

    def _get_price(self, id: Id) -> float:
        return self._prices.get(id, None)

    def latest_price(self, symbol: Symbol) -> Optional[Price]:
        id = self._symbol_to_id.get(symbol)
        if not id:
            return None

        price = self._get_price(id)
        if not price:
            return None
        return Price(price, price * self._config.confidence_ratio_bps / 10000)
