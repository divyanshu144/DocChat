from slowapi import Limiter
from slowapi.util import get_remote_address

# Shared limiter instance — imported by main.py (to register with app) and
# by route modules (to apply per-endpoint stricter limits via @limiter.limit()).
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
