#!/usr/bin/env python3
"""
StandX Maker Points Strategy (Two-Sided)

Maximizes maker points with minimal fill risk using both buy and sell orders.

Strategy:
- Places TWO limit orders: buy below mark price, sell above mark price
- Each side uses 50% of the configured balance_percent
- Monitors order positions relative to mark price
- Rebalances when orders drift outside target band
- Auto-closes any filled positions immediately

Usage:
    python maker_points.py                          # Run with default config
    python maker_points.py -c config_maker_points.yaml  # Specify config
    python maker_points.py --dry-run                # Simulate without placing orders
"""
import sys
import os
import yaml
import time
import argparse
from datetime import datetime
from decimal import Decimal, ROUND_DOWN

# Project setup
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from adapters import create_adapter

# Track order start times by side: {"buy": timestamp, "sell": timestamp}
ORDER_START_TIMES = {}


def format_uptime(seconds):
    """Format uptime in human readable format"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m{secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h{mins}m"


def load_config(config_file="config_maker_points.yaml"):
    """Load configuration file"""
    if not os.path.isabs(config_file):
        config_path = os.path.join(current_dir, config_file)
    else:
        config_path = config_file

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def calculate_order_price(mark_price, target_bps, side):
    """
    Calculate order price at target basis points from mark price

    Args:
        mark_price: Current mark price
        target_bps: Target distance in basis points
        side: "buy" or "sell"

    Returns:
        Decimal: Order price
    """
    spread = Decimal(str(mark_price)) * Decimal(str(target_bps)) / Decimal("10000")

    if side == "buy":
        # Buy below mark price
        price = Decimal(str(mark_price)) - spread
    else:
        # Sell above mark price
        price = Decimal(str(mark_price)) + spread

    # Round to 2 decimal places
    return price.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def calculate_order_quantity(balance, mark_price, balance_percent):
    """
    Calculate order quantity based on available balance

    Args:
        balance: Available balance in USDT
        mark_price: Current mark price
        balance_percent: Percentage of balance to use

    Returns:
        Decimal: Order quantity
    """
    usable_balance = Decimal(str(balance)) * Decimal(str(balance_percent)) / Decimal("100")
    quantity = usable_balance / Decimal(str(mark_price))

    # Round down to 4 decimal places (BTC precision)
    return quantity.quantize(Decimal("0.0001"), rounding=ROUND_DOWN)


def get_current_bps(order_price, mark_price, side):
    """
    Calculate current basis points distance from mark price

    Args:
        order_price: Current order price
        mark_price: Current mark price
        side: "buy" or "sell"

    Returns:
        float: Distance in basis points
    """
    if side == "buy":
        distance = Decimal(str(mark_price)) - Decimal(str(order_price))
    else:
        distance = Decimal(str(order_price)) - Decimal(str(mark_price))

    bps = (distance / Decimal(str(mark_price))) * Decimal("10000")
    return float(bps)


def get_existing_orders(adapter, symbol):
    """
    Get existing open orders for both sides

    Returns:
        dict: {"buy": Order or None, "sell": Order or None}
    """
    result = {"buy": None, "sell": None}
    try:
        orders = adapter.get_open_orders(symbol=symbol)
        for order in orders:
            if order.status in ["pending", "open", "partially_filled"]:
                order_side = order.side.lower()
                if order_side in ["buy", "long"]:
                    result["buy"] = order
                elif order_side in ["sell", "short"]:
                    result["sell"] = order
    except Exception as e:
        print(f"Error getting open orders: {e}")
    return result


def run_strategy_cycle(adapter, config, dry_run=False):
    """
    Execute one strategy cycle for both buy and sell sides

    Args:
        adapter: Exchange adapter
        config: Strategy configuration
        dry_run: If True, don't place real orders

    Returns:
        bool: True if successful, False otherwise
    """
    symbol = config['symbol']
    mp_config = config['maker_points']
    target_bps = mp_config['target_bps']
    max_bps = mp_config.get('max_bps', 10)
    min_bps = mp_config.get('min_bps', 1)
    balance_percent = mp_config['balance_percent']
    leverage = mp_config.get('leverage', 1)
    auto_close = mp_config.get('auto_close_position', True)

    # Each side uses half of balance_percent
    per_side_balance_percent = balance_percent / 2
    
    # Action log for UI
    actions_log = []

    # 1. Get current mark price
    try:
        ticker = adapter.get_ticker(symbol)
        mark_price = ticker.get('mark_price') or ticker.get('mid_price') or ticker.get('last_price')
        if not mark_price:
            print("❌ 無法獲取價格...")
            return False
        mark_price = float(mark_price)
    except Exception as e:
        print(f"❌ 獲取價格失敗: {e}")
        return False

    # 2. Check and close any positions
    position_qty = 0
    if auto_close:
        try:
            position = adapter.get_position(symbol)
            if position and position.size > Decimal("0"):
                position_qty = float(position.size)
                actions_log.append(f"🚨 持倉 {position_qty} {position.side} -> 平倉中...")
                adapter.close_position(symbol, order_type="market")
                actions_log.append("✅ 已平倉")
                time.sleep(3)
        except Exception:
            pass

    # 3. Get balance
    try:
        balance = adapter.get_balance()
        available = float(balance.available_balance)
    except Exception as e:
        print(f"❌ 獲取餘額失敗: {e}")
        return False

    # 4. Get existing orders for both sides
    existing_orders = get_existing_orders(adapter, symbol)
    
    # Track which sides need new orders
    sides_to_place = []
    
    # Store order info for UI display
    active_orders = []

    # 5. Process each side
    for side in ["buy", "sell"]:
        target_price = calculate_order_price(mark_price, target_bps, side)
        target_quantity = calculate_order_quantity(available, mark_price, per_side_balance_percent)
        
        if target_quantity < Decimal("0.0001"):
            continue

        target_notional = float(target_price * target_quantity)
        existing_order = existing_orders[side]

        if existing_order:
            existing_price = float(existing_order.price)
            current_bps = get_current_bps(existing_price, mark_price, side)
            
            # Track order start time if not already tracked
            if side not in ORDER_START_TIMES:
                ORDER_START_TIMES[side] = time.time()
            
            uptime = time.time() - ORDER_START_TIMES[side]

            # Store for UI display
            active_orders.append({
                'side': side,
                'price': existing_price,
                'quantity': float(existing_order.quantity),
                'bps': current_bps,
                'uptime': uptime
            })

            # Check if order is still in good position
            if min_bps <= current_bps <= max_bps:
                continue
            else:
                # Order drifted outside safe band - need to rebalance
                if current_bps < min_bps:
                    reason = f"太近 {current_bps:.1f} < {min_bps} bps"
                else:
                    reason = f"太遠 {current_bps:.1f} > {max_bps} bps"

                actions_log.append(f"⚠️ {side.upper()} 偏離 {current_bps:.1f}bps -> 撤單 ({reason})")
                
                # Reset uptime tracking for this side
                if side in ORDER_START_TIMES:
                    del ORDER_START_TIMES[side]

                if not dry_run:
                    try:
                        adapter.cancel_order(order_id=existing_order.order_id)
                    except Exception:
                        continue
                
                # Remove from active orders since we're cancelling
                active_orders = [o for o in active_orders if o['side'] != side]

        # Add to list of sides needing new orders
        sides_to_place.append({
            'side': side,
            'price': target_price,
            'quantity': target_quantity,
            'notional': target_notional
        })

    # 6. Wait for balance update if we cancelled any orders
    if sides_to_place and not dry_run:
        time.sleep(2)
        
        # Re-fetch balance
        try:
            balance = adapter.get_balance()
            available = float(balance.available_balance)
            
            # Recalculate quantities with updated balance
            for order_info in sides_to_place:
                order_info['quantity'] = calculate_order_quantity(available, mark_price, per_side_balance_percent)
                order_info['notional'] = float(order_info['price'] * order_info['quantity'])
        except Exception:
            pass

    # 7. Place new orders
    for order_info in sides_to_place:
        side = order_info['side']
        target_price = order_info['price']
        target_quantity = order_info['quantity']
        
        if target_quantity < Decimal("0.0001"):
            continue

        if dry_run:
            actions_log.append(f"🔸 [DRY] 掛{side.upper()}單 @ {float(target_price):.2f}")
            ORDER_START_TIMES[side] = time.time()
            active_orders.append({
                'side': side,
                'price': float(target_price),
                'quantity': float(target_quantity),
                'bps': target_bps,
                'uptime': 0
            })
            continue

        try:
            order = adapter.place_order(
                symbol=symbol,
                side=side,
                order_type="limit",
                quantity=target_quantity,
                price=target_price,
                time_in_force="gtc",
                reduce_only=False,
                leverage=leverage
            )
            actions_log.append(f"✅ 掛{side.upper()}單 @ {float(target_price):.2f}")
            ORDER_START_TIMES[side] = time.time()
            active_orders.append({
                'side': side,
                'price': float(target_price),
                'quantity': float(target_quantity),
                'bps': target_bps,
                'uptime': 0
            })
        except Exception as e:
            actions_log.append(f"❌ {side.upper()}單失敗: {e}")

    # 8. Display UI (like main.py)
    os.system('clear' if os.name != 'nt' else 'cls')
    
    print(f"=== 🛡️ StandX Maker Points 挖礦策略 (雙邊) ===")
    print(f"⏰ 時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"💰 錢包餘額: ${available:,.2f} | 掛單比例: {balance_percent}% ({per_side_balance_percent:.1f}%/邊)")
    print(f"📊 即時價格: ${mark_price:,.2f}")
    print(f"🎯 目標: {target_bps} bps | 安全帶: {min_bps}-{max_bps} bps")
    if position_qty == 0:
        print(f"🛡️ 持倉: (0) 非常安全")
    else:
        print(f"🚨 持倉: {position_qty} (平倉中...)")
    print("-" * 45)
    
    # Display orders
    if not active_orders:
        print(" (無掛單，正在補單...)")
    else:
        for o in active_orders:
            side_emoji = "🟢" if o['side'] == 'buy' else "🔴"
            uptime_str = format_uptime(o.get('uptime', 0))
            print(f" {side_emoji} [{o['side'].upper()}] ${o['price']:,.2f} x {o['quantity']:.4f} (距 {o['bps']:.1f}bps) ⏱️  {uptime_str}")
    
    print("-" * 45)
    
    if dry_run:
        print("🔸 模式: DRY RUN (不實際下單)")
    
    for log in actions_log:
        print(log)

    return True


def main():
    parser = argparse.ArgumentParser(description='StandX Maker Points Strategy')
    parser.add_argument('-c', '--config', type=str, default='config_maker_points.yaml',
                        help='Config file path (default: config_maker_points.yaml)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Simulate without placing orders')
    args = parser.parse_args()

    # Load config
    try:
        print(f"📂 載入設定: {args.config}")
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"❌ 錯誤: {e}")
        sys.exit(1)

    # Create adapter
    try:
        adapter = create_adapter(config['exchange'])
        adapter.connect()
        print("✅ 已連接 StandX")
    except Exception as e:
        print(f"❌ 連接失敗: {e}")
        sys.exit(1)

    # Strategy loop
    rebalance_interval = config['maker_points'].get('rebalance_interval', 3)

    print("🚀 啟動 Maker Points 挖礦策略...")
    print("按 Ctrl+C 停止\n")
    time.sleep(2)

    try:
        while True:
            run_strategy_cycle(adapter, config, dry_run=args.dry_run)
            time.sleep(rebalance_interval)
    except KeyboardInterrupt:
        print("\n\n🛑 策略已停止")

        # Cancel all orders on exit
        if not args.dry_run:
            print("\n🔄 撤銷所有掛單...")
            try:
                adapter.cancel_all_orders(symbol=config['symbol'])
                print("✅ 已撤銷")
            except Exception as e:
                print(f"❌ 撤單失敗: {e}")


if __name__ == "__main__":
    main()
