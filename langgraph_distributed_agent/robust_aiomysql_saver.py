import aiomysql
from contextlib import asynccontextmanager
from langgraph.checkpoint.mysql.aio import AIOMySQLSaver
from typing_extensions import AsyncIterator, Self

class RobustAIOMySQLSaver(AIOMySQLSaver):
    """Enhanced version of AIOMySQLSaver with connection pooling
    to handle dropped connections more gracefully.
    """
    
    @classmethod
    @asynccontextmanager
    async def from_conn_string(
        cls,
        conn_string: str,
        *,
        serde=None,
        use_pool: bool = True,
        pool_size: int = 5,
        pool_recycle: int = 1800,  # 30 minutes
        **pool_kwargs
    ) -> AsyncIterator[Self]:
        """
        Create an AIOMySQLSaver instance from a MySQL connection string,
        optionally using a connection pool.

        Args:
            conn_string (str): MySQL connection string.
            serde: Optional serialization/deserialization handler.
            use_pool (bool): Whether to use a connection pool. Defaults to True.
            pool_size (int): Maximum number of connections in the pool. Defaults to 5.
            pool_recycle (int): Time limit (in seconds) before recycling connections. Defaults to 1800 (30 minutes).
            **pool_kwargs: Additional parameters to pass to aiomysql.create_pool.
        """
        conn_params = cls.parse_conn_string(conn_string)
        
        if use_pool:
            # Using connection pool
            pool = await aiomysql.create_pool(
                **conn_params,
                minsize=2,
                maxsize=pool_size,
                autocommit=True,
                pool_recycle=pool_recycle,
                echo=True,
                connect_timeout=30,
                **pool_kwargs
            )
            
            try:
                # Directly use the connection pool; get_connection handles connections internally
                yield cls(conn=pool, serde=serde)
            finally:
                pool.close()
                await pool.wait_closed()
        else:
            # Fallback to direct connection
            async with aiomysql.connect(
                **conn_params,
                autocommit=True,
            ) as conn:
                yield cls(conn=conn, serde=serde)
    
    @classmethod
    @asynccontextmanager
    async def from_pool(
        cls,
        pool: aiomysql.Pool,
        *,
        serde=None
    ) -> AsyncIterator[Self]:
        """
        Create an AIOMySQLSaver instance directly from an existing
        aiomysql connection pool.

        Args:
            pool (aiomysql.Pool): An existing aiomysql connection pool.
            serde: Optional serialization/deserialization handler.
        """
        yield cls(conn=pool, serde=serde) # type: ignore