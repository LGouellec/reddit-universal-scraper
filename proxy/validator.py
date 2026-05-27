"""
Proxy validator for testing proxy connectivity and availability.
"""
import asyncio
import logging
import time
from typing import List, Optional, Tuple
import aiohttp

logger = logging.getLogger(__name__)

# Test configuration
DEFAULT_TEST_URL = "https://httpbin.org/ip"
DEFAULT_TEST_TIMEOUT = 10  # seconds
DEFAULT_CONCURRENT_TESTS = 20  # number of proxies to test concurrently


class ProxyValidator:
    """
    Validates proxy connectivity and availability.

    Features:
    - Tests proxy connections against a test URL
    - Concurrent validation for faster testing
    - Configurable timeout and test URL
    - Filters out non-working proxies

    Environment Variables:
        PROXY_TEST_URL: URL to test proxies against (default: httpbin.org)
        PROXY_TEST_TIMEOUT: Connection timeout in seconds (default: 10)
        PROXY_TEST_CONCURRENT: Number of concurrent tests (default: 20)
    """

    def __init__(
        self,
        test_url: str = DEFAULT_TEST_URL,
        timeout: int = DEFAULT_TEST_TIMEOUT,
        concurrent_tests: int = DEFAULT_CONCURRENT_TESTS,
    ):
        """
        Initialize proxy validator.

        Args:
            test_url: URL to test proxies against
            timeout: Connection timeout in seconds
            concurrent_tests: Number of proxies to test concurrently
        """
        self.test_url = test_url
        self.timeout = timeout
        self.concurrent_tests = concurrent_tests

    async def validate_proxies(
        self, proxies: List[str], max_proxies: Optional[int] = None
    ) -> List[str]:
        """
        Validate a list of proxies and return only working ones.

        Args:
            proxies: List of proxy URLs to validate
            max_proxies: Maximum number of working proxies to return (stops early)

        Returns:
            List of validated working proxy URLs
        """
        if not proxies:
            return []

        logger.info(
            f"🔍 Validating {len(proxies)} proxies "
            f"(concurrent: {self.concurrent_tests}, timeout: {self.timeout}s)"
        )

        start_time = time.time()
        working_proxies = []
        semaphore = asyncio.Semaphore(self.concurrent_tests)

        # Create validation tasks
        tasks = []
        for proxy_url in proxies:
            task = asyncio.create_task(
                self._validate_single_proxy(proxy_url, semaphore)
            )
            tasks.append(task)

        # Wait for all validations to complete
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter working proxies
        for proxy_url, result in zip(proxies, results):
            if isinstance(result, Exception):
                continue

            if result:
                working_proxies.append(proxy_url)
                # Show immediate feedback for working proxies (INFO level)
                logger.info(f"✅ [{len(working_proxies)}] ONLINE: {self._sanitize_url(proxy_url)}")

                # Stop early if we have enough working proxies
                if max_proxies and len(working_proxies) >= max_proxies:
                    logger.info(
                        f"✅ Found {len(working_proxies)} working proxies "
                        f"(reached max limit, stopping validation)"
                    )
                    # Cancel remaining tasks
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    break
            else:
                logger.debug(f"❌ Proxy failed: {self._sanitize_url(proxy_url)}")

        elapsed = time.time() - start_time
        success_rate = (
            len(working_proxies) / len(proxies) * 100 if proxies else 0
        )

        logger.info(
            f"✅ Validation complete: {len(working_proxies)}/{len(proxies)} working "
            f"({success_rate:.1f}% success rate, {elapsed:.1f}s)"
        )

        return working_proxies

    async def _validate_single_proxy(
        self, proxy_url: str, semaphore: asyncio.Semaphore
    ) -> bool:
        """
        Validate a single proxy by testing connectivity.

        Args:
            proxy_url: Proxy URL to test
            semaphore: Semaphore for concurrent request limiting

        Returns:
            True if proxy is working, False otherwise
        """
        #return True
        async with semaphore:
            try:
                # Create connector with proxy
                connector = aiohttp.TCPConnector(ssl=False)
                timeout = aiohttp.ClientTimeout(total=self.timeout)

                async with aiohttp.ClientSession(
                    connector=connector, timeout=timeout
                ) as session:
                    async with session.get(
                        self.test_url, proxy=proxy_url
                    ) as response:
                        # Check if we got a successful response
                        if response.status == 200:
                            # Try to read response to ensure connection works
                            await response.text()
                            return True

                return False

            except asyncio.CancelledError:
                # Task was cancelled (e.g., max_proxies reached)
                raise

            except Exception as e:
                # Log specific errors at debug level
                # logger.debug(f"Proxy validation failed for {self._sanitize_url(proxy_url)}: {e}")
                return False

    def _sanitize_url(self, url: str) -> str:
        """
        Sanitize proxy URL for logging (hide credentials).

        Args:
            url: Proxy URL

        Returns:
            Sanitized URL
        """
        if "@" in url:
            # Format: socks5://user:pass@host:port -> socks5://***:***@host:port
            parts = url.split("@")
            protocol = parts[0].split("://")[0]
            return f"{protocol}://***:***@{parts[1]}"
        return url

    async def test_proxy(self, proxy_url: str) -> Tuple[bool, Optional[str]]:
        """
        Test a single proxy and return result with error message.

        Args:
            proxy_url: Proxy URL to test

        Returns:
            Tuple of (success, error_message)
        """
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            timeout = aiohttp.ClientTimeout(total=self.timeout)

            async with aiohttp.ClientSession(
                connector=connector, timeout=timeout
            ) as session:
                async with session.get(self.test_url, proxy=proxy_url) as response:
                    if response.status == 200:
                        await response.text()
                        return True, None
                    else:
                        return False, f"HTTP {response.status}"

        except Exception as e:
            return False, str(e)
