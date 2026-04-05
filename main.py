"""
XAUUSD Analyst v4 — Entry Point

Launches two independent processes:
  1. Data Pipeline (asyncio) — WebSocket feeds, candle building, indicators
  2. Web Server (Flask) — Dashboard, SSE, report generation

They communicate via a shared EventBus (multiprocessing.Queue).
"""

import multiprocessing
import signal
import sys
import logging
import asyncio

from pipeline.event_bus import EventBus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(processName)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def start_pipeline(event_bus: EventBus):
    """Run the async data pipeline in its own process."""
    from pipeline.feed_manager import run_pipeline
    logger.info("Data pipeline starting...")
    try:
        asyncio.run(run_pipeline(event_bus))
    except KeyboardInterrupt:
        logger.info("Pipeline shutting down.")


def start_server(event_bus: EventBus):
    """Run the Flask web server in its own process."""
    from server.app import create_app
    import config

    logger.info("Web server starting...")
    app = create_app(event_bus)
    try:
        app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True)
    except KeyboardInterrupt:
        logger.info("Web server shutting down.")


def main():
    logger.info("═" * 50)
    logger.info("  XAUUSD ANALYST v4.0 — Starting")
    logger.info("═" * 50)

    event_bus = EventBus()

    p1 = multiprocessing.Process(
        target=start_pipeline,
        args=(event_bus,),
        name="DataPipeline",
        daemon=True,
    )
    p2 = multiprocessing.Process(
        target=start_server,
        args=(event_bus,),
        name="WebServer",
        daemon=True,
    )

    def shutdown(signum, frame):
        logger.info("Shutdown signal received. Stopping processes...")
        p1.terminate()
        p2.terminate()
        p1.join(timeout=5)
        p2.join(timeout=5)
        logger.info("All processes stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    p1.start()
    p2.start()

    logger.info(f"Pipeline PID: {p1.pid}")
    logger.info(f"Server PID:   {p2.pid}")

    # Block main process until children exit
    p1.join()
    p2.join()


if __name__ == "__main__":
    main()
