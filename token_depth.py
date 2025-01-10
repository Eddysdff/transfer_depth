import asyncio
import logging
import os
from typing import Dict, List, Tuple, Optional

import aiohttp
import numpy as np
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 从环境变量中读取配置
RPC_URLS = {
    'BTC': os.getenv('BTC_RPC_URL', 'https://api.blockchain.com/v3/exchange/order_book/BTC-USD'),
    'ETH': 'https://api.0x.org/swap/v1/quote'
}
MAX_LIQUIDITY_SCORE = 100
MAX_RISK_SCORE = 50
ORDER_BOOK_DEPTH = 10  # 限制订单簿深度

# 在文件顶部添加以下行
ZEROX_API_KEY = "7a9e4a09-4403-40a8-b0ad-a6bc29a26dee"

# 添加 OpenSea API 的配置
OPENSEA_API_URL = "https://api.opensea.io/api/v1"
OPENSEA_API_KEY = os.getenv("OPENSEA_API_KEY")

async def fetch_order_book_btc(session: aiohttp.ClientSession, rpc_url: str) -> Optional[Dict]:
    try:
        async with session.get(rpc_url) as response:
            if response.status != 200:
                logger.error(f"Error: Received response code {response.status}")
                return None
            return await response.json()
    except aiohttp.ClientError as e:
        logger.error(f"Error fetching BTC order book: {e}")
        return None

async def fetch_order_book_eth(session: aiohttp.ClientSession, token_address: str) -> Optional[Dict]:
    base_token = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"  # USDC 合约地址
    url = f"{RPC_URLS['ETH']}?sellToken={token_address}&buyToken={base_token}&sellAmount=1000000000000000000"
    
    headers = {
        "0x-api-key": ZEROX_API_KEY
    }
    
    try:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                logger.error(f"Error: Received response code {response.status}")
                return None
            data = await response.json()
            logger.debug(f"API Response: {data}")
            
            sell_amount = float(data["sellAmount"]) / 1e18  # 假设代币有 18 位小数
            buy_amount = float(data["buyAmount"]) / 1e6    # USDC 有 6 位小数
            price = buy_amount / sell_amount
            
            return {
                "bids": [("0", str(sell_amount))],
                "asks": [("0", str(buy_amount))],
                "price": price,
                "estimatedPriceImpact": data.get("estimatedPriceImpact", "0")
            }
    except aiohttp.ClientError as e:
        logger.error(f"Error fetching ETH token data from 0x API: {e}")
        return None
    except KeyError as e:
        logger.error(f"Error parsing 0x API response: {e}")
        return None

async def fetch_nft_info(session: aiohttp.ClientSession, contract_address: str, token_id: str) -> Optional[Dict]:
    url = f"{OPENSEA_API_URL}/asset/{contract_address}/{token_id}/"
    headers = {"X-API-KEY": OPENSEA_API_KEY}
    
    try:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                logger.error(f"Error: Received response code {response.status}")
                return None
            data = await response.json()
            return {
                "name": data.get("name"),
                "description": data.get("description"),
                "image_url": data.get("image_url"),
                "owner": data.get("owner", {}).get("address"),
                "last_sale": data.get("last_sale", {}).get("total_price")
            }
    except aiohttp.ClientError as e:
        logger.error(f"Error fetching NFT info: {e}")
        return None

def calculate_depth(order_book: Dict) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if not order_book or 'bids' not in order_book or 'asks' not in order_book:
        logger.error("Error: Invalid order book data")
        return None, None, None
    
    bids = order_book['bids'][:ORDER_BOOK_DEPTH]
    asks = order_book['asks'][:ORDER_BOOK_DEPTH]
    
    bid_depth = sum(float(bid[1]) for bid in bids)
    ask_depth = sum(float(ask[1]) for ask in asks)
    
    bid_ask_spread = float(asks[0][0]) - float(bids[0][0])
    
    return bid_depth, ask_depth, bid_ask_spread

def evaluate_liquidity(order_book: Dict) -> float:
    if 'estimatedPriceImpact' not in order_book:
        logger.warning("Warning: No estimated price impact available, setting liquidity score to 0")
        return 0
    
    price_impact = float(order_book['estimatedPriceImpact'])
    liquidity_score = 1 / (1 + price_impact)  
    return min(liquidity_score * 100, MAX_LIQUIDITY_SCORE)  

async def fetch_price_history(session: aiohttp.ClientSession, token_address: str) -> List[float]:
    url = f"{RPC_URLS['ETH']}?sellToken={token_address}&buyToken=USDC&sellAmount=1000000000000000000"
    headers = {
        "0x-api-key": ZEROX_API_KEY
    }
    try:
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                logger.error(f"Error: Received response code {response.status}")
                return []
            data = await response.json()
            price = float(data["price"])
            return [price]  # 返回一个只包含当前价格的列表
    except aiohttp.ClientError as e:
        logger.error(f"Error fetching price: {e}")
        return []

def assess_risk(price: float) -> float:
    if price < 0.01:
        return MAX_RISK_SCORE  
    elif price < 1:
        return MAX_RISK_SCORE / 2
    else:
        return MAX_RISK_SCORE / 4
    return min(price_history[0] / 100, MAX_RISK_SCORE)

def standardize_score(liquidity_score: float, risk_score: float) -> float:
    standardized_score = (liquidity_score / MAX_LIQUIDITY_SCORE) * 60 - (risk_score / MAX_RISK_SCORE) * 40
    return max(0, min(100, standardized_score))

async def main():
    print("请选择区块链网络：")
    print("1. BTC 主网")
    print("2. ETH 主网")
    print("3. 查询 ETH NFT")
    choice = input("输入您的选择编号: ")

    async with aiohttp.ClientSession() as session:
        if choice == '1':
            rpc_url = RPC_URLS['BTC']
            order_book = await fetch_order_book_btc(session, rpc_url)
        elif choice == '2':
            token_address = input("输入代币的合约地址: ")
            order_book = await fetch_order_book_eth(session, token_address)
        elif choice == '3':
            contract_address = input("输入 NFT 合约地址: ")
            token_id = input("输入 NFT token ID: ")
            nft_info = await fetch_nft_info(session, contract_address, token_id)
            if nft_info:
                print(f"NFT 名称: {nft_info['name']}")
                print(f"描述: {nft_info['description']}")
                print(f"图片 URL: {nft_info['image_url']}")
                print(f"所有者: {nft_info['owner']}")
                print(f"最后售价: {nft_info['last_sale']}")
            else:
                print("无法获取 NFT 信息")
        else:
            logger.error("无效的选择")
            return

        if not order_book:
            logger.error("Error: 获取订单簿数据失败")
            return
        
        liquidity_score = evaluate_liquidity(order_book)
        risk_assessment = assess_risk(order_book['price'])
        
        combined_score = standardize_score(liquidity_score, risk_assessment)
        
        print(f"标准化评分: {combined_score:.2f}")
        print(f"流动性评分: {liquidity_score:.2f}")
        print(f"风险评分: {risk_assessment:.2f}")
        print(f"当前价格: {order_book['price']:.6f} USDC")
        
        if combined_score > 60:
            print("值得购买")
        else:
            print("不建议购买")

if __name__ == "__main__":
    asyncio.run(main())