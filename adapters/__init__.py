"""
Exchange Adapters Package

统一入口：通过配置创建适配器，无需关心具体实现

安全配置（推荐）:
    私钥应通过环境变量配置，而不是硬编码在代码中:

    1. 复制 .env.example 为 .env
    2. 设置环境变量: STANDX_PRIVATE_KEY=你的私钥
    3. 安装 python-dotenv（可选）: pip install python-dotenv

使用示例:
    import os
    from dotenv import load_dotenv  # 可选
    from adapters import create_adapter

    load_dotenv()  # 加载 .env 文件（可选）

    # 私钥从环境变量自动读取，无需在配置中指定
    config = {
        "exchange_name": "standx",  # 或 "nado", "grvt" 等
        "chain": "bsc"  # 可选，也可通过 STANDX_CHAIN 环境变量配置
    }

    adapter = create_adapter(config)
    adapter.connect()
    balance = adapter.get_balance()

环境变量:
    - STANDX_PRIVATE_KEY: StandX 交易所私钥
    - STANDX_CHAIN: StandX 链配置（默认 bsc）
"""
from adapters.base_adapter import (
    BasePerpAdapter,
    OrderSide,
    OrderType,
    TimeInForce,
    OrderStatus,
    Position,
    Balance,
    Order,
)
from adapters.factory import (
    create_adapter,
    register_adapter,
    get_available_exchanges,
)

__all__ = [
    # 基类和接口
    "BasePerpAdapter",
    "create_adapter",
    
    # 数据模型
    "Position",
    "Balance",
    "Order",
    
    # 枚举
    "OrderSide",
    "OrderType",
    "TimeInForce",
    "OrderStatus",
    
    # 工厂函数
    "register_adapter",
    "get_available_exchanges",
]
