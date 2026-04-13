"""
Async observation queue for non-blocking memory processing.

Queues observations for background compression and storage.
Ensures tool calls return immediately while heavy processing happens asynchronously.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


class ObservationQueue:
    """Async queue for observation processing."""

    def __init__(
        self,
        processor: Optional[Callable[[Dict[str, Any]], Any]] = None,
        maxsize: int = 1000,
        worker_name: str = "memory-worker"
    ):
        """
        Initialize observation queue.

        Args:
            processor: Callable that processes observations (compression, storage)
            maxsize: Max queue size (blocks when full)
            worker_name: Name for worker thread
        """
        self.processor = processor
        self.queue = queue.Queue(maxsize=maxsize)
        self.worker_thread = threading.Thread(
            target=self._process_loop,
            daemon=True,
            name=worker_name
        )
        self.running = False
        self.processed_count = 0
        self.error_count = 0

    def start(self) -> None:
        """Start the background worker thread."""
        if self.running:
            logger.warning("Observation queue already running")
            return

        self.running = True
        self.worker_thread.start()
        logger.info(f"Observation worker started: {self.worker_thread.name}")

    def stop(self, timeout: float = 10.0) -> bool:
        """
        Stop the background worker thread.

        Args:
            timeout: Max seconds to wait for queue to drain

        Returns:
            True if worker stopped gracefully
        """
        if not self.running:
            return True

        self.running = False

        # Send sentinel value to stop worker
        try:
            self.queue.put(None, timeout=timeout)
        except queue.Full:
            logger.warning("Queue full, forcing stop")

        # Wait for worker to finish
        self.worker_thread.join(timeout=timeout)

        if self.worker_thread.is_alive():
            logger.warning("Worker thread did not stop gracefully")
            return False

        logger.info(
            f"Observation worker stopped "
            f"(processed: {self.processed_count}, "
            f"errors: {self.error_count})"
        )
        return True

    def enqueue(self, observation: Dict[str, Any], timeout: float = 5.0) -> bool:
        """
        Add observation to processing queue.

        Args:
            observation: Observation data dict
            timeout: Max seconds to wait if queue is full

        Returns:
            True if observation was enqueued
        """
        if not self.running:
            logger.warning("Cannot enqueue: worker not running")
            return False

        try:
            self.queue.put(observation, timeout=timeout)
            logger.debug(
                f"Enqueued observation "
                f"(queue size: {self.queue.qsize()})"
            )
            return True
        except queue.Full:
            logger.error(
                f"Observation queue full ({self.queue.maxsize}), "
                f"dropping observation"
            )
            return False

    def _process_loop(self) -> None:
        """Background worker loop."""
        logger.info("Observation worker loop started")

        while self.running:
            try:
                # Get next observation (with timeout for responsiveness)
                try:
                    observation = self.queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                # Check for sentinel (stop signal)
                if observation is None:
                    break

                # Process observation
                if self.processor:
                    try:
                        self.processor(observation)
                        self.processed_count += 1
                        logger.debug(
                            f"Processed observation "
                            f"(total: {self.processed_count})"
                        )
                    except Exception as e:
                        self.error_count += 1
                        logger.error(
                            f"Error processing observation: {e}",
                            exc_info=True
                        )
                else:
                    logger.debug(
                        "No processor registered, skipping observation"
                    )

                self.queue.task_done()

            except Exception as e:
                logger.error(
                    f"Unexpected error in worker loop: {e}",
                    exc_info=True
                )
                self.error_count += 1

        logger.info("Observation worker loop ended")

    def size(self) -> int:
        """Get current queue size."""
        return self.queue.qsize()

    def empty(self) -> bool:
        """Check if queue is empty."""
        return self.queue.empty()

    def join(self, timeout: Optional[float] = None) -> bool:
        """
        Wait for all items to be processed.

        Uses the underlying queue.Queue.join() which waits for task_done() calls.

        Args:
            timeout: Max seconds to wait (None = forever)

        Returns:
            True if queue was drained
        """
        if timeout is None:
            self.queue.join()
            return True

        # Use a thread to call queue.join() with timeout
        import threading
        import time
        evt = threading.Event()

        def _join():
            self.queue.join()
            evt.set()

        t = threading.Thread(target=_join, daemon=True)
        t.start()
        return evt.wait(timeout)

    def stats(self) -> Dict[str, Any]:
        """Get queue statistics."""
        return {
            "running": self.running,
            "queue_size": self.queue.qsize(),
            "processed_count": self.processed_count,
            "error_count": self.error_count,
            "worker_thread": self.worker_thread.name,
        }


# Default processor for observations

def default_observation_processor(observation: Dict[str, Any]) -> None:
    """
    Default processor for observations.
    Compresses and updates observation in storage.
    
    This is a placeholder - in production, this would:
    1. Call LLM for semantic compression
    2. Extract facts and concepts
    3. Update observation in database
    
    Args:
        observation: Observation data dict
    """
    from .compressor import MemoryCompressor
    from .storage import MemoryStorage

    # This is a simplified example
    # In reality, you'd inject storage and compressor instances
    compressor = MemoryCompressor()
    compressed = compressor.compress(observation)

    logger.debug(
        f"Compressed observation: "
        f"{compressed['token_count_original']} → "
        f"{compressed['token_count_compressed']} tokens"
    )
