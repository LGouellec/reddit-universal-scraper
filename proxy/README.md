# Proxy Rotator

A robust proxy rotation system with automatic fetching, validation, and health checking.

## Features

- **Automatic Proxy Fetching**: Download free SOCKS5 proxies from public lists
- **Auto-Refresh**: Automatically refresh proxy list when cache is stale (>6 hours)
- **Proxy Validation**: Test proxies before use to ensure they're working
- **Local Caching**: Cache validated proxies with configurable TTL
- **Round-Robin Rotation**: Distribute requests evenly across proxies
- **Rate Limiting**: Per-proxy request rate limiting
- **Health Checking**: Automatic detection and failover of dead proxies
- **Multiple Strategies**: round_robin, least_used, random

## Quick Start

### Async Usage (Default)

```python
from common import ProxyRotator

# Initialize with manual proxy list
rotator = ProxyRotator(
    proxies=[
        "socks5://proxy1.example.com:1080",
        "socks5://proxy2.example.com:1080"
    ]
)

# Async API (use in async functions)
proxy_url = await rotator.get_proxy()

# Mark success/failure for health tracking
await rotator.mark_success(proxy_url)
await rotator.mark_failure(proxy_url, exception)
```

### Sync Usage (For curl_cffi, requests, etc.)

```python
from common import ProxyRotator

# Initialize with manual proxy list
rotator = ProxyRotator(
    proxies=[
        "socks5://proxy1.example.com:1080",
        "socks5://proxy2.example.com:1080"
    ]
)

# Sync API (use in regular functions)
rotator.initialize_sync()  # Initialize first
proxy_url = rotator.get_proxy_sync()

# Mark success/failure for health tracking
rotator.mark_success_sync(proxy_url)
rotator.mark_failure_sync(proxy_url, exception)
```

**Use the `_sync` methods when:**
- Using with `curl_cffi` (synchronous HTTP library)
- Using with `requests` library
- Working in synchronous/non-async code
- Integrating with existing sync frameworks

### Auto-Fetch Mode

```python
from common import ProxyRotator

# Initialize with auto-fetch enabled
rotator = ProxyRotator(
    auto_fetch_proxies=True,
    auto_fetch_max_proxies=50  # Limit to 50 validated proxies
)

# Proxies are fetched and validated on first use
proxy_url = await rotator.get_proxy()
```

### Auto-Refresh (New!)

When `auto_fetch` is enabled, the proxy list automatically refreshes when the cache is stale (>6 hours):

```python
from common import ProxyRotator

# Enable auto-fetch (enables auto-refresh)
rotator = ProxyRotator(
    auto_fetch_proxies=True,
    auto_fetch_max_proxies=30
)

await rotator.initialize()  # Initial fetch

# After 6+ hours, next get_proxy() call will auto-refresh
proxy = await rotator.get_proxy()  # Auto-refreshes if cache is stale

# Or manually trigger a refresh anytime
await rotator.refresh_proxies()

# Check cache age
cache_age_hours = rotator.get_cache_age() / 3600
print(f"Cache age: {cache_age_hours:.1f} hours")
```

**How it works:**
- Cache timestamp is set when proxies are fetched/initialized
- Every `get_proxy()` call checks if cache is older than 6 hours
- If stale AND `auto_fetch=True`, fetches new proxies automatically
- Old proxies are replaced with newly validated ones
- Cache timestamp is updated after successful refresh

**Benefits:**
- Long-running scrapers always have fresh proxies
- Automatically recover from proxy failures over time
- No manual intervention required
- Configurable via `PROXY_AUTO_FETCH` environment variable

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PROXY_LIST` | Comma-separated proxy URLs | None |
| `PROXY_CONFIG_PATH` | Path to proxy config file (one per line) | None |
| `PROXY_AUTO_FETCH` | Enable auto-fetching from free lists | `false` |
| `PROXY_AUTO_FETCH_MAX` | Max validated proxies when auto-fetching | `50` |
| `PROXY_MAX_RPM` | Max requests per minute per proxy | `60` |
| `PROXY_MAX_FAILURES` | Consecutive failures before unhealthy | `3` |
| `PROXY_LIST_URL` | Custom URL for proxy list | proxifly free-proxy-list |
| `PROXY_CACHE_DIR` | Cache directory | `.cache/` |
| `PROXY_CACHE_TTL` | Cache TTL in seconds | `3600` (1 hour) |
| `PROXY_TEST_URL` | URL to test proxies against | httpbin.org/ip |
| `PROXY_TEST_TIMEOUT` | Connection timeout for testing | `10` |
| `PROXY_TEST_CONCURRENT` | Concurrent proxy tests | `20` |

### Example with Environment Variables

```bash
# Enable auto-fetch mode
export PROXY_AUTO_FETCH=true
export PROXY_AUTO_FETCH_MAX=100

# Custom proxy list URL
export PROXY_LIST_URL=https://example.com/proxies.txt

# Cache configuration
export PROXY_CACHE_TTL=7200  # 2 hours

# Run your scraper
python scraper.py
```

## Proxy Formats

The rotator supports both HTTP and SOCKS5 proxies:

```
# SOCKS5 (recommended - better compatibility)
socks5://host:port
socks5://user:pass@host:port

# HTTP (may be blocked by some services)
http://host:port
http://user:pass@host:port
```

## How It Works

### Auto-Fetch Flow

1. **Fetch**: Downloads proxy list from configured URL
2. **Cache**: Saves list locally with TTL
3. **Validate**: Tests each proxy for connectivity (concurrent)
4. **Initialize**: Adds working proxies to rotation pool
5. **Rotate**: Distributes requests across healthy proxies

### Health Checking

- Tracks consecutive failures per proxy
- Marks proxy as unhealthy after N failures
- Automatically restores proxy on successful request
- Skips unhealthy proxies during rotation

### Rate Limiting

- Per-proxy request rate limiting (requests/minute)
- Prevents overwhelming individual proxies
- Automatically skips rate-limited proxies

## Synchronous API

The proxy rotator provides a synchronous API for use with non-async libraries like `curl_cffi`, `requests`, etc.

### Available Sync Methods

| Async Method | Sync Method | Description |
|--------------|-------------|-------------|
| `await initialize()` | `initialize_sync()` | Initialize the rotator |
| `await get_proxy()` | `get_proxy_sync()` | Get next proxy URL |
| `await mark_success()` | `mark_success_sync()` | Mark proxy as successful |
| `await mark_failure()` | `mark_failure_sync()` | Mark proxy as failed |
| `await refresh_proxies()` | `refresh_proxies_sync()` | Manually refresh proxy list |

### Example with curl_cffi

```python
from common.proxy import ProxyRotator
from curl_cffi import requests

# Initialize rotator
rotator = ProxyRotator(auto_fetch_proxies=True)
rotator.initialize_sync()  # Blocks until initialized

# Get proxy and make request
proxy = rotator.get_proxy_sync()

try:
    response = requests.get(
        "https://api.example.com/data",
        proxy=proxy,
        impersonate="chrome119"
    )
    
    if response.status_code == 200:
        rotator.mark_success_sync(proxy)
        print(response.json())
    else:
        rotator.mark_failure_sync(proxy, Exception(f"HTTP {response.status_code}"))
        
except Exception as e:
    rotator.mark_failure_sync(proxy, e)
    raise
```

### Example with requests library

```python
from common.proxy import ProxyRotator
import requests

rotator = ProxyRotator(
    proxies=["socks5://proxy1:1080", "socks5://proxy2:1080"]
)
rotator.initialize_sync()

for i in range(10):
    proxy = rotator.get_proxy_sync(strategy="round_robin")
    
    try:
        response = requests.get("https://httpbin.org/ip", proxies={"https": proxy})
        rotator.mark_success_sync(proxy)
        print(f"Request {i}: {response.json()['origin']}")
    except Exception as e:
        rotator.mark_failure_sync(proxy, e)
```

### How Sync API Works

The sync methods internally use `asyncio.run()` or the existing event loop to run async code from synchronous context. This allows seamless integration with sync libraries without requiring async/await syntax.

**Performance Note**: Each sync call creates a small overhead due to event loop management. For high-performance applications with thousands of requests, consider using the async API directly.

## Example: YFinance Scraper

```python
from common import ProxyRotator
import asyncio

async def main():
    # Initialize with auto-fetch
    rotator = ProxyRotator(
        auto_fetch_proxies=True,
        auto_fetch_max_proxies=50,
        max_requests_per_minute=60
    )
    
    # Get proxy for request
    proxy = await rotator.get_proxy(strategy="round_robin")
    
    if proxy:
        try:
            # Make request using proxy
            response = await fetch_data(proxy=proxy)
            await rotator.mark_success(proxy)
        except Exception as e:
            await rotator.mark_failure(proxy, e)
    
    # Check stats
    stats = rotator.get_stats()
    print(f"Healthy proxies: {rotator.get_healthy_count()}")

asyncio.run(main())
```

## Directory Structure

```
proxy/
├── __init__.py          # Package exports
├── rotator.py           # Main ProxyRotator class
├── fetcher.py           # Proxy list fetching
├── validator.py         # Proxy connectivity testing
├── .cache/              # Cached proxy lists
│   └── .gitignore
└── README.md            # This file
```

## Performance Considerations

- **Validation**: Testing 1000 proxies with 20 concurrent tests takes ~5-10 minutes
- **Caching**: Use appropriate TTL to balance freshness vs. validation overhead
- **Max Proxies**: Limit validated proxies (50-100) for faster initialization
- **Concurrent Tests**: Increase for faster validation (but more network load)

## Troubleshooting

### No proxies found

```
⚠️  No working proxies found after validation
```

- Free proxy lists have low success rates (5-20%)
- Try increasing `PROXY_AUTO_FETCH_MAX` or use a better proxy source
- Consider using paid proxy services for production

### All proxies rate limited

```
⚠️  All proxies are rate limited or unhealthy
```

- Reduce request rate or increase `PROXY_MAX_RPM`
- Add more proxies to the pool
- Implement backoff/retry logic

### Validation too slow

```
# Increase concurrent tests
export PROXY_TEST_CONCURRENT=50

# Reduce timeout
export PROXY_TEST_TIMEOUT=5

# Limit max proxies
export PROXY_AUTO_FETCH_MAX=30
```

## Advanced Usage

### Custom Proxy Source

```python
from common.proxy.fetcher import ProxyFetcher

# Use custom proxy list URL
fetcher = ProxyFetcher(
    proxy_list_url="https://example.com/proxies.txt",
    cache_ttl=7200  # 2 hours
)

proxies = await fetcher.fetch_proxies()
```

### Manual Validation

```python
from common.proxy.validator import ProxyValidator

# Test specific proxies
validator = ProxyValidator(timeout=10)
working = await validator.validate_proxies([
    "socks5://proxy1.com:1080",
    "socks5://proxy2.com:1080"
])
```

### Test Single Proxy

```python
from common.proxy.validator import ProxyValidator

validator = ProxyValidator()
is_working, error = await validator.test_proxy("socks5://proxy.com:1080")

if is_working:
    print("✅ Proxy is working")
else:
    print(f"❌ Proxy failed: {error}")
```
