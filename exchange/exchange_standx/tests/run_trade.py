#!/usr/bin/env python3
"""
StandX 交易脚本
查询余额并下单

使用方法:
    1. 通过环境变量设置私钥（推荐）:
       Windows: set STANDX_PRIVATE_KEY=0x你的私钥
       Linux/Mac: export STANDX_PRIVATE_KEY=0x你的私钥
       python run_trade.py

    2. 通过命令行参数（仅用于测试）:
       python run_trade.py --private-key 0x你的私钥 --dry-run
"""
import sys
import os
import argparse

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 加载 .env 文件（如果存在）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from standx_protocol.perps_auth import StandXAuth
from standx_protocol.perp_http import StandXPerpHTTP
from eth_account.messages import encode_defunct
from eth_account import Account
from web3 import Web3

# ==================== 配置区域 ====================
# 私钥从环境变量 STANDX_PRIVATE_KEY 读取（不要硬编码！）

# 交易配置
CHAIN = "bsc"  # 或 "solana"
SYMBOL = "BTC-USD"
SIDE = "buy"  # 或 "sell"
QTY = "0.001"
PRICE = "80000"
# ================================================


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='StandX 交易脚本')
    parser.add_argument('--private-key', type=str, help='钱包私钥（推荐使用环境变量 STANDX_PRIVATE_KEY）')
    parser.add_argument('--dry-run', action='store_true', help='模拟运行，不实际下单')
    parser.add_argument('--symbol', type=str, default=SYMBOL, help=f'交易对 (默认: {SYMBOL})')
    parser.add_argument('--side', type=str, default=SIDE, choices=['buy', 'sell'], help=f'方向 (默认: {SIDE})')
    parser.add_argument('--qty', type=str, default=QTY, help=f'数量 (默认: {QTY})')
    parser.add_argument('--price', type=str, default=PRICE, help=f'价格 (默认: {PRICE})')
    return parser.parse_args()


def get_private_key(args):
    """获取私钥（优先级：命令行 > 环境变量）"""
    private_key = args.private_key or os.environ.get('STANDX_PRIVATE_KEY')
    if not private_key:
        raise ValueError(
            "未找到私钥。请通过以下方式之一提供:\n"
            "  1. 环境变量: export STANDX_PRIVATE_KEY=0x你的私钥\n"
            "  2. 命令行参数: --private-key 0x你的私钥"
        )
    return private_key


def sign_message_with_private_key(private_key: str, message: str) -> str:
    """使用钱包私钥签名消息"""
    # 移除 0x 前缀
    if private_key.startswith('0x'):
        private_key = private_key[2:]
    
    # 创建账户
    account = Account.from_key(private_key)
    
    # 使用 encode_defunct 编码消息（EIP-191 个人签名格式）
    # 这会添加 "\x19Ethereum Signed Message:\n{length}" 前缀
    message_encoded = encode_defunct(text=message)
    
    # 签名消息
    signed = account.sign_message(message_encoded)
    
    # 获取签名的 hex 格式
    # ethers.js 的 signMessage 返回带 0x 前缀的字符串
    signature_hex = signed.signature.hex()
    
    # 确保签名长度正确（应该是 130 个字符，65 字节）
    if len(signature_hex) != 130:
        raise ValueError(f"签名长度不正确: {len(signature_hex)}, 期望 130")
    
    # ethers.js 的 signMessage 返回带 0x 前缀的格式
    # 尝试添加 0x 前缀
    return "0x" + signature_hex


def main():
    """主函数"""
    args = parse_args()

    try:
        print("=" * 60)
        print("StandX 交易脚本")
        if args.dry_run:
            print("[DRY RUN MODE - 不会实际下单]")
        print("=" * 60)

        # 获取私钥
        private_key = get_private_key(args)

        # 1. 初始化
        auth = StandXAuth()
        http_client = StandXPerpHTTP()

        # 2. 获取钱包地址
        pk = private_key
        if pk.startswith('0x'):
            pk = pk[2:]

        account = Web3().eth.account.from_key(pk)
        wallet_address = account.address
        print(f"钱包地址: {wallet_address}")

        # 3. 认证
        print("\n步骤 1: 认证...")
        print(f"  RequestId: {auth.request_id}")

        def sign_message(msg: str) -> str:
            # 调试：打印完整消息内容
            print(f"  签名消息: {msg}")
            signature = sign_message_with_private_key(private_key, msg)
            print(f"  签名 (hex): {signature[:66]}... (长度: {len(signature)})")
            return signature

        login_response = auth.authenticate(
            chain=CHAIN,
            wallet_address=wallet_address,
            sign_message=sign_message
        )

        token = login_response.token
        print(f"✓ 认证成功")

        # 4. 查询余额
        print("\n步骤 2: 查询余额...")
        balance = http_client.query_balance(token)
        print(f"✓ 总资产: {balance.get('balance', '0')}")
        print(f"  可用余额: {balance.get('cross_available', '0')}")
        print(f"  账户权益: {balance.get('equity', '0')}")

        # 5. 下单
        symbol = args.symbol
        side = args.side
        qty = args.qty
        price = args.price

        print(f"\n步骤 3: 下单 {qty} {symbol} @ {price}...")

        if args.dry_run:
            print("✓ [DRY RUN] 跳过实际下单")
        else:
            order = http_client.place_order(
                token=token,
                symbol=symbol,
                side=side,
                order_type="limit",
                qty=qty,
                price=price,
                time_in_force="gtc",
                reduce_only=False,
                auth=auth
            )

            if order.get("code") == 0:
                print(f"✓ 下单成功: {order.get('request_id', 'N/A')}")
            else:
                print(f"✗ 下单失败: {order}")

        print("\n" + "=" * 60)
        print("完成！")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
