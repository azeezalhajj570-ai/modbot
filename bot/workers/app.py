import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import AsyncIO, CurrentMessage

from bot.config import get_settings

settings = get_settings()
redis_broker = RedisBroker(url=settings.redis_url)
redis_broker.add_middleware(AsyncIO())
redis_broker.add_middleware(CurrentMessage())
dramatiq.set_broker(redis_broker)
