#!/usr/bin/env python3
"""
StandX Maker Points Strategy

Maximizes maker points with minimal fill risk using 1x leverage.

Strategy:
- Places single limit order at 5 bps from mark price (100% points tier)
- Monitors order position relative to mark price
- Rebalances when order drifts outside target band
- Auto-closes any filled positions immediately
- Tracks and logs estimated points earned

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
import json
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


# Global config
CONFIG = None
ADAPTER = None


class PointsTracker:
    """Track and log estimated maker points"""

    def __init__(self, log_file="maker_points_log.json"):
        self.log_file = os.path.join(current_dir, log_file)
        self.session_start = datetime.now()
        self.total_points = 0.0
        self.total_earning_seconds = 0
        self.orders = []  # List of order tracking data
        self.current_order = None

        # Load existing log if available
        self.load_log()

    def load_log(self):
        """Load existing log file"""
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r') as f:
                    data = json.load(f)
                    self.total_points = data.get('total_points', 0.0)
                    self.orders = data.get('orders', [])
        except Exception:
            pass

    def save_log(self):
        """Save log to file"""
        try:
            data = {
                'last_updated': datetime.now().isoformat(),
                'total_points': round(self.total_points, 4),
                'total_earning_seconds': self.total_earning_seconds,
                'session_start': self.session_start.isoformat(),
                'orders': self.orders[-100:]  # Keep last 100 orders
            }
            with open(self.log_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[WARN] Failed to save log: {e}")

    def start_order(self, order_id, price, quantity, notional, bps):
        """Start tracking a new order"""
        self.current_order = {
            'order_id': str(order_id),
            'start_time': time.time(),
            'price': float(price),
            'quantity': float(quantity),
            'notional': float(notional),
            'start_bps': float(bps),
            'points_earned': 0.0
        }

    def update_order(self, current_bps):
        """Update current order tracking with current bps"""
        if not self.current_order:
            return 0.0

        now = time.time()
        elapsed = now - self.current_order.get('last_update', self.current_order['start_time'])
        self.current_order['last_update'] = now
        self.current_order['current_bps'] = float(current_bps)

        # Calculate points for this period
        # Points formula: notional × multiplier × (time / 86400)
        multiplier = self.get_multiplier(current_bps)
        notional = self.current_order['notional']
        points = notional * multiplier * (elapsed / 86400)

        self.current_order['points_earned'] += points
        self.total_points += points
        self.total_earning_seconds += elapsed

        return points

    def end_order(self, reason="rebalance"):
        """End tracking current order"""
        if not self.current_order:
            return

        self.current_order['end_time'] = time.time()
        self.current_order['duration'] = self.current_order['end_time'] - self.current_order['start_time']
        self.current_order['end_reason'] = reason

        self.orders.append(self.current_order)
        self.save_log()
        self.current_order = None

    def get_multiplier(self, bps):
        """Get points multiplier based on bps distance"""
        if bps <= 0:
            return 0.0
        elif bps <= 10:
            return 1.0      # 100% points
        elif bps <= 30:
            return 0.5      # 50% points
        elif bps <= 100:
            return 0.1      # 10% points
        else:
            return 0.0      # No points

    def get_stats(self):
        """Get current session stats"""
        session_duration = (datetime.now() - self.session_start).total_seconds()
        points_per_hour = (self.total_points / session_duration * 3600) if session_duration > 0 else 0
        points_per_day = points_per_hour * 24

        return {
            'total_points': round(self.total_points, 4),
            'session_duration_min': round(session_duration / 60, 1),
            'earning_time_min': round(self.total_earning_seconds / 60, 1),
            'uptime_percent': round(self.total_earning_seconds / session_duration * 100, 1) if session_duration > 0 else 0,
            'points_per_hour': round(points_per_hour, 2),
            'projected_daily': round(points_per_day, 0)
        }

    def print_stats(self):
        """Print current stats"""
        stats = self.get_stats()
        print(f"\n[POINTS] Total: {stats['total_points']:.4f} | "
              f"Rate: {stats['points_per_hour']:.2f}/hr | "
              f"Projected: ~{stats['projected_daily']:.0f}/day | "
              f"Uptime: {stats['uptime_percent']:.1f}%")


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


def get_existing_order(adapter, symbol, side):
    """
    Get existing open order for the given side

    Returns:
        Order object or None
    """
    try:
        orders = adapter.get_open_orders(symbol=symbol)
        for order in orders:
            if order.status in ["pending", "open", "partially_filled"]:
                order_side = order.side.lower()
                if (side == "buy" and order_side in ["buy", "long"]) or \
                   (side == "sell" and order_side in ["sell", "short"]):
                    return order
        return None
    except Exception as e:
        print(f"Error getting open orders: {e}")
        return None


def close_any_position(adapter, symbol):
    """Close any open position immediately"""
    try:
        position = adapter.get_position(symbol)
        if position and position.size > Decimal("0"):
            print(f"[RISK] Position detected: {position.size} {position.side}")
            print("[RISK] Closing position with market order...")
            adapter.close_position(symbol, order_type="market")
            print("[RISK] Position closed")
            print("[WAIT] Waiting 2 seconds for balance to update...")
            sys.stdout.flush()  # Ensure output is visible
            time.sleep(3)
            print("[WAIT] Wait complete, balance should be updated...")
            return True
    except Exception:
        pass
    return False


def run_strategy_cycle(adapter, config, tracker, dry_run=False):
    """
    Execute one strategy cycle

    Args:
        adapter: Exchange adapter
        config: Strategy configuration
        tracker: PointsTracker instance
        dry_run: If True, don't place real orders

    Returns:
        bool: True if successful, False otherwise
    """
    symbol = config['symbol']
    mp_config = config['maker_points']
    target_bps = mp_config['target_bps']
    max_bps = mp_config.get('max_bps', 10)
    balance_percent = mp_config['balance_percent']
    order_side = mp_config['order_side']
    leverage = mp_config.get('leverage', 1)  # Default to 1x if not specified
    auto_close = mp_config.get('auto_close_position', True)

    # 1. Get current mark price
    try:
        ticker = adapter.get_ticker(symbol)
        mark_price = ticker.get('mark_price') or ticker.get('mid_price') or ticker.get('last_price')
        if not mark_price:
            print("[ERROR] Could not get mark price")
            return False
        mark_price = float(mark_price)
    except Exception as e:
        print(f"[ERROR] Failed to get ticker: {e}")
        return False

    print(f"[INFO] {symbol} Mark Price: ${mark_price:,.2f}")

    # 2. Check and close any positions
    position_closed = False
    if auto_close:
        position_closed = close_any_position(adapter, symbol)

    # 3. Get balance (re-fetch if position was closed to get updated balance)
    try:
        balance = adapter.get_balance()
        available = float(balance.available_balance)
        print(f"[INFO] Available Balance: ${available:,.2f}")
        # If position was just closed, the balance should already be updated after the 2-second wait
    except Exception as e:
        print(f"[ERROR] Failed to get balance: {e}")
        return False

    # 4. Calculate target order
    target_price = calculate_order_price(mark_price, target_bps, order_side)
    target_quantity = calculate_order_quantity(available, mark_price, balance_percent)

    if target_quantity < Decimal("0.0001"):
        print(f"[WARN] Quantity too small: {target_quantity}")
        return False

    target_notional = float(target_price * target_quantity)
    print(f"[INFO] Target: {order_side.upper()} {target_quantity} @ ${target_price} ({target_bps} bps)")
    print(f"[INFO] Notional: ${target_notional:,.2f} = ~{target_notional:.0f} points/day")

    # 5. Check existing order
    existing_order = get_existing_order(adapter, symbol, order_side)

    if existing_order:
        existing_price = float(existing_order.price)
        current_bps = get_current_bps(existing_price, mark_price, order_side)
        min_bps = mp_config.get('min_bps', 1)

        # Calculate points earned since last check
        points_earned = tracker.update_order(current_bps)
        multiplier = tracker.get_multiplier(current_bps)
        tier = "100%" if multiplier == 1.0 else "50%" if multiplier == 0.5 else "10%" if multiplier == 0.1 else "0%"

        print(f"[INFO] Existing order: {existing_order.quantity} @ ${existing_price} ({current_bps:.1f} bps, {tier} tier)")
        print(f"[POINTS] +{points_earned:.6f} this cycle")

        # Check if order is still in good position (between min_bps and max_bps)
        if min_bps <= current_bps <= max_bps:
            print(f"[OK] Order at {current_bps:.1f} bps - within {min_bps}-{max_bps} bps band - keeping order")
            tracker.print_stats()
            return True
        else:
            # Order drifted outside safe band - need to rebalance
            if current_bps < min_bps:
                reason = f"too close to mark ({current_bps:.1f} < {min_bps} bps) - fill risk"
            else:
                reason = f"too far from mark ({current_bps:.1f} > {max_bps} bps) - losing points tier"

            print(f"[REBALANCE] {reason}")
            tracker.end_order(reason=reason)

            if not dry_run:
                try:
                    adapter.cancel_order(order_id=existing_order.order_id)
                    print(f"[CANCELLED] Order {existing_order.order_id}")
                    print("[WAIT] Waiting 2 seconds for balance to update...")
                    sys.stdout.flush()  # Ensure output is visible
                    time.sleep(2)
                    print("[WAIT] Wait complete, fetching updated balance...")
                    # Re-fetch balance after cancel
                    try:
                        balance = adapter.get_balance()
                        available = float(balance.available_balance)
                        print(f"[INFO] Updated Available Balance: ${available:,.2f}")
                        # Recalculate order with updated balance
                        target_quantity = calculate_order_quantity(available, mark_price, balance_percent)
                        target_notional = float(target_price * target_quantity)
                        print(f"[INFO] Updated Target: {order_side.upper()} {target_quantity} @ ${target_price}")
                        print(f"[INFO] Updated Notional: ${target_notional:,.2f}")
                    except Exception as e:
                        print(f"[WARN] Failed to refresh balance: {e}")
                except Exception as e:
                    print(f"[ERROR] Failed to cancel: {e}")
            else:
                print(f"[DRY RUN] Would cancel order {existing_order.order_id}")

    # 6. Place new order
    print(f"[PLACE] {order_side.upper()} {target_quantity} @ ${target_price}")

    if dry_run:
        print("[DRY RUN] Order not placed")
        # Still track for simulation
        tracker.start_order("dry-run", target_price, target_quantity, target_notional, target_bps)
        return True

    try:
        order = adapter.place_order(
            symbol=symbol,
            side=order_side,
            order_type="limit",
            quantity=target_quantity,
            price=target_price,
            time_in_force="gtc",
            reduce_only=False,
            leverage=leverage
        )
        print(f"[SUCCESS] Order placed: {order.order_id}")

        # Start tracking the new order
        tracker.start_order(order.order_id, target_price, target_quantity, target_notional, target_bps)

        return True
    except Exception as e:
        print(f"[ERROR] Failed to place order: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description='StandX Maker Points Strategy')
    parser.add_argument('-c', '--config', type=str, default='config_maker_points.yaml',
                        help='Config file path (default: config_maker_points.yaml)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Simulate without placing orders')
    args = parser.parse_args()

    # Load config
    try:
        print(f"Loading config: {args.config}")
        config = load_config(args.config)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Create adapter
    try:
        adapter = create_adapter(config['exchange'])
        adapter.connect()
        print("Connected to StandX")
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

    # Initialize points tracker
    tracker = PointsTracker()
    print(f"Points log: {tracker.log_file}")
    if tracker.total_points > 0:
        print(f"Loaded previous points: {tracker.total_points:.4f}")

    # Strategy loop
    rebalance_interval = config['maker_points'].get('rebalance_interval', 3)

    print("\n" + "=" * 60)
    print("MAKER POINTS STRATEGY")
    print(f"Symbol: {config['symbol']}")
    print(f"Target: {config['maker_points']['target_bps']} bps (100% points tier)")
    print(f"Safe band: {config['maker_points'].get('min_bps', 1)}-{config['maker_points'].get('max_bps', 9)} bps")
    print(f"Side: {config['maker_points']['order_side']}")
    print(f"Balance %: {config['maker_points']['balance_percent']}%")
    print(f"Rebalance: every {rebalance_interval}s")
    if args.dry_run:
        print("MODE: DRY RUN (no real orders)")
    print("=" * 60 + "\n")

    print("Starting strategy... Press Ctrl+C to stop\n")

    try:
        while True:
            run_strategy_cycle(adapter, config, tracker, dry_run=args.dry_run)
            print(f"\n--- Waiting {rebalance_interval}s ---\n")
            time.sleep(rebalance_interval)
    except KeyboardInterrupt:
        print("\n\nStrategy stopped by user")

        # End current order tracking
        tracker.end_order(reason="user_stopped")
        tracker.save_log()

        # Print final stats
        print("\n" + "=" * 60)
        print("FINAL SESSION STATS")
        stats = tracker.get_stats()
        print(f"Total Points Earned: {stats['total_points']:.4f}")
        print(f"Session Duration: {stats['session_duration_min']:.1f} minutes")
        print(f"Active Earning Time: {stats['earning_time_min']:.1f} minutes")
        print(f"Uptime: {stats['uptime_percent']:.1f}%")
        print(f"Average Rate: {stats['points_per_hour']:.2f} points/hour")
        print(f"Projected Daily: ~{stats['projected_daily']:.0f} points/day")
        print("=" * 60)

        # Cancel all orders on exit
        if not args.dry_run:
            print("\nCancelling open orders...")
            try:
                adapter.cancel_all_orders(symbol=config['symbol'])
                print("Orders cancelled")
            except Exception as e:
                print(f"Failed to cancel orders: {e}")


if __name__ == "__main__":
    main()
