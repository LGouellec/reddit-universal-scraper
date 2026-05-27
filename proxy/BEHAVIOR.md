# ProxyRotator Behavior Documentation

## `is_enabled()` Method Behavior

The `is_enabled()` method returns different values depending on the initialization state and proxy configuration:

### ✅ Returns `True` (Proxy rotation is enabled or will be enabled)

1. **Has loaded proxies**: Proxies are already initialized and available
   ```python
   rotator = ProxyRotator(proxies=['socks5://proxy:1080'])
   await rotator.initialize()
   rotator.is_enabled()  # True - has 1 proxy
   ```

2. **Has proxies to load (before init)**: Proxies were provided but not yet initialized
   ```python
   rotator = ProxyRotator(proxies=['socks5://proxy:1080'])
   rotator.is_enabled()  # True - will load proxies when initialized
   ```

3. **Auto-fetch enabled (before init)**: Will fetch proxies on initialization
   ```python
   rotator = ProxyRotator(auto_fetch_proxies=True)
   rotator.is_enabled()  # True - will fetch proxies when initialized
   ```

4. **Environment variables configured (before init)**: Proxies configured via env vars
   ```python
   os.environ['PROXY_LIST'] = 'socks5://proxy:1080'
   rotator = ProxyRotator()
   rotator.is_enabled()  # True - will load from env vars
   ```

### ❌ Returns `False` (Proxy rotation is disabled)

1. **No configuration provided**
   ```python
   rotator = ProxyRotator()
   rotator.is_enabled()  # False - no proxies configured
   ```

2. **Initialization completed but found 0 working proxies**
   ```python
   # Auto-fetch enabled, but all proxies fail validation
   rotator = ProxyRotator(auto_fetch_proxies=True)
   await rotator.initialize()  # Fetches and validates, finds 0 working
   rotator.is_enabled()  # False - initialized but no working proxies
   ```

3. **After initialization with empty result**
   ```python
   rotator = ProxyRotator()
   await rotator.initialize()  # No proxies to load
   rotator.is_enabled()  # False - initialized, no proxies
   ```

## Auto-Deactivation on Validation Failure

**Key Feature**: If auto-fetch is enabled but finds 0 working proxies after validation, the proxy rotator automatically deactivates itself.

### Example Scenario

```python
import asyncio
from common import ProxyRotator

async def example():
    # Enable auto-fetch
    rotator = ProxyRotator(
        auto_fetch_proxies=True,
        auto_fetch_max_proxies=50
    )
    
    # Before initialization: is_enabled() = True (will fetch)
    print(f"Before init: {rotator.is_enabled()}")  # True
    
    # Initialize: fetches proxies and validates them
    await rotator.initialize()
    # If all proxies fail validation, 0 working proxies
    
    # After initialization: is_enabled() = False (no working proxies)
    print(f"After init: {rotator.is_enabled()}")  # False
    
    # get_proxy() returns None
    proxy = await rotator.get_proxy()
    print(f"Proxy: {proxy}")  # None

asyncio.run(example())
```

### Why This Matters

1. **Graceful Degradation**: If free proxy lists have low quality (common), the scraper can continue without proxies rather than using broken proxies

2. **Clear State**: `is_enabled()` accurately reflects whether proxy rotation is actually working, not just configured

3. **Error Handling**: Calling code can check `is_enabled()` after initialization to decide whether to proceed with or without proxies

### Recommended Usage Pattern

```python
from common import ProxyRotator

async def setup_scraper():
    # Try to enable proxy rotation
    rotator = ProxyRotator(auto_fetch_proxies=True)
    
    # Initialize and validate
    await rotator.initialize()
    
    # Check if we actually have working proxies
    if rotator.is_enabled():
        logger.info(f"✅ Proxy rotation enabled with {rotator.get_healthy_count()} proxies")
        return rotator
    else:
        logger.warning("⚠️ No working proxies found, continuing without proxy rotation")
        return None
```

## State Transitions

```
┌─────────────────────────────────────────────────────────────┐
│ Initial State                                               │
│ _initialized = False                                        │
│ _proxies = {}                                              │
└─────────────────────────────────────────────────────────────┘
                           │
                           │ await initialize()
                           ▼
                    ┌──────────────┐
                    │   Loading    │
                    └──────────────┘
                           │
          ┌────────────────┼────────────────┐
          ▼                                 ▼
┌──────────────────────┐          ┌──────────────────────┐
│ Proxies Found        │          │ No Proxies Found     │
│ _initialized = True  │          │ _initialized = True  │
│ _proxies = {1..N}   │          │ _proxies = {}       │
│ is_enabled() = True  │          │ is_enabled() = False │
└──────────────────────┘          └──────────────────────┘
```

## Implementation Details

### Lazy Initialization

The rotator uses lazy initialization - `initialize()` is automatically called the first time `get_proxy()` is invoked:

```python
rotator = ProxyRotator(auto_fetch_proxies=True)
# Not initialized yet

proxy = await rotator.get_proxy()
# Automatically calls initialize() on first use
```

### Idempotent Initialization

Calling `initialize()` multiple times is safe - it only runs once:

```python
await rotator.initialize()  # Runs initialization
await rotator.initialize()  # No-op (already initialized)
await rotator.initialize()  # No-op (already initialized)
```

### Thread Safety

The rotator uses asyncio locks for thread-safe proxy selection and health tracking:

```python
async with self._lock:
    # Thread-safe proxy selection
    proxy = self._select_next_proxy()
```
