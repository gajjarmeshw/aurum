"""
Event Bus — Multiprocessing-safe pub/sub for pipeline ↔ server communication.

Uses multiprocessing.Queue for cross-process message passing.
Pipeline publishes events; server subscribes and pushes to browsers via SSE.
"""

import multiprocessing
import queue
import time
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Event:
    """A single event on the bus."""
    topic: str              # candle_close, tick, indicator_update, confluence_update, alert, feed_status
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "Event":
        d = json.loads(raw)
        return cls(**d)


class EventBus:
    """
    Multiprocessing-safe event bus.

    Usage:
        bus = EventBus()
        # In pipeline process:
        bus.publish("candle_close", {"timeframe": "H1", ...})
        # In server process:
        event = bus.subscribe(timeout=1.0)
    """

    def __init__(self, latest_dict: dict | None = None):
        self._queue: multiprocessing.Queue = multiprocessing.Queue(maxsize=10_000)
        # Use provided shared dict (from a Manager) or fallback to local dict
        self._latest = latest_dict if latest_dict is not None else {}
        self._manager = None # No longer storing manager to avoid pickling issues

    def publish(self, topic: str, data: dict | None = None):
        """Publish an event to all subscribers."""
        event = Event(topic=topic, data=data or {})
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            # Drop oldest if full — real-time data, stale events are useless
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._queue.put_nowait(event)
        self._latest[topic] = data or {}

    def subscribe(self, timeout: float = 1.0) -> Event | None:
        """
        Block until an event is available or timeout.
        Returns None on timeout.
        """
        try:
            event = self._queue.get(timeout=timeout)
            self._latest[event.topic] = event.data
            return event
        except queue.Empty:
            return None

    def get_latest(self, topic: str) -> dict | None:
        """Get the most recent data for a topic."""
        return self._latest.get(topic)

    def get_all_latest(self) -> dict[str, Any]:
        """Get the entire latest state cache."""
        return dict(self._latest)

    def drain(self, max_events: int = 100) -> list[Event]:
        """Drain up to max_events from the queue without blocking."""
        events = []
        for _ in range(max_events):
            try:
                event = self._queue.get_nowait()
                self._latest[event.topic] = event.data
                events.append(event)
            except queue.Empty:
                break
        return events
