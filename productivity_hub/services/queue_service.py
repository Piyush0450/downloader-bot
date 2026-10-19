"""
Asynchronous Background Task Queue Service.

Implements an asyncio-based in-memory task queue backed by SQLite persistence.
Enforces strict concurrency limits (global max tasks, per-user active limits,
queue capacity), supports task cancellation, queue position lookup, file tracking
(for cleanup protection), and startup recovery of stale tasks.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from productivity_hub.config.settings import Settings, get_settings
from productivity_hub.database.database import get_db
from productivity_hub.database.models import Task, TaskStatus, User

logger = logging.getLogger("productivity_hub.services.queue")


class QueueOverflowError(Exception):
    """Raised when the global task queue has reached maximum capacity."""
    pass


class UserTaskLimitError(Exception):
    """Raised when a user exceeds their active or queued task quota."""
    pass


class TaskNotFoundError(Exception):
    """Raised when a specified task ID cannot be found."""
    pass


@dataclass
class QueueTask:
    """In-memory representation of a queued/running background task."""
    task_id: str
    user_id: int
    task_type: str
    coro_fn: Callable[..., Any]
    args: Tuple[Any, ...] = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    payload: Optional[Dict[str, Any]] = None
    status: TaskStatus = TaskStatus.PENDING
    file_paths: Set[Path] = field(default_factory=set)
    created_at: datetime = field(default_factory=datetime.utcnow)
    future: Optional[asyncio.Future] = None


class TaskQueueService:
    """
    Async Task Queue Service managing background work processing.
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.max_concurrent = self.settings.MAX_CONCURRENT_TASKS
        self.max_user_active = self.settings.MAX_USER_ACTIVE_TASKS
        self.max_user_queue = self.settings.MAX_USER_QUEUE_TASKS
        self.max_queue_size = self.settings.MAX_QUEUE_SIZE

        # Internal state
        self._pending_queue: List[QueueTask] = []
        self._active_tasks: Dict[str, QueueTask] = {}  # task_id -> QueueTask
        self._running_tasks: Dict[str, asyncio.Task] = {}  # task_id -> asyncio.Task
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._worker_task: Optional[asyncio.Task] = None
        self._accepting_tasks: bool = True
        self._lock = asyncio.Lock()

    @property
    def queue_size(self) -> int:
        """Current number of queued pending tasks."""
        return len(self._pending_queue)

    @property
    def active_task_count(self) -> int:
        """Current number of concurrently executing tasks."""
        return len(self._running_tasks)

    async def start(self) -> None:
        """Start the background task queue processing worker loop."""
        async with self._lock:
            if self._worker_task is None or self._worker_task.done():
                self._accepting_tasks = True
                self._worker_task = asyncio.create_task(self._queue_worker_loop(), name="QueueWorkerLoop")
                logger.info("Task Queue Service started successfully.")

    async def stop(self) -> None:
        """Stop accepting new tasks and cancel running tasks gracefully."""
        async with self._lock:
            self._accepting_tasks = False
            logger.info("Stopping Task Queue Service...")
            
            # Cancel active running tasks
            for task_id, task in list(self._running_tasks.items()):
                if not task.done():
                    task.cancel()
                    logger.info(f"Cancelled running task {task_id}")

            if self._worker_task and not self._worker_task.done():
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
                self._worker_task = None
            logger.info("Task Queue Service stopped cleanly.")

    async def recover_stale_tasks(self) -> int:
        """
        Scan database on startup for tasks left in 'PROCESSING' or 'PENDING' status
        from a previous process crash/restart, mark them as FAILED, and log recovery.

        Returns:
            int: Number of stale tasks recovered.
        """
        logger.info("Checking database for stale tasks from previous runs...")
        db = get_db()
        stale_count = 0
        try:
            async with db.get_connection() as conn:
                async with conn.execute(
                    "SELECT task_id, user_id, task_type FROM tasks WHERE status IN ('processing', 'pending')"
                ) as cursor:
                    rows = await cursor.fetchall()
                    for row in rows:
                        t_id = row["task_id"]
                        logger.warning(f"Recovered stale task {t_id} ({row['task_type']}) for user {row['user_id']}. Marking as FAILED.")
                        await conn.execute(
                            "UPDATE tasks SET status = 'failed', error_message = 'Task aborted due to system restart.', updated_at = datetime('now') WHERE task_id = ?",
                            (t_id,)
                        )
                        stale_count += 1
                await conn.commit()
            logger.info(f"Stale task recovery completed. Recovered {stale_count} orphaned tasks.")
            return stale_count
        except Exception as e:
            logger.error(f"Failed to recover stale tasks: {e}")
            return 0

    async def submit_task(
        self,
        user_id: int,
        task_type: str,
        coro_fn: Callable[..., Any],
        *args: Any,
        payload: Optional[Dict[str, Any]] = None,
        associated_files: Optional[List[Path]] = None,
        **kwargs: Any
    ) -> QueueTask:
        """
        Submit a new background task to the queue.

        Args:
            user_id: Requesting user Telegram ID.
            task_type: Functional type string ('download', 'convert', etc.).
            coro_fn: Async coroutine function to execute.
            payload: Optional dict of parameters.
            associated_files: List of file Paths involved in task (to protect from cleanup).

        Returns:
            QueueTask: Created task object with task_id.

        Raises:
            QueueOverflowError: If global queue capacity is exceeded.
            UserTaskLimitError: If user active/queued task limits are breached.
        """
        if not self._accepting_tasks:
            raise QueueOverflowError("Queue is currently shutting down and not accepting new tasks.")

        async with self._lock:
            # Check global capacity limit
            total_tasks = len(self._pending_queue) + len(self._active_tasks)
            if total_tasks >= self.max_queue_size:
                raise QueueOverflowError(f"Global queue is full ({total_tasks}/{self.max_queue_size}). Please try again later.")

            # Check user per-user active limits
            user_active_count = sum(1 for t in self._active_tasks.values() if t.user_id == user_id)
            user_pending_count = sum(1 for t in self._pending_queue if t.user_id == user_id)

            if user_active_count + user_pending_count >= self.max_user_queue:
                raise UserTaskLimitError(f"You have reached your limit of {self.max_user_queue} concurrent/queued tasks.")

            # Generate task ID and QueueTask instance
            task_id = str(uuid.uuid4())
            file_paths = set(associated_files or [])
            
            queue_task = QueueTask(
                task_id=task_id,
                user_id=user_id,
                task_type=task_type,
                coro_fn=coro_fn,
                args=args,
                kwargs=kwargs,
                payload=payload,
                status=TaskStatus.PENDING,
                file_paths=file_paths,
                future=asyncio.get_running_loop().create_future()
            )

            # Persist task in Database (ensure user exists first to satisfy FK constraint)
            db = get_db()
            existing_user = await db.get_user(user_id)
            if not existing_user:
                await db.upsert_user(User(user_id=user_id, username=f"user_{user_id}"))

            db_task = Task(
                task_id=task_id,
                user_id=user_id,
                task_type=task_type,
                status=TaskStatus.PENDING,
                payload=json.dumps(payload) if payload else None
            )
            await db.create_task(db_task)

            # Enqueue task
            self._pending_queue.append(queue_task)
            pos = len(self._pending_queue)
            logger.info(f"Task {task_id} ({task_type}) enqueued for user {user_id}. Queue position: #{pos}")

        return queue_task

    async def cancel_task(self, task_id: str, user_id: int) -> bool:
        """
        Cancel a pending or currently running task and immediately purge its temporary files.

        Args:
            task_id: Task UUID.
            user_id: Requesting user ID (must match task owner).

        Returns:
            bool: True if task was successfully cancelled.
        """
        from productivity_hub.services.cleanup_service import safe_delete_files

        async with self._lock:
            # 1. Check pending queue
            for idx, task in enumerate(self._pending_queue):
                if task.task_id == task_id and task.user_id == user_id:
                    self._pending_queue.pop(idx)
                    task.status = TaskStatus.CANCELLED
                    if task.future and not task.future.done():
                        task.future.cancel()

                    # Purge associated temporary files immediately upon cancellation
                    safe_delete_files(task.file_paths, exclude_task_id=task_id, log_msg=f"cancelled pending task {task_id[:8]}")

                    db = get_db()
                    await db.update_task_status(task_id, TaskStatus.CANCELLED, error_message="Cancelled by user.")
                    logger.info(f"Pending task {task_id} cancelled by user {user_id}.")
                    return True

            # 2. Check currently running tasks
            if task_id in self._running_tasks:
                q_task = self._active_tasks.get(task_id)
                if q_task and q_task.user_id == user_id:
                    runner = self._running_tasks[task_id]
                    runner.cancel()
                    q_task.status = TaskStatus.CANCELLED
                    if q_task.future and not q_task.future.done():
                        q_task.future.cancel()

                    safe_delete_files(q_task.file_paths, exclude_task_id=task_id, log_msg=f"cancelled active task {task_id[:8]}")

                    db = get_db()
                    await db.update_task_status(task_id, TaskStatus.CANCELLED, error_message="Cancelled by user while executing.")
                    logger.info(f"Running task {task_id} cancelled by user {user_id}.")
                    return True

        return False

    def get_queue_position(self, task_id: str) -> Optional[int]:
        """
        Get the current 1-indexed queue position of a pending task.

        Args:
            task_id: Task UUID.

        Returns:
            Optional[int]: Position number (1 = next up), or None if task is active/completed.
        """
        for idx, task in enumerate(self._pending_queue):
            if task.task_id == task_id:
                return idx + 1
        return None

    def get_active_file_paths(self, exclude_task_id: Optional[str] = None) -> Set[Path]:
        """
        Retrieve set of all file paths referenced by pending or active tasks.
        Used by CleanupService to guarantee active files are never prematurely deleted.

        Args:
            exclude_task_id: Optional task ID to exclude from query (allowing a task to clean its own files).
        """
        active_paths: Set[Path] = set()

        for t in self._pending_queue:
            if exclude_task_id and t.task_id == exclude_task_id:
                continue
            for p in t.file_paths:
                try:
                    active_paths.add(p.resolve())
                except Exception:
                    pass

        for t in self._active_tasks.values():
            if exclude_task_id and t.task_id == exclude_task_id:
                continue
            for p in t.file_paths:
                try:
                    active_paths.add(p.resolve())
                except Exception:
                    pass

        return active_paths

    def register_task_files(self, task_id: str, *paths: Optional[Path]) -> None:
        """
        Dynamically associate newly created or downloaded file paths with a task,
        ensuring they are tracked, protected from periodic sweeps, and cleaned up if the task fails.
        """
        valid_paths = [p for p in paths if p is not None]
        if not valid_paths:
            return

        task = self._active_tasks.get(task_id)
        if task:
            for p in valid_paths:
                task.file_paths.add(p)
            return

        for t in self._pending_queue:
            if t.task_id == task_id:
                for p in valid_paths:
                    t.file_paths.add(p)
                return

    async def _queue_worker_loop(self) -> None:
        """Background loop pulling tasks from pending queue and dispatching workers."""
        logger.info("Queue worker loop operational.")
        while self._accepting_tasks:
            try:
                await asyncio.sleep(0.2)
                
                if not self._pending_queue:
                    continue

                # Acquire concurrency semaphore slot
                await self._semaphore.acquire()

                async with self._lock:
                    if not self._pending_queue:
                        self._semaphore.release()
                        continue
                    task = self._pending_queue.pop(0)
                    self._active_tasks[task.task_id] = task

                # Spawn task execution wrapper
                worker_coro = self._execute_task_wrapper(task)
                run_task = asyncio.create_task(worker_coro, name=f"TaskWorker-{task.task_id[:8]}")
                self._running_tasks[task.task_id] = run_task

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in queue worker loop: {e}", exc_info=True)

    async def _execute_task_wrapper(self, task: QueueTask) -> None:
        """Execute a single task with database state tracking and error handling."""
        from productivity_hub.services.cleanup_service import safe_delete_files

        db = get_db()
        task_id = task.task_id
        try:
            task.status = TaskStatus.PROCESSING
            await db.update_task_status(task_id, TaskStatus.PROCESSING)
            logger.info(f"Executing task {task_id} ({task.task_type}) for user {task.user_id}...")

            # Execute user coroutine
            result = await task.coro_fn(*task.args, **task.kwargs)

            task.status = TaskStatus.COMPLETED
            res_json = json.dumps(result, default=str) if isinstance(result, (dict, list)) else str(result) if result else None
            await db.update_task_status(task_id, TaskStatus.COMPLETED, result_data=res_json)
            
            if task.future and not task.future.done():
                task.future.set_result(result)
            logger.info(f"Task {task_id} completed successfully.")

        except asyncio.CancelledError:
            task.status = TaskStatus.CANCELLED
            await db.update_task_status(task_id, TaskStatus.CANCELLED, error_message="Task cancelled during execution.")
            logger.warning(f"Task {task_id} cancelled during execution.")
            # Immediate file cleanup on cancellation
            safe_delete_files(task.file_paths, exclude_task_id=task_id, log_msg=f"cancelled task {task_id[:8]}")

        except Exception as err:
            task.status = TaskStatus.FAILED
            err_msg = str(err) or "Unknown task execution error."
            await db.update_task_status(task_id, TaskStatus.FAILED, error_message=err_msg)
            if task.future and not task.future.done():
                task.future.set_exception(err)
            logger.error(f"Task {task_id} failed: {err_msg}", exc_info=True)
            # Immediate file cleanup on failure
            safe_delete_files(task.file_paths, exclude_task_id=task_id, log_msg=f"failed task {task_id[:8]}")

        finally:
            async with self._lock:
                self._active_tasks.pop(task_id, None)
                self._running_tasks.pop(task_id, None)
                self._semaphore.release()


# Global Queue Service instance
_queue_service_instance: Optional[TaskQueueService] = None


async def init_queue_service(settings: Optional[Settings] = None) -> TaskQueueService:
    """Initialize and start global TaskQueueService instance."""
    global _queue_service_instance
    _queue_service_instance = TaskQueueService(settings)
    await _queue_service_instance.start()
    return _queue_service_instance


def get_queue_service() -> TaskQueueService:
    """Retrieve global TaskQueueService singleton."""
    global _queue_service_instance
    if _queue_service_instance is None:
        raise RuntimeError("TaskQueueService has not been initialized. Call init_queue_service() first.")
    return _queue_service_instance
