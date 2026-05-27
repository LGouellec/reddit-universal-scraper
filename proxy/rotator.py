"""
Proxy rotation system for distributing requests across multiple proxies.

Helps avoid rate limiting by masking total request volume across different IPs.
"""
import asyncio
import logging
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .fetcher import ProxyFetcher
from .validator import ProxyValidator

logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    """Configuration for a single proxy."""
    url: str  # Format: socks5://host:port or socks5://user:pass@host:port (recommended)
              #         http://host:port or http://user:pass@host:port (may be blocked by Yahoo)
    max_requests_per_minute: int = 60
    healthy: bool = True
    total_requests: int = 0
    last_used: float = 0.0
    consecutive_failures: int = 0


class ProxyRotator:
    """
    Manages a pool of proxies with round-robin rotation and health checking.

    Features:
    - Round-robin rotation across healthy proxies
    - Per-proxy rate limiting (max requests per minute)
    - Automatic health checking and failover
    - Dead proxy detection (consecutive failures)
    - Load balancing based on least recently used
    - Supports HTTP and SOCKS5 proxies (SOCKS5 recommended for Yahoo Finance)

    Important:
        Yahoo Finance detects and blocks local HTTP proxies. Use SOCKS5 proxies instead.
        Format: socks5://host:port or socks5://user:pass@host:port

    Environment Variables:
        PROXY_LIST: Comma-separated list of proxy URLs
        PROXY_CONFIG_PATH: Path to proxy config file (one proxy per line)
        PROXY_AUTO_FETCH: Enable automatic proxy fetching from free lists (default: false)
        PROXY_AUTO_FETCH_MAX: Maximum validated proxies when auto-fetching (default: 50)
        PROXY_MAX_RPM: Max requests per minute per proxy (default: 60)
        PROXY_MAX_FAILURES: Consecutive failures before marking unhealthy (default: 3)
    """

    def __init__(
        self,
        proxies: Optional[List[str]] = None,
        max_requests_per_minute: int = 60,
        max_consecutive_failures: int = 3,
        enable_health_check: Optional[bool] = None,
        auto_fetch_proxies: Optional[bool] = None,
        auto_fetch_max_proxies: int = 50,
    ):
        """
        Initialize proxy rotator.

        Args:
            proxies: List of proxy URLs (socks5://host:port or http://host:port)
                     SOCKS5 recommended - Yahoo Finance blocks HTTP proxies
            max_requests_per_minute: Max requests per proxy per minute
            max_consecutive_failures: Failures before marking proxy as unhealthy
            enable_health_check: Enable automatic health checking
            auto_fetch_proxies: Automatically fetch and validate proxies from free lists
            auto_fetch_max_proxies: Maximum number of validated proxies when auto-fetching
        """
        self._proxies: Dict[str, ProxyConfig] = {}
        self._max_consecutive_failures = max_consecutive_failures
        self._enable_health_check = enable_health_check
        self._current_index = 0
        self._lock = asyncio.Lock()
        self._auto_fetch = auto_fetch_proxies or os.environ.get("PROXY_AUTO_FETCH", "false").lower() == "true"
        self._auto_fetch_max = int(os.environ.get("PROXY_AUTO_FETCH_MAX", auto_fetch_max_proxies))
        self._initialized = False
        self._cache_timestamp = 0.0  # Track when proxies were last fetched/refreshed
        self._cache_ttl = 6 * 3600  # 6 hours in seconds

        # Store params for async initialization
        self._provided_proxies = proxies
        self._max_rpm = int(os.environ.get("PROXY_MAX_RPM", max_requests_per_minute))

    async def initialize(self) -> None:
        """
        Async initialization of proxy rotator.

        Must be called before using the rotator if auto_fetch_proxies is enabled.
        Safe to call multiple times (idempotent).
        """
        if self._initialized:
            return

        # Load proxies from config or environment
        proxy_list = self._provided_proxies or self._load_proxies_from_env()

        # Auto-fetch proxies if enabled and no manual proxies provided
        if self._auto_fetch and not proxy_list:
            logger.info("🔄 Auto-fetching proxies from free proxy list...")
            proxy_list = await self._fetch_and_validate_proxies()

        if not proxy_list:
            logger.warning("⚠️  No proxies configured - ProxyRotator disabled")
            self._initialized = True
            return

        # Initialize proxy configs
        for proxy_url in proxy_list:
            self._proxies[proxy_url] = ProxyConfig(
                url=proxy_url,
                max_requests_per_minute=self._max_rpm,
            )

        logger.info(f"✅ ProxyRotator initialized with {len(self._proxies)} proxies")
        logger.info(f"   Max requests per proxy: {self._max_rpm}/min")
        logger.info(f"   Health check: {'Enabled' if self._enable_health_check else 'Disabled'}")
        logger.info(f"   Auto-fetch: {'Enabled' if self._auto_fetch else 'Disabled'}")

        # Set cache timestamp
        self._cache_timestamp = time.time()

        self._initialized = True

    async def _fetch_and_validate_proxies(self) -> List[str]:
        """
        Fetch proxies from free list and validate them.

        Returns:
            List of validated proxy URLs
        """
        try:
            # Fetch proxies from remote source
            fetcher = ProxyFetcher()
            proxies = await fetcher.fetch_proxies()

            if not proxies:
                logger.warning("⚠️  No proxies fetched from remote source")
                return []

            logger.info(f"📥 Fetched {len(proxies)} proxies, starting validation...")

            # Validate proxies
            validator = ProxyValidator()
            validated_proxies = await validator.validate_proxies(
                proxies, max_proxies=self._auto_fetch_max
            )

            if not validated_proxies:
                logger.warning("⚠️  No working proxies found after validation")
            else:
                logger.info(
                    f"✅ Validated {len(validated_proxies)} working proxies "
                    f"out of {len(proxies)} total"
                )

            return validated_proxies

        except Exception as e:
            logger.error(f"❌ Failed to fetch and validate proxies: {e}")
            return []

    def _load_proxies_from_env(self) -> List[str]:
        """
        Load proxy list from environment variables.

        Returns:
            List of proxy URLs
        """
        proxies = []

        # Option 1: PROXY_LIST environment variable (comma-separated)
        proxy_list_env = os.environ.get("PROXY_LIST")
        if proxy_list_env:
            proxies = [p.strip() for p in proxy_list_env.split(",") if p.strip()]
            logger.info(f"📋 Loaded {len(proxies)} proxies from PROXY_LIST env var")
            return proxies

        # Option 2: PROXY_CONFIG_PATH (file with one proxy per line)
        config_path = os.environ.get("PROXY_CONFIG_PATH")
        if config_path and os.path.exists(config_path):
            with open(config_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        proxies.append(line)
            logger.info(f"📋 Loaded {len(proxies)} proxies from {config_path}")
            return proxies

        return proxies

    async def get_proxy(self, strategy: str = "round_robin") -> Optional[str]:
        """
        Get next proxy URL based on rotation strategy.

        Automatically refreshes proxy list if:
        - Cache is older than 6 hours
        - AND auto_fetch is enabled

        Args:
            strategy: Rotation strategy ("round_robin", "least_used", "random")

        Returns:
            Proxy URL or None if no proxies available
        """
        # Ensure initialization has happened
        if not self._initialized:
            await self.initialize()

        # Check if cache is stale and auto-refresh is enabled
        if self._auto_fetch and self._is_cache_stale():
            logger.info("🔄 Proxy cache is stale (>6 hours), refreshing...")
            await self._refresh_proxy_list()

        if not self._proxies:
            return None

        async with self._lock:
            healthy_proxies = [
                (url, config) for url, config in self._proxies.items()
                if config.healthy and not self._is_rate_limited(config)
            ]

            if not healthy_proxies:
                # All proxies unhealthy or rate limited - wait for cooldown
                logger.warning("⚠️  All proxies are rate limited or unhealthy")
                return None

            # Select proxy based on strategy
            if strategy == "round_robin":
                proxy_url, config = healthy_proxies[self._current_index % len(healthy_proxies)]
                self._current_index = (self._current_index + 1) % len(healthy_proxies)

            elif strategy == "least_used":
                # Sort by last used time (oldest first)
                healthy_proxies.sort(key=lambda p: p[1].last_used)
                proxy_url, config = healthy_proxies[0]

            elif strategy == "random":
                proxy_url, config = random.choice(healthy_proxies)

            else:
                raise ValueError(f"Unknown strategy: {strategy}")

            # Update usage stats
            config.last_used = time.time()
            config.total_requests += 1

            return proxy_url

    def _is_rate_limited(self, config: ProxyConfig) -> bool:
        """
        Check if proxy has exceeded rate limit.

        Args:
            config: Proxy configuration

        Returns:
            True if rate limited
        """
        if config.max_requests_per_minute <= 0:
            return False

        now = time.time()
        time_since_last_use = now - config.last_used

        # Reset if more than 1 minute has passed
        if time_since_last_use > 60:
            return False

        # Check if we're within the rate limit window
        return time_since_last_use < (60.0 / config.max_requests_per_minute)

    def _is_cache_stale(self) -> bool:
        """
        Check if proxy cache is stale (older than 6 hours).

        Returns:
            True if cache is stale and needs refresh
        """
        if self._cache_timestamp == 0:
            return False  # Not initialized yet

        age = time.time() - self._cache_timestamp
        return age > self._cache_ttl

    async def _refresh_proxy_list(self) -> None:
        """
        Refresh the proxy list by fetching new proxies from free lists.

        Only works if auto_fetch is enabled. Replaces existing proxies
        with newly validated ones.
        """
        if not self._auto_fetch:
            logger.warning("⚠️  Cannot refresh proxy list - auto_fetch is disabled")
            return

        logger.info("🔄 Refreshing proxy list from free proxy sources...")

        try:
            # Fetch and validate new proxies
            new_proxies = await self._fetch_and_validate_proxies()

            if not new_proxies:
                logger.warning("⚠️  No new proxies found during refresh, keeping existing ones")
                # Update cache timestamp anyway to avoid continuous refresh attempts
                self._cache_timestamp = time.time()
                return

            async with self._lock:
                # Clear old proxies
                old_count = len(self._proxies)
                self._proxies.clear()

                # Add new proxies
                for proxy_url in new_proxies:
                    self._proxies[proxy_url] = ProxyConfig(
                        url=proxy_url,
                        max_requests_per_minute=self._max_rpm,
                    )

                # Update cache timestamp
                self._cache_timestamp = time.time()

                logger.info(
                    f"✅ Proxy list refreshed: {old_count} old → {len(self._proxies)} new proxies"
                )

        except Exception as e:
            logger.error(f"❌ Failed to refresh proxy list: {e}")
            # Update timestamp to avoid immediate retry
            self._cache_timestamp = time.time()

    async def mark_success(self, proxy_url: str) -> None:
        """
        Mark a proxy request as successful.

        Args:
            proxy_url: Proxy URL that succeeded
        """
        if proxy_url not in self._proxies:
            return

        async with self._lock:
            config = self._proxies[proxy_url]
            config.consecutive_failures = 0

            # Restore health if it was marked unhealthy
            if not config.healthy and self._enable_health_check:
                config.healthy = True
                logger.info(f"✅ Proxy restored to healthy: {self._sanitize_url(proxy_url)}")

    async def mark_failure(self, proxy_url: str, error: Exception) -> None:
        """
        Mark a proxy request as failed.

        Args:
            proxy_url: Proxy URL that failed
            error: Exception that occurred
        """
        if proxy_url not in self._proxies:
            return

        async with self._lock:
            config = self._proxies[proxy_url]
            config.consecutive_failures += 1

            error_str = str(error).lower()
            is_proxy_error = any(term in error_str for term in [
                "proxy", "connection", "timeout", "unreachable"
            ])

            # Mark unhealthy if too many consecutive failures
            if is_proxy_error and config.consecutive_failures >= self._max_consecutive_failures:
                config.healthy = False
                logger.warning(
                    f"❌ Proxy marked unhealthy after {config.consecutive_failures} failures: "
                    f"{self._sanitize_url(proxy_url)}"
                )

    def _sanitize_url(self, url: str) -> str:
        """
        Sanitize proxy URL for logging (hide credentials).

        Args:
            url: Proxy URL

        Returns:
            Sanitized URL
        """
        if "@" in url:
            # Format: http://user:pass@host:port -> http://***:***@host:port
            parts = url.split("@")
            return f"***:***@{parts[1]}"
        return url

    def get_stats(self) -> Dict[str, any]:
        """
        Get proxy pool statistics.

        Returns:
            Dictionary with statistics for each proxy
        """
        stats = {}
        for url, config in self._proxies.items():
            stats[self._sanitize_url(url)] = {
                "healthy": config.healthy,
                "total_requests": config.total_requests,
                "consecutive_failures": config.consecutive_failures,
                "last_used": config.last_used,
            }
        return stats

    def get_healthy_count(self) -> int:
        """
        Get count of healthy proxies.

        Returns:
            Number of healthy proxies
        """
        return sum(1 for config in self._proxies.values() if config.healthy)

    async def refresh_proxies(self) -> bool:
        """
        Manually trigger a proxy list refresh.

        Only works if auto_fetch is enabled.

        Returns:
            True if refresh was successful, False otherwise
        """
        if not self._auto_fetch:
            logger.warning("⚠️  Cannot manually refresh - auto_fetch is disabled")
            return False

        logger.info("🔄 Manual proxy refresh triggered...")
        await self._refresh_proxy_list()

        return len(self._proxies) > 0

    def get_cache_age(self) -> float:
        """
        Get the age of the proxy cache in seconds.

        Returns:
            Age in seconds, or 0 if not initialized
        """
        if self._cache_timestamp == 0:
            return 0.0

        return time.time() - self._cache_timestamp

    def is_enabled(self) -> bool:
        """
        Check if proxy rotation is enabled or will be enabled.

        Returns True if:
        - Proxies are already loaded
        - Proxies were provided in constructor (not yet initialized)
        - Auto-fetch is enabled (not yet initialized)
        - Proxies are configured via environment variables (not yet initialized)

        Returns False if:
        - Initialization completed but found no working proxies
        - No proxy configuration provided

        Returns:
            True if proxies are configured or will be available
        """
        # Already have proxies loaded
        if len(self._proxies) > 0:
            return True

        # If initialization already happened but found no proxies, disabled
        if self._initialized:
            return False

        # Have proxies to load
        if self._provided_proxies:
            return True

        # Will auto-fetch proxies
        if self._auto_fetch:
            return True

        # Check environment variables
        if os.environ.get("PROXY_LIST") or os.environ.get("PROXY_CONFIG_PATH"):
            return True

        return False

    # ==================== Synchronous API ====================
    # These methods allow using the rotator from synchronous code
    # (e.g., with curl_cffi or other sync libraries)

    def _run_async(self, coro):
        """
        Helper to run async code from sync context.

        Tries to use existing event loop if available, otherwise creates new one.

        Args:
            coro: Coroutine to run

        Returns:
            Result of the coroutine
        """
        try:
            if sys.platform == 'win32':
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                
            # Try to get existing event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Loop is already running (e.g., in async context)
                # Create a new loop in a thread
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, coro)
                    return future.result()
            else:
                # Loop exists but not running
                return loop.run_until_complete(coro)
        except RuntimeError:
            # No event loop exists, create new one
            return asyncio.run(coro)

    def initialize_sync(self) -> None:
        """
        Synchronous version of initialize().

        Initialize the proxy rotator from synchronous code.

        Example:
            rotator = ProxyRotator(auto_fetch_proxies=True)
            rotator.initialize_sync()  # Blocks until initialized
        """
        return self._run_async(self.initialize())

    def get_proxy_sync(self, strategy: str = "round_robin") -> Optional[str]:
        """
        Synchronous version of get_proxy().

        Get next proxy URL from synchronous code.

        Args:
            strategy: Rotation strategy ("round_robin", "least_used", "random")

        Returns:
            Proxy URL or None if no proxies available

        Example:
            rotator = ProxyRotator(auto_fetch_proxies=True)
            proxy = rotator.get_proxy_sync()  # Blocks until proxy available

            # Use with curl_cffi
            import curl_cffi.requests as requests
            response = requests.get(url, proxy=proxy)
        """
        return self._run_async(self.get_proxy(strategy))

    def mark_success_sync(self, proxy_url: str) -> None:
        """
        Synchronous version of mark_success().

        Mark a proxy request as successful from synchronous code.

        Args:
            proxy_url: Proxy URL that succeeded

        Example:
            rotator.mark_success_sync(proxy)
        """
        return self._run_async(self.mark_success(proxy_url))

    def mark_failure_sync(self, proxy_url: str, error: Exception) -> None:
        """
        Synchronous version of mark_failure().

        Mark a proxy request as failed from synchronous code.

        Args:
            proxy_url: Proxy URL that failed
            error: Exception that occurred

        Example:
            try:
                response = requests.get(url, proxy=proxy)
            except Exception as e:
                rotator.mark_failure_sync(proxy, e)
        """
        return self._run_async(self.mark_failure(proxy_url, error))

    def refresh_proxies_sync(self) -> bool:
        """
        Synchronous version of refresh_proxies().

        Manually trigger a proxy list refresh from synchronous code.

        Returns:
            True if refresh was successful, False otherwise

        Example:
            success = rotator.refresh_proxies_sync()
            if success:
                print("Proxies refreshed!")
        """
        return self._run_async(self.refresh_proxies())
