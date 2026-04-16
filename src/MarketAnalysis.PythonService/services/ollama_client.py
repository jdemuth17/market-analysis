"""Ollama Cloud client with concurrency control, queue-and-retry, and structured output support."""

import asyncio
import logging
import time
from typing import Optional, Any
from datetime import datetime, timedelta
import httpx
from config import Settings

logger = logging.getLogger(__name__)


class OllamaQueueFullError(Exception):
    """Raised when Ollama request queue is at capacity."""
    pass


class QueuedRequest:
    """Queued request with TTL tracking."""
    def __init__(self, model: str, messages: list[dict], format_schema: Optional[dict], created_at: datetime):
        self.model = model
        self.messages = messages
        self.format_schema = format_schema
        self.created_at = created_at


class OllamaClient:
    """Async Ollama Cloud client with semaphore-gated concurrency and exponential backoff retry."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._semaphore = asyncio.Semaphore(3)
        self._queue: asyncio.Queue[QueuedRequest] = asyncio.Queue(maxsize=settings.ollama_queue_max)
        
        if len(settings.ollama_api_key) < 10:
            logger.warning("Ollama API key too short or missing, client will operate in VADER-only mode")
            self._client = None
        else:
            self._client = httpx.AsyncClient(
                base_url=settings.ollama_base_url,
                headers={"Authorization": f"Bearer {settings.ollama_api_key}"},
                timeout=settings.ollama_timeout_seconds,
            )
        
        self._consumer_task: Optional[asyncio.Task] = None
        self._running = False

    async def chat(self, model: str, messages: list[dict], format_schema: Optional[dict] = None) -> dict:
        """Send chat request to Ollama Cloud with structured output support.
        
        Args:
            model: Model name (e.g., 'qwen3.5', 'deepseek-v3.2')
            messages: List of message dicts with 'role' and 'content'
            format_schema: Optional JSON schema for structured output
        
        Returns:
            Response dict with 'message' key containing assistant reply
        """
        if self._client is None:
            raise Exception("Ollama client not initialized: API key validation failed")
        
        async with self._semaphore:
            return await self._chat_with_retry(model, messages, format_schema)

    async def _chat_with_retry(self, model: str, messages: list[dict], format_schema: Optional[dict]) -> dict:
        """Internal chat with exponential backoff retry."""
        last_exception = None
        
        for attempt in range(self._settings.ollama_retry_max_attempts):
            try:
                payload: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                }
                if format_schema:
                    payload["format"] = format_schema
                
                response = await self._client.post("/api/chat", json=payload)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code in (429, 503):
                    delay = self._settings.ollama_retry_base_delay * (2 ** attempt)
                    logger.warning(f"Ollama returned {response.status_code}, retrying in {delay}s (attempt {attempt + 1}/{self._settings.ollama_retry_max_attempts})")
                    await asyncio.sleep(delay)
                    last_exception = Exception(f"HTTP {response.status_code}")
                    continue
                else:
                    response.raise_for_status()
                    
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                delay = self._settings.ollama_retry_base_delay * (2 ** attempt)
                logger.warning(f"Ollama request failed: {e}, retrying in {delay}s (attempt {attempt + 1}/{self._settings.ollama_retry_max_attempts})")
                await asyncio.sleep(delay)
                last_exception = e
                continue
        
        logger.error(f"Ollama request failed after {self._settings.ollama_retry_max_attempts} attempts, queuing for retry")
        await self._enqueue(model, messages, format_schema)
        raise Exception(f"Ollama request failed after retries: {last_exception}")

    async def _enqueue(self, model: str, messages: list[dict], format_schema: Optional[dict]):
        """Add failed request to retry queue."""
        try:
            request = QueuedRequest(model, messages, format_schema, datetime.utcnow())
            self._queue.put_nowait(request)
            logger.info(f"Queued request for retry (queue size: {self._queue.qsize()})")
        except asyncio.QueueFull:
            logger.error("Retry queue is full")
            raise OllamaQueueFullError("Request queue at capacity")

    async def start_queue_consumer(self):
        """Start background task to drain retry queue."""
        if self._running:
            logger.warning("Queue consumer already running")
            return
        
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume_queue())
        logger.info("Ollama queue consumer started")

    async def _consume_queue(self):
        """Background task that drains the retry queue with exponential backoff."""
        while self._running:
            try:
                request = await asyncio.wait_for(self._queue.get(), timeout=5.0)
                
                age = datetime.utcnow() - request.created_at
                if age.total_seconds() > self._settings.ollama_queue_ttl_seconds:
                    logger.warning(f"Dropping queued request older than {self._settings.ollama_queue_ttl_seconds}s")
                    self._queue.task_done()
                    continue
                
                try:
                    async with self._semaphore:
                        await self._chat_with_retry(request.model, request.messages, request.format_schema)
                    logger.info(f"Successfully processed queued request (queue size: {self._queue.qsize()})")
                except Exception as e:
                    logger.error(f"Failed to process queued request even after retries: {e}")
                finally:
                    self._queue.task_done()
                    
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Queue consumer error: {e}")
                await asyncio.sleep(1)

    async def stop(self):
        """Stop queue consumer and close HTTP client."""
        logger.info("Stopping Ollama client...")
        self._running = False
        
        if self._consumer_task:
            await self._queue.join()
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
        
        if self._client:
            await self._client.aclose()
        logger.info("Ollama client stopped")
