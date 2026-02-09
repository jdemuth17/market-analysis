import time
import threading
import logging

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, max_tokens: int, refill_rate: float, refill_interval: float = 1.0):
        """
        Args:
            max_tokens: Maximum tokens in the bucket
            refill_rate: Tokens added per refill interval
            refill_interval: Seconds between refills
        """
        self.max_tokens = max_tokens
        self.tokens = max_tokens
        self.refill_rate = refill_rate
        self.refill_interval = refill_interval
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        tokens_to_add = elapsed / self.refill_interval * self.refill_rate
        self.tokens = min(self.max_tokens, self.tokens + tokens_to_add)
        self.last_refill = now

    def acquire(self, tokens: int = 1, timeout: float = 60.0) -> bool:
        """Acquire tokens, blocking until available or timeout."""
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                self._refill()
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True
            if time.monotonic() >= deadline:
                logger.warning(f"Rate limiter timeout waiting for {tokens} tokens")
                return False
            time.sleep(0.1)

    def wait(self):
        """Wait for one token to be available."""
        self.acquire(1)


# Pre-configured rate limiters
yahoo_rate_limiter = TokenBucketRateLimiter(
    max_tokens=50,
    refill_rate=0.5,  # ~30 requests per minute = 1800/hour
    refill_interval=1.0,
)

stocktwits_rate_limiter = TokenBucketRateLimiter(
    max_tokens=10,
    refill_rate=0.05,  # ~3 requests per minute = 180/hour
    refill_interval=1.0,
)
