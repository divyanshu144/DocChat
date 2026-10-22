"""asyncpg connection factory that reads a rotating password and retries once after an authentication failure."""


def make_async_creator(cfg, provider):
    async def creator():
        import asyncpg

        async def connect(password: str):
            return await asyncpg.connect(
                host=cfg.database_host, port=cfg.database_port, user=cfg.database_user,
                database=cfg.database_name, password=password, ssl=cfg.database_ssl or None)

        try:
            return await connect(await provider.get())
        except asyncpg.exceptions.InvalidPasswordError:
            # Rotation happened since the cached read: refresh once, then give up (no retry loop).
            return await connect(await provider.get(force=True))

    return creator
