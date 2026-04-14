"""
Health Monitor — Tracks feed health, reconnect stats, and uptime.

Publishes health status events for the dashboard.
"""

import time
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FeedHealth:
    """Health metrics for a single feed."""
    name: str
    connected: bool = False
    active: bool = False
    last_tick_time: float = 0.0
    reconnect_count: int = 0
    total_ticks: int = 0
    uptime_start: float = field(default_factory=time.time)

    @property
    def seconds_since_last_tick(self) -> float:
        if self.last_tick_time == 0:
            return 999999.0
        return time.time() - self.last_tick_time

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.uptime_start

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "connected": self.connected,
            "active": self.active,
            "last_tick_time": self.last_tick_time,
            "seconds_since_last_tick": round(self.seconds_since_last_tick, 1),
            "reconnect_count": self.reconnect_count,
            "total_ticks": self.total_ticks,
            "uptime_seconds": round(self.uptime_seconds, 1),
        }


class HealthMonitor:
    """Monitors health of both feeds and publishes status."""

    def __init__(self, on_status_update=None):
        self.primary = FeedHealth(name="oanda", active=True)
        self.fallback = FeedHealth(name="oanda", active=False)
        self.on_status_update = on_status_update
        self._failover_count = 0
        self._current_source = "oanda"

    def record_tick(self, source: str = "oanda"):  # noqa: ARG002
        """Record a tick received from the feed."""
        self.primary.last_tick_time = time.time()
        self.primary.total_ticks += 1

    def update_connection(self, connected: bool):
        """Update connection status."""
        was_connected = self.primary.connected
        self.primary.connected = connected
        if not was_connected and connected:
            self.primary.reconnect_count += 1

    def record_failover(self, to_source: str):
        """Record a failover event."""
        self._failover_count += 1
        self._current_source = to_source
        if to_source == "finnhub":
            self.primary.active = False
            self.fallback.active = True
        else:
            self.primary.active = True
            self.fallback.active = False
        logger.warning(f"Failover #{self._failover_count} → {to_source}")

    def get_status(self) -> dict:
        """Get full health status for dashboard."""
        return {
            "current_source": self._current_source,
            "failover_count": self._failover_count,
            "primary": self.primary.to_dict(),
            "fallback": self.fallback.to_dict(),
        }
