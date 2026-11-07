"""Centralized logging configuration.

Call ``configure_logging()`` once at application startup (FastAPI lifespan)
to apply a consistent format and level across all
project modules.

Level is controlled by the ``LOG_LEVEL`` environment variable (default INFO).
Format is timestamped and structured so it is both human-readable and
easy to grep.
"""

import logging
import logging.config


def configure_logging(log_level: str = "INFO") -> None:
    """Apply consistent format and level across all project loggers.

    Args:
        log_level: One of DEBUG, INFO, WARNING, ERROR, CRITICAL.
                   Typically passed from ``settings.log_level``.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)-8s %(name)s  %(message)s",
                    "datefmt": "%Y-%m-%d %H:%M:%S",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {
                "level": level,
                "handlers": ["console"],
            },
            # Quiet noisy third-party libraries that flood logs at INFO
            "loggers": {
                "httpx": {"level": "WARNING", "propagate": True},
                "httpcore": {"level": "WARNING", "propagate": True},
                "sqlalchemy.engine": {"level": "WARNING", "propagate": True},
                "apscheduler": {"level": "WARNING", "propagate": True},
                "watchdog": {"level": "WARNING", "propagate": True},
            },
        }
    )
