#!/usr/bin/env python3
"""
适配器使用示例

演示如何使用统一的适配器接口编写策略

安全配置说明:
    私钥应通过环境变量配置，而不是硬编码在代码中。

    方法1 - 使用 .env 文件（推荐）:
        1. 复制 .env.example 为 .env
        2. 在 .env 中设置: STANDX_PRIVATE_KEY=你的私钥
        3. 安装 python-dotenv: pip install python-dotenv
        4. 代码会自动加载 .env 文件

    方法2 - 直接设置环境变量:
        Windows: set STANDX_PRIVATE_KEY=你的私钥
        Linux/Mac: export STANDX_PRIVATE_KEY=你的私钥
"""
import sys
import os
from decimal import Decimal

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# 加载 .env 文件（如果存在）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv 未安装，跳过

from adapters import create_adapter, get_available_exchanges


# ==================== 配置区域 ====================
# 私钥通过环境变量 STANDX_PRIVATE_KEY 配置（不要在代码中硬编码！）
# 链配置可通过环境变量 STANDX_CHAIN 配置，默认 bsc
STANDX_CONFIG = {
    "exchange_name": "standx",
    # private_key 从环境变量自动读取，无需在此配置
    # chain 从环境变量自动读取，默认 bsc
}
# ================================================


def example_basic_usage():
    """基本使用示例 - 只需要更改配置即可切换交易所"""
    print("=" * 60)
    print("基本使用示例")
    print("=" * 60)
    
    try:
        # 创建适配器（统一接口，无需关心具体实现）
        adapter = create_adapter(STANDX_CONFIG)
        print(f"创建适配器: {adapter}")
        
        # 连接并认证
        print("\n连接交易所...")
        adapter.connect()
        print("✓ 连接成功")
        
        # 查询余额
        print("\n查询余额...")
        balance = adapter.get_balance()
        print(f"总资产: {balance.total_balance}")
        print(f"可用余额: {balance.available_balance}")
        print(f"账户权益: {balance.equity}")
        print(f"未实现盈亏: {balance.unrealized_pnl}")
        
        # 查询持仓
        print("\n查询持仓...")
        positions = adapter.get_positions()
        if positions:
            for pos in positions:
                print(f"  {pos.symbol}: {pos.size} {pos.side}, 未实现盈亏: {pos.unrealized_pnl}")
        else:
            print("  无持仓")
        
    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()


def example_place_orders():
    """下单示例"""
    print("\n" + "=" * 60)
    print("下单示例")
    print("=" * 60)
    
    try:
        adapter = create_adapter(STANDX_CONFIG)
        adapter.connect()
        
        # 下限价单
        print("\n下限价单...")
        order = adapter.place_limit_order(
            symbol="BTC-USD",
            side="buy",
            quantity=Decimal("0.001"),
            price=Decimal("80000"),
            time_in_force="gtc"
        )
        print(f"✓ 限价单已提交")
        print(f"  订单ID: {order.order_id}")
        print(f"  交易对: {order.symbol}")
        print(f"  方向: {order.side}")
        print(f"  数量: {order.quantity}")
        print(f"  价格: {order.price}")
        
        # 下市价单
        print("\n下市价单...")
        order = adapter.place_market_order(
            symbol="BTC-USD",
            side="sell",
            quantity=Decimal("0.001")
        )
        print(f"✓ 市价单已提交")
        print(f"  订单ID: {order.order_id}")
        
    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()


def example_multi_exchange():
    """多交易所策略示例 - 统一接口操作不同交易所"""
    print("\n" + "=" * 60)
    print("多交易所策略示例")
    print("=" * 60)
    
    # 配置多个交易所（可以使用全局配置或单独配置）
    exchanges_config = [
        STANDX_CONFIG,  # 使用全局配置
        # 未来可以添加更多交易所
        # {
        #     "exchange_name": "nado",
        #     "private_key": "0x你的私钥2",
        #     # ... nado 配置
        # },
    ]
    
    adapters = []
    for config in exchanges_config:
        try:
            adapter = create_adapter(config)
            adapter.connect()
            adapters.append(adapter)
            print(f"✓ {adapter.exchange_name} 连接成功")
        except Exception as e:
            print(f"✗ {config.get('exchange_name')} 连接失败: {e}")
    
    # 使用统一接口操作所有交易所
    for adapter in adapters:
        try:
            print(f"\n处理交易所: {adapter.exchange_name}")
            balance = adapter.get_balance()
            print(f"  可用余额: {balance.available_balance}")
            
            positions = adapter.get_positions()
            print(f"  持仓数量: {len(positions)}")
            
        except Exception as e:
            print(f"  ✗ 错误: {e}")


def example_close_position():
    """平仓示例"""
    print("\n" + "=" * 60)
    print("平仓示例")
    print("=" * 60)
    
    try:
        adapter = create_adapter(STANDX_CONFIG)
        adapter.connect()
        
        symbol = "BTC-USD"
        
        # 查询持仓
        position = adapter.get_position(symbol)
        if position and position.size != Decimal("0"):
            print(f"当前持仓: {position.size} {position.side}")
            
            # 市价平仓
            print("\n市价平仓...")
            order = adapter.close_position(symbol, order_type="market")
            if order:
                print(f"✓ 平仓订单已提交: {order.order_id}")
            else:
                print("无持仓，无需平仓")
        else:
            print("无持仓")
        
    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()


def example_switch_exchange():
    """切换交易所示例 - 展示如何通过配置切换"""
    print("\n" + "=" * 60)
    print("切换交易所示例")
    print("=" * 60)
    
    # 获取可用交易所列表
    available = get_available_exchanges()
    print(f"可用交易所: {', '.join(available)}")
    
    # 不同的交易所配置（可以使用全局配置或单独配置）
    configs = {
        "standx": STANDX_CONFIG,  # 使用全局配置
        # 未来添加更多交易所
        # "nado": {
        #     "exchange_name": "nado",
        #     "private_key": "0x...",
        #     # ... nado 配置
        # },
    }
    
    # 使用相同的代码，只需要更改配置
    for exchange_name, config in configs.items():
        try:
            print(f"\n切换到 {exchange_name}...")
            adapter = create_adapter(config)
            adapter.connect()
            
            balance = adapter.get_balance()
            print(f"✓ {exchange_name} 余额: {balance.available_balance}")
            
        except Exception as e:
            print(f"✗ {exchange_name} 错误: {e}")


if __name__ == "__main__":
    print("适配器使用示例")
    print("注意: 请先配置正确的私钥和参数")
    print()
    
    # 取消注释以运行示例
    example_basic_usage()
    example_place_orders()
    # example_multi_exchange()
    # example_close_position()
    # example_switch_exchange()
