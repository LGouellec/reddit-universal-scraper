"""
Proxy fetcher for downloading and caching proxy lists.
"""
import logging
import os
import time
from pathlib import Path
from typing import List, Optional
import aiohttp

logger = logging.getLogger(__name__)

# Default proxy list URL
DEFAULT_PROXY_LIST_URL = "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt"

# Cache configuration
DEFAULT_CACHE_DIR = Path(__file__).parent / ".cache"
DEFAULT_CACHE_TTL = 3600  # 1 hour in seconds


class ProxyFetcher:
    """
    Fetches and caches proxy lists from remote sources.

    Features:
    - Downloads proxy lists from GitHub or custom URLs
    - Caches proxies locally with configurable TTL
    - Supports SOCKS5 proxy format
    - Automatic cache refresh when expired

    Environment Variables:
        PROXY_LIST_URL: Custom URL for proxy list (default: proxifly free-proxy-list)
        PROXY_CACHE_DIR: Directory for caching proxy lists
        PROXY_CACHE_TTL: Cache TTL in seconds (default: 3600)
    """

    def __init__(
        self,
        proxy_list_url: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        cache_ttl: int = DEFAULT_CACHE_TTL,
    ):
        """
        Initialize proxy fetcher.

        Args:
            proxy_list_url: URL to fetch proxy list from
            cache_dir: Directory to cache proxy lists
            cache_ttl: Cache time-to-live in seconds
        """
        self.proxy_list_url = proxy_list_url or os.environ.get(
            "PROXY_LIST_URL", DEFAULT_PROXY_LIST_URL
        )
        self.cache_dir = cache_dir or Path(
            os.environ.get("PROXY_CACHE_DIR", DEFAULT_CACHE_DIR)
        )
        self.cache_ttl = int(os.environ.get("PROXY_CACHE_TTL", cache_ttl))
        self.cache_file = self.cache_dir / "proxy_list.txt"

        # Ensure cache directory exists
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    async def fetch_proxies(self, force_refresh: bool = False) -> List[str]:
        """
        Fetch proxy list from remote source or cache.

        Args:
            force_refresh: Force download even if cache is valid

        Returns:
            List of proxy URLs in format socks5://host:port
        """
        # Check if cache is valid
        if not force_refresh and self._is_cache_valid():
            logger.info(f"📦 Loading proxies from cache: {self.cache_file}")
            return self._load_from_cache()

        # Download fresh proxy list
        logger.info(f"🌐 Downloading proxy list from: {self.proxy_list_url}")
        try:
            proxies = await self._download_proxies()

            if proxies:
                self._save_to_cache(proxies)
                logger.info(f"✅ Downloaded and cached {len(proxies)} proxies")
            else:
                logger.warning("⚠️  No proxies found in downloaded list")

                # Fall back to cache if available
                if self.cache_file.exists():
                    logger.info("📦 Falling back to cached proxy list")
                    return self._load_from_cache()

            return proxies

        except Exception as e:
            logger.error(f"❌ Failed to download proxy list: {e}")

            # Fall back to cache if available
            if self.cache_file.exists():
                logger.info("📦 Falling back to cached proxy list")
                return self._load_from_cache()

            return []

    async def _download_proxies(self) -> List[str]:
        """
        Download proxy list from remote URL.

        Returns:
            List of proxy URLs
        """
        async with aiohttp.ClientSession() as session:
            async with session.get(self.proxy_list_url, timeout=30) as response:
                response.raise_for_status()
                content = await response.text()

        # Parse proxy list (one proxy per line)
        proxies = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Convert IP:port format to socks5://IP:port
            if "://" not in line:
                line = f"socks5://{line}"

            proxies.append(line)

        return proxies

    def _is_cache_valid(self) -> bool:
        """
        Check if cached proxy list is still valid.

        Returns:
            True if cache exists and is not expired
        """
        if not self.cache_file.exists():
            return False

        # Check cache age
        cache_age = time.time() - self.cache_file.stat().st_mtime
        return cache_age < self.cache_ttl

    def _load_from_cache(self) -> List[str]:
        """
        Load proxy list from cache file.

        Returns:
            List of proxy URLs
        """
        with open(self.cache_file, "r") as f:
            proxies = [line.strip() for line in f if line.strip()]
        return proxies

    def _save_to_cache(self, proxies: List[str]) -> None:
        """
        Save proxy list to cache file.

        Args:
            proxies: List of proxy URLs to cache
        """
        with open(self.cache_file, "w") as f:
            f.write("\n".join(proxies))
