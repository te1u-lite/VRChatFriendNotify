from __future__ import annotations
import time, threading , random

class RateLimiter:
    """
    Token-bucket rate limiter (thread-safe).
    capacity: 最大トークン (=瞬間バーストの上限)
    refill_rate: 1秒あたりの補充トークン数 (=平均レート)
    """
    def __init__(self,capacity: int,refill_rate: float):
        if capacity <= 0 or refill_rate <=0:
            raise ValueError("capacity and refill_rate must be positive")
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self.tokens = float(capacity)
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()
        pass

    def _refill_locked(self,now: float)->None:
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(self.capacity,self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

    def _compute_wait_locked(self,need: float)->float:
        if self.tokens >= need:
            return 0.0
        return (need - self.tokens) / self.refill_rate

    def try_acquire(self,tokens: float = 1.0) ->bool:
        now = time.monotonic()
        with self.lock:
            self._refill_locked(now)
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False


    def acquire(self,tokens: float =1.0, cancel_event: threading.Event | None = None,timeout: float | None = None)->bool:
        start = time.monotonic()
        while True:
            now = time.monotonic()
            with self.lock:
                self._refill_locked(now)
                wait = self._compute_wait_locked(tokens)
                if wait <= 0:
                    self.tokens -= tokens
                    return True
            jitter = random.uniform(0,0.02)
            sleep_for = wait + jitter

            if timeout is not None:
                remain = timeout - (now -start)
                if remain <=0:
                    return False
                sleep_for = min(sleep_for,remain)

            if cancel_event is not None:
                if cancel_event.wait(sleep_for):
                    return False
            else:
                time.sleep(sleep_for)