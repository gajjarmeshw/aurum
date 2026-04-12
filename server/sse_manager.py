"""
SSE Manager — Server-Sent Events connection manager.

Subscribes to EventBus, pushes events to connected browsers.
Thread-safe queue per client connection.
"""

import queue
import json
import time
import threading
import logging

from pipeline.event_bus import EventBus

logger = logging.getLogger(__name__)


class SSEManager:
    """Manages SSE connections to browsers."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._clients: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._running = True
        self._latest_state: dict = self.event_bus.get_all_latest()

        # Start background thread to bridge EventBus → SSE clients
        self._thread = threading.Thread(target=self._relay_loop, daemon=True)
        self._thread.start()

    def subscribe(self) -> queue.Queue:
        """Register a new SSE client. Returns a queue to read events from."""
        client_queue = queue.Queue(maxsize=100)

        # Send current state immediately
        if self._latest_state:
            try:
                client_queue.put_nowait({
                    "event": "full_state",
                    "data": self._latest_state,
                })
            except queue.Full:
                pass

        with self._lock:
            self._clients.append(client_queue)

        logger.info(f"SSE client connected. Total: {len(self._clients)}")
        return client_queue

    def unsubscribe(self, client_queue: queue.Queue):
        """Remove a disconnected SSE client."""
        with self._lock:
            if client_queue in self._clients:
                self._clients.remove(client_queue)
        logger.info(f"SSE client disconnected. Total: {len(self._clients)}")

    def broadcast(self, event_type: str, data: dict):
        """Send an event to all connected clients."""
        message = {"event": event_type, "data": data}
        dead_clients = []

        with self._lock:
            for client_queue in self._clients:
                try:
                    client_queue.put_nowait(message)
                except queue.Full:
                    dead_clients.append(client_queue)

        # Clean up overflowed clients
        for dead in dead_clients:
            self.unsubscribe(dead)

    def _relay_loop(self):
        """Bridge events from EventBus to SSE clients."""
        while self._running:
            event = self.event_bus.subscribe(timeout=0.5)
            if event:
                # Cache latest state per topic
                self._latest_state[event.topic] = event.data

                self.broadcast(event.topic, event.data)

    def stop(self):
        """Stop the relay thread."""
        self._running = False
