#!/usr/bin/env python3
"""
Proxy Rotator - Main Entry Point

Test and validate available proxies from various sources:
- proxies.txt file
- Environment variables (PROXY_LIST, PROXY_CONFIG_PATH)
- Auto-fetch from free proxy lists

Usage:
    python -m common.proxy                    # Check all available proxies
    python -m common.proxy --fetch            # Auto-fetch and test free proxies
    python -m common.proxy --test-only        # Just validate, don't rotate
    python -m common.proxy --verbose          # Show detailed logging
    python -m common.proxy --max-proxies 10   # Limit to 10 working proxies
"""
import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from common.proxy.rotator import ProxyRotator
from common.proxy.validator import ProxyValidator


def load_proxies_from_file(file_path: str) -> List[str]:
    """
    Load proxies from a text file (one proxy per line).

    Args:
        file_path: Path to proxy list file

    Returns:
        List of proxy URLs
    """
    proxies = []
    path = Path(file_path)

    if not path.exists():
        return proxies

    with open(path, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip empty lines and comments
            if line and not line.startswith('#'):
                proxies.append(line)

    return proxies


def load_proxies_from_env() -> List[str]:
    """
    Load proxies from environment variables.

    Checks:
        - PROXY_LIST: Comma-separated list of proxy URLs
        - PROXY_CONFIG_PATH: Path to proxy config file

    Returns:
        List of proxy URLs
    """
    proxies = []

    # Check PROXY_LIST env var (comma-separated)
    if os.environ.get("PROXY_LIST"):
        proxy_list = os.environ["PROXY_LIST"]
        proxies.extend([p.strip() for p in proxy_list.split(',') if p.strip()])

    # Check PROXY_CONFIG_PATH env var (file path)
    if os.environ.get("PROXY_CONFIG_PATH"):
        config_path = os.environ["PROXY_CONFIG_PATH"]
        proxies.extend(load_proxies_from_file(config_path))

    return proxies


async def test_proxies(
    proxies: List[str],
    max_proxies: int = None,
    verbose: bool = False
) -> List[str]:
    """
    Test and validate a list of proxies with real-time feedback.

    Args:
        proxies: List of proxy URLs to test
        max_proxies: Maximum number of working proxies to return
        verbose: Show detailed logging

    Returns:
        List of working proxy URLs
    """
    print(f"\n🔍 Testing {len(proxies)} proxies...")
    print(f"   Concurrent tests: 20")
    print(f"   Timeout: 10 seconds")
    print(f"   Test URL: https://httpbin.org/ip")

    if max_proxies:
        print(f"   Max proxies: {max_proxies}")

    print("\n⏳ Testing in progress...\n")

    # Test proxies with immediate feedback
    working_proxies = []
    semaphore = asyncio.Semaphore(20)  # Concurrent tests

    async def test_single_proxy(proxy_url: str, index: int):
        """Test a single proxy and show immediate feedback."""
        async with semaphore:
            try:
                import aiohttp
                timeout = aiohttp.ClientTimeout(total=10)

                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(
                        "https://httpbin.org/ip",
                        proxy=proxy_url
                    ) as response:
                        if response.status == 200:
                            # Immediately display success
                            print(f"✅ [{len(working_proxies)+1}] ONLINE: {sanitize_proxy_url(proxy_url)}")
                            return proxy_url
                        else:
                            if verbose:
                                print(f"❌ [{index+1}] Failed (HTTP {response.status}): {sanitize_proxy_url(proxy_url)}")
                            return None
            except asyncio.TimeoutError:
                if verbose:
                    print(f"⏱️  [{index+1}] Timeout: {sanitize_proxy_url(proxy_url)}")
                return None
            except Exception as e:
                if verbose:
                    print(f"❌ [{index+1}] Error: {sanitize_proxy_url(proxy_url)} - {str(e)[:50]}")
                return None

    # Create tasks for all proxies
    tasks = [test_single_proxy(proxy, i) for i, proxy in enumerate(proxies)]

    # Wait for all tests to complete
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Collect working proxies
    for result in results:
        if result and not isinstance(result, Exception):
            working_proxies.append(result)

            # Stop early if we have enough
            if max_proxies and len(working_proxies) >= max_proxies:
                break

    print(f"\n✅ Testing complete: {len(working_proxies)}/{len(proxies)} proxies working\n")

    return working_proxies


async def auto_fetch_and_test(max_proxies: int = 50, verbose: bool = False):
    """
    Auto-fetch proxies from free lists and test them.

    Args:
        max_proxies: Maximum number of working proxies
        verbose: Show detailed logging
    """
    print("\n🌐 Auto-fetching proxies from free proxy lists...")
    print(f"   Target: {max_proxies} working proxies")
    print(f"\n⏳ Fetching and testing proxies... (this may take a few minutes)\n")

    # Configure logging to show immediate feedback from rotator
    if verbose:
        logging.getLogger('common.proxy.validator').setLevel(logging.DEBUG)
    else:
        logging.getLogger('common.proxy.validator').setLevel(logging.INFO)

    rotator = ProxyRotator(
        auto_fetch_proxies=True,
        auto_fetch_max_proxies=max_proxies,
        max_requests_per_minute=60
    )

    # Initialize will auto-fetch and validate
    await rotator.initialize()

    if rotator.is_enabled():
        stats = rotator.get_stats()
        print(f"\n✅ Successfully initialized with {len(stats)} working proxies")
        display_proxy_stats(stats, verbose)
    else:
        print("\n❌ No working proxies found")


def display_proxy_stats(stats: dict, verbose: bool = False):
    """Display proxy statistics in a formatted table."""
    if not stats:
        print("\n📊 No proxies available")
        return

    print("\n📊 Proxy Statistics:")
    print("=" * 80)
    print(f"{'Proxy':<50} {'Status':<10} {'Requests':<10}")
    print("-" * 80)

    for proxy_url, stat in stats.items():
        status = "✅ Healthy" if stat['healthy'] else "❌ Unhealthy"
        requests = stat['total_requests']
        failures = stat['consecutive_failures']

        # Sanitize proxy URL for display (hide passwords)
        display_url = sanitize_proxy_url(proxy_url)

        if verbose:
            print(f"{display_url:<50} {status:<10} {requests:<10} (failures: {failures})")
        else:
            print(f"{display_url:<50} {status:<10} {requests:<10}")

    print("=" * 80)

    # Summary
    healthy_count = sum(1 for s in stats.values() if s['healthy'])
    total_requests = sum(s['total_requests'] for s in stats.values())

    print(f"\n📈 Summary:")
    print(f"   Total proxies: {len(stats)}")
    print(f"   Healthy: {healthy_count}")
    print(f"   Unhealthy: {len(stats) - healthy_count}")
    print(f"   Total requests: {total_requests}")


def sanitize_proxy_url(url: str) -> str:
    """Hide password in proxy URL for display."""
    import re
    # Replace password in URLs like socks5://user:password@host:port
    return re.sub(r'://([^:]+):([^@]+)@', r'://\1:***@', url)


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Test and validate available proxies',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m common.proxy                    # Check all available proxies
  python -m common.proxy --fetch            # Auto-fetch and test free proxies
  python -m common.proxy --test-only        # Just validate, don't use rotator
  python -m common.proxy --verbose          # Show detailed logging
  python -m common.proxy --max-proxies 10   # Limit to 10 working proxies
  python -m common.proxy --file my_proxies.txt  # Test specific file
        """
    )

    parser.add_argument(
        '--fetch',
        action='store_true',
        help='Auto-fetch proxies from free proxy lists'
    )

    parser.add_argument(
        '--test-only',
        action='store_true',
        help='Only test proxies, do not initialize rotator'
    )

    parser.add_argument(
        '--file',
        type=str,
        help='Path to proxy list file (one proxy per line)'
    )

    parser.add_argument(
        '--max-proxies',
        type=int,
        default=None,
        help='Maximum number of working proxies to find'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed logging'
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("=" * 80)
    print("🔄 Proxy Rotator - Availability Checker")
    print("=" * 80)

    # Auto-fetch mode
    if args.fetch:
        await auto_fetch_and_test(
            max_proxies=args.max_proxies or 50,
            verbose=args.verbose
        )
        return

    # Load proxies from various sources
    proxies = []

    # 1. Load from specified file
    if args.file:
        file_proxies = load_proxies_from_file(args.file)
        if file_proxies:
            print(f"\n✅ Loaded {len(file_proxies)} proxies from {args.file}")
            proxies.extend(file_proxies)
        else:
            print(f"\n⚠️  No proxies found in {args.file}")

    # 2. Load from default proxies.txt
    else:
        default_file = Path(__file__).parent / "proxies.txt"
        if default_file.exists():
            file_proxies = load_proxies_from_file(str(default_file))
            if file_proxies:
                print(f"\n✅ Loaded {len(file_proxies)} proxies from {default_file}")
                proxies.extend(file_proxies)

    # 3. Load from environment variables
    env_proxies = load_proxies_from_env()
    if env_proxies:
        print(f"\n✅ Loaded {len(env_proxies)} proxies from environment variables")
        proxies.extend(env_proxies)

    # Remove duplicates
    proxies = list(set(proxies))

    if not proxies:
        print("\n❌ No proxies found!")
        print("\nPlease provide proxies via:")
        print("  1. proxies.txt file in this directory")
        print("  2. PROXY_LIST environment variable (comma-separated)")
        print("  3. PROXY_CONFIG_PATH environment variable (file path)")
        print("  4. --file argument")
        print("  5. --fetch flag to auto-fetch from free lists")
        return

    # Test-only mode
    if args.test_only:
        working_proxies = await test_proxies(
            proxies,
            max_proxies=args.max_proxies,
            verbose=args.verbose
        )

        if working_proxies:
            print(f"\n✅ Found {len(working_proxies)} working proxies:")
            for proxy in working_proxies:
                print(f"   • {sanitize_proxy_url(proxy)}")
        else:
            print("\n❌ No working proxies found")

        return

    # Full rotator mode
    print(f"\n🔄 Initializing proxy rotator with {len(proxies)} proxies...")

    rotator = ProxyRotator(
        proxies=proxies,
        max_requests_per_minute=60,
        max_consecutive_failures=3
    )

    await rotator.initialize()

    if rotator.is_enabled():
        stats = rotator.get_stats()
        healthy_count = rotator.get_healthy_count()

        print(f"\n✅ Rotator initialized: {healthy_count}/{len(stats)} proxies healthy")
        display_proxy_stats(stats, args.verbose)

        # Test rotation
        print("\n🔄 Testing proxy rotation (round-robin):")
        for i in range(min(5, healthy_count)):
            proxy = await rotator.get_proxy(strategy="round_robin")
            if proxy:
                print(f"   [{i+1}] {sanitize_proxy_url(proxy)}")
    else:
        print("\n❌ Failed to initialize rotator - no working proxies")


if __name__ == "__main__":
    asyncio.run(main())
