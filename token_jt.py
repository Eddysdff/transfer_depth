import asyncio
import logging
import os
from typing import Dict, List, Tuple, Optional
import time
from datetime import datetime

import aiohttp
import numpy as np
import pandas as pd
from dotenv import load_dotenv
import smtplib
from email.mime.text import MIMEText
from email.header import Header

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

# 新增配置
EXCEL_FILE = 'token_contracts.xlsx'  # Excel文件名
CHECK_INTERVAL = 300  # 5分钟
PRICE_HISTORY_LENGTH = 5  # 保存5个周期的价格历史
PRICE_INCREASE_THRESHOLD = 0.1  # 10%的价格增长阈值
LIQUIDITY_THRESHOLD = 80  # 流动性阈值

# 邮件配置
SMTP_SERVER = 'smtp.163.com'
SMTP_PORT = 587
SENDER_EMAIL = 'cyberchunk123@163.com'
SENDER_PASSWORD = '100467007Hexi!'
RECIPIENT_EMAIL = '18206723831@1631.com'

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

async def read_token_contracts():
    df = pd.read_excel(EXCEL_FILE)
    return df['contract_address'].tolist()

async def send_email(subject, body):
    message = MIMEText(body, 'plain', 'utf-8')
    message['Subject'] = Header(subject, 'utf-8')
    message['From'] = SENDER_EMAIL
    message['To'] = RECIPIENT_EMAIL

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, message.as_string())
        logger.info("Email sent successfully")
    except Exception as e:
        logger.error(f"Failed to send email: {e}")

async def monitor_token(session: aiohttp.ClientSession, token_address: str):
    price_history = []
    while True:
        order_book = await fetch_order_book_eth(session, token_address)
        if not order_book:
            logger.error(f"Failed to fetch order book for {token_address}")
            await asyncio.sleep(CHECK_INTERVAL)
            continue

        current_price = order_book['price']
        liquidity_score = evaluate_liquidity(order_book)
        
        price_history.append(current_price)
        if len(price_history) > PRICE_HISTORY_LENGTH:
            price_history.pop(0)

        if len(price_history) == PRICE_HISTORY_LENGTH:
            price_increase = (price_history[-1] - price_history[0]) / price_history[0]
            if price_increase > PRICE_INCREASE_THRESHOLD and all(price_history[i] < price_history[i+1] for i in range(len(price_history)-1)):
                if liquidity_score >= LIQUIDITY_THRESHOLD:
                    subject = f"Price Alert for {token_address}"
                    body = f"Token {token_address} has increased by {price_increase:.2%} over the last {PRICE_HISTORY_LENGTH} periods.\n"
                    body += f"Current price: {current_price:.8f} USDC\n"
                    body += f"Liquidity score: {liquidity_score}"
                    await send_email(subject, body)

        # 修改这行日志输出
        logger.info(f"Token: {token_address}, Price: {current_price:.8f} USDC, Liquidity: {liquidity_score:.2f}")
        await asyncio.sleep(CHECK_INTERVAL)

async def main():
    token_addresses = await read_token_contracts()
    async with aiohttp.ClientSession() as session:
        tasks = [monitor_token(session, address) for address in token_addresses]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
