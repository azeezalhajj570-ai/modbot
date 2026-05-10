from prometheus_client import Counter, Histogram

MESSAGES_TOTAL = Counter("combot_messages_total", "Total incoming messages", ["chat_type"])
MODERATION_ACTIONS_TOTAL = Counter(
    "combot_moderation_actions_total",
    "Moderation actions by type",
    ["action"],
)
HANDLER_DURATION = Histogram("combot_handler_duration_seconds", "Handler latency", ["handler"])
