import asyncio
from contextlib import asynccontextmanager
import uuid

@asynccontextmanager
async def redis_lock(redis_client, lock_key: str, timeout: int = 30, retry_interval: float = 0.1):
    """
    A simple distributed lock implementation using Redis `SET NX EX`.

    This lock ensures that only one process can acquire the given key at a time.
    It uses a UUID as a lock value to verify ownership before releasing.

    Args:
        redis_client: An asynchronous Redis client instance supporting `set`, `get`, and `delete` methods.
        lock_key (str): The Redis key used for the lock.
        timeout (int): The lock expiration time in seconds. Default is 30.
        retry_interval (float): Interval in seconds between lock acquisition retries. Default is 0.1.

    Usage:
        async with redis_lock(redis_client, "my_lock_key"):
            # critical section
            ...

    Notes:
        - This lock is not reentrant.
        - The lock is automatically released when exiting the context if it is still held.
    """
    lock_value = str(uuid.uuid4())  # Unique identifier to ensure safe unlock
    got_lock = False
    try:
        while not got_lock:
            # Try acquiring the lock with SET NX EX
            got_lock = await redis_client.set(lock_key, lock_value, nx=True, ex=timeout)
            if not got_lock:
                await asyncio.sleep(retry_interval)
        yield
    finally:
        # Ensure that we release the lock only if it is still owned by this process
        current_value = await redis_client.get(lock_key)
        if current_value == lock_value:
            await redis_client.delete(lock_key)