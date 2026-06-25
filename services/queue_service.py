import asyncio
from collections import deque
import uuid
import time
from telegram import Bot
from config.settings import MAX_PROCESSING_TIME
from services.database_service import log_event
from utils.logger import logger

class QueueTask:
    def __init__(self, user_id: int, task_func, bot: Bot, chat_id: int, description: str, args, kwargs):
        self.task_id = str(uuid.uuid4())
        self.user_id = user_id
        self.task_func = task_func
        self.bot = bot
        self.chat_id = chat_id
        self.description = description
        self.args = args
        self.kwargs = kwargs
        
        self.status = "PENDING"  # PENDING, PROCESSING, COMPLETED, FAILED, CANCELLED
        self.asyncio_task = None  # Reference to the running asyncio.Task
        self.future = asyncio.Future()
        self.created_at = time.time()

# States
_pending_queue = deque()
_active_tasks = []
_user_cooldowns = {}  # user_id -> float timestamp of last request

_completed_tasks_count = 0
_failed_tasks_count = 0
_total_processing_time = 0.0

def get_queue_stats() -> dict:
    return {
        "active": len(_active_tasks),
        "pending": len(_pending_queue),
        "total": len(_active_tasks) + len(_pending_queue)
    }

def get_monitoring_stats() -> dict:
    """Return live system resource and queue metrics."""
    cpu = 0.0
    ram = 0.0
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
    except Exception:
        pass
        
    stats = get_queue_stats()
    avg_processing = 0.0
    if _completed_tasks_count > 0:
        avg_processing = _total_processing_time / _completed_tasks_count
        
    return {
        "cpu_usage": cpu,
        "ram_usage": ram,
        "active_tasks": stats["active"],
        "pending_tasks": stats["pending"],
        "failed_tasks": _failed_tasks_count,
        "completed_tasks": _completed_tasks_count,
        "avg_processing_time": avg_processing
    }

async def enqueue_task(user_id: int, bot: Bot, chat_id: int, description: str, task_func, *args, **kwargs) -> tuple:
    """Enqueues a task, checking limits and cooldowns.
    Returns (task, queue_position, estimated_wait_minutes)
    If it starts immediately, queue_position is 0.
    Raises ValueError if limits or cooldowns are breached.
    """
    now = time.time()
    
    # 1. Cooldown Check (10 seconds)
    last_time = _user_cooldowns.get(user_id, 0.0)
    if now - last_time < 10.0:
        raise ValueError("❌ Please wait before creating another task.")
        
    # 2. Max Active Check (1 task per user)
    if any(t.user_id == user_id for t in _active_tasks):
        raise ValueError("❌ Please wait before creating another task.")
        
    # 3. Max User Queue Entries Check (3 tasks)
    user_queue_count = sum(1 for t in _pending_queue if t.user_id == user_id)
    if user_queue_count >= 3:
        raise ValueError("❌ Please wait before creating another task.")
        
    # 4. Global Queue Limit Check (50 entries)
    if len(_pending_queue) >= 50:
        raise ValueError("❌ System queue is full. Please try again later.")
        
    # Record request timestamp
    _user_cooldowns[user_id] = now
    
    task = QueueTask(user_id, task_func, bot, chat_id, description, args, kwargs)
    
    # Run immediately if slot is free and queue is empty
    if len(_active_tasks) < 2 and not _pending_queue:
        _active_tasks.append(task)
        asyncio.create_task(_run_task_execution(task))
        return task, 0, 0
    else:
        # Put in queue
        task.status = "PENDING"
        _pending_queue.append(task)
        position = len(_pending_queue)
        wait_time = max(1, round(position * 0.6))
        
        logger.info(f"Task {task.task_id} enqueued. User: {user_id}. Position: #{position}")
        log_event("QUEUE", f"User {user_id} task enqueued. Position: #{position}")
        return task, position, wait_time

async def _run_task_execution(task: QueueTask):
    global _completed_tasks_count, _total_processing_time, _failed_tasks_count
    task.status = "PROCESSING"
    logger.info(f"Executing task {task.task_id} for user {task.user_id}")
    log_event("QUEUE", f"Task {task.task_id} started processing.")
    
    # Create the task wrapper so it is cancellable
    async def task_wrapper():
        return await task.task_func(*task.args, **task.kwargs)
        
    task.asyncio_task = asyncio.create_task(task_wrapper())
    start_time = time.time()
    
    try:
        # Enforce max processing timeout (10 minutes)
        result = await asyncio.wait_for(task.asyncio_task, timeout=MAX_PROCESSING_TIME)
        task.status = "COMPLETED"
        task.future.set_result(result)
        log_event("QUEUE", f"Task {task.task_id} completed successfully.")
        
        # Track statistics
        duration = time.time() - start_time
        _completed_tasks_count += 1
        _total_processing_time += duration
        
    except asyncio.CancelledError:
        task.status = "CANCELLED"
        # Make sure future is resolved with exception so awaiters receive it
        if not task.future.done():
            task.future.set_exception(asyncio.CancelledError())
        logger.warning(f"Task {task.task_id} was cancelled by user.")
        log_event("QUEUE", f"Task {task.task_id} cancelled.")
    except asyncio.TimeoutError:
        task.status = "FAILED"
        task.future.set_exception(TimeoutError("Processing time exceeded the 10 minute limit."))
        logger.error(f"Task {task.task_id} timed out.")
        log_event("ERROR", f"Task {task.task_id} timed out.")
        _failed_tasks_count += 1
    except Exception as e:
        task.status = "FAILED"
        task.future.set_exception(e)
        logger.error(f"Task {task.task_id} failed: {e}")
        log_event("ERROR", f"Task {task.task_id} failed: {e}")
        _failed_tasks_count += 1
    finally:
        task.asyncio_task = None
        if task in _active_tasks:
            _active_tasks.remove(task)
        _process_next_task()

def _process_next_task():
    if len(_active_tasks) < 2 and _pending_queue:
        next_task = _pending_queue.popleft()
        _active_tasks.append(next_task)
        asyncio.create_task(_notify_and_run(next_task))

async def _notify_and_run(task: QueueTask):
    try:
        await task.bot.send_message(
            chat_id=task.chat_id,
            text=f"⚡ **Queue Update**\nYour task is now starting: *{task.description}*",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.warning(f"Failed to notify user {task.user_id}: {e}")
    await _run_task_execution(task)

def cancel_user_task(user_id: int) -> bool:
    """Finds and cancels any active or queued task for the given user.
    Returns True if a task was found and cancelled, False otherwise.
    """
    # 1. Search active tasks
    for task in _active_tasks:
        if task.user_id == user_id:
            logger.info(f"Cancelling active task {task.task_id} for user {user_id}")
            task.status = "CANCELLED"
            if task.asyncio_task:
                task.asyncio_task.cancel()
            return True
            
    # 2. Search pending queue
    for task in list(_pending_queue):
        if task.user_id == user_id:
            logger.info(f"Removing queued task {task.task_id} for user {user_id}")
            task.status = "CANCELLED"
            task.future.set_exception(asyncio.CancelledError())
            _pending_queue.remove(task)
            return True
            
    return False
