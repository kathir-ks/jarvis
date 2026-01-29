"""Celery task executors with MongoDB persistence and callbacks."""
import asyncio
import json
import logging
from typing import Any

from ..db.mongo import get_mongo_db
from ..db.redis_client import get_redis_client
from ..runtime.task import Task, TaskType
from .celery_app import celery_app

logger = logging.getLogger(__name__)


async def submit_task_to_celery(task: Task) -> dict[str, Any]:
    """Submit task to appropriate Celery executor based on task type."""
    task_map = {
        TaskType.RESEARCH: execute_research_task,
        TaskType.EXPLORATION: execute_exploration_task,
        TaskType.PURCHASE: execute_purchase_task,
        TaskType.BOOKING: execute_booking_task,
        TaskType.CUSTOM: execute_custom_task,
    }
    
    executor = task_map.get(task.task_type)
    if not executor:
        raise ValueError(f"No executor for task type {task.task_type}")
    
    # Submit to Celery asynchronously
    result = executor.apply_async(
        args=[task.task_id, task.task_params],
        soft_time_limit=task.max_duration,
        time_limit=task.max_duration + 30,
    )
    
    # For async submission, we return immediately
    # Actual result will be retrieved by task status polling or callback
    return {"celery_task_id": result.id, "status": "SUBMITTED"}


@celery_app.task(bind=True, name="jarvis.tasks.research")
def execute_research_task(self, task_id: str, params: dict) -> dict[str, Any]:
    """Execute research task with web search and summarization."""
    logger.info(f"Executing research task {task_id} with params {params}")
    
    try:
        # Check for cancellation
        db = get_mongo_db()
        task_doc = db["tasks"].find_one({"_id": task_id})
        if task_doc and task_doc.get("status") == "CANCELLED_REQUESTED":
            logger.info(f"Task {task_id} cancelled")
            return {"status": "CANCELLED", "task_id": task_id}
        
        # TODO: Implement actual web search + LLM summarization
        # Placeholder logic
        query = params.get("query", "")
        
        result = {
            "task_id": task_id,
            "status": "COMPLETED",
            "result": {
                "query": query,
                "summary": f"Research summary for: {query}",
                "sources": ["https://example.com"],
                "findings": ["Sample finding 1", "Sample finding 2"]
            }
        }
        
        # Persist result to MongoDB
        _persist_task_result(task_id, result)
        
        # Trigger callback
        _trigger_callback(task_id, "on_complete", result)
        
        return result
        
    except Exception as e:
        logger.error(f"Research task {task_id} failed: {e}", exc_info=True)
        error_result = {"task_id": task_id, "status": "FAILED", "error": str(e)}
        _persist_task_result(task_id, error_result)
        _trigger_callback(task_id, "on_failure", error_result)
        raise


@celery_app.task(bind=True, name="jarvis.tasks.exploration")
def execute_exploration_task(self, task_id: str, params: dict) -> dict[str, Any]:
    """Execute exploration task with browser automation."""
    logger.info(f"Executing exploration task {task_id}")
    
    try:
        # Check cancellation
        db = get_mongo_db()
        task_doc = db["tasks"].find_one({"_id": task_id})
        if task_doc and task_doc.get("status") == "CANCELLED_REQUESTED":
            return {"status": "CANCELLED", "task_id": task_id}
        
        # TODO: Implement Playwright browsing and content extraction
        url = params.get("url", "")
        
        result = {
            "task_id": task_id,
            "status": "COMPLETED",
            "result": {
                "url": url,
                "discoveries": [
                    {"type": "product", "title": "Sample Product", "price": "$99"},
                    {"type": "article", "title": "Sample Article"}
                ],
                "entities_extracted": 2
            }
        }
        
        _persist_task_result(task_id, result)
        _trigger_callback(task_id, "on_complete", result)
        
        return result
        
    except Exception as e:
        logger.error(f"Exploration task {task_id} failed: {e}", exc_info=True)
        error_result = {"task_id": task_id, "status": "FAILED", "error": str(e)}
        _persist_task_result(task_id, error_result)
        _trigger_callback(task_id, "on_failure", error_result)
        raise


@celery_app.task(bind=True, name="jarvis.tasks.purchase")
def execute_purchase_task(self, task_id: str, params: dict) -> dict[str, Any]:
    """Execute purchase task (requires user approval)."""
    logger.info(f"Executing purchase task {task_id} - approval required")
    
    # Purchase tasks must wait for approval
    result = {
        "task_id": task_id,
        "status": "WAITING_APPROVAL",
        "result": {
            "action": "purchase",
            "item": params.get("item"),
            "price": params.get("price"),
            "message": "Awaiting user approval for purchase"
        }
    }
    
    _persist_task_result(task_id, result)
    return result


@celery_app.task(bind=True, name="jarvis.tasks.booking")
def execute_booking_task(self, task_id: str, params: dict) -> dict[str, Any]:
    """Execute booking task (requires user approval)."""
    logger.info(f"Executing booking task {task_id} - approval required")
    
    result = {
        "task_id": task_id,
        "status": "WAITING_APPROVAL",
        "result": {
            "action": "booking",
            "details": params,
            "message": "Awaiting user approval for booking"
        }
    }
    
    _persist_task_result(task_id, result)
    return result


@celery_app.task(bind=True, name="jarvis.tasks.custom")
def execute_custom_task(self, task_id: str, params: dict) -> dict[str, Any]:
    """Execute custom task based on parameters."""
    logger.info(f"Executing custom task {task_id}")
    
    try:
        # Generic task execution
        result = {
            "task_id": task_id,
            "status": "COMPLETED",
            "result": {"message": "Custom task completed", "params": params}
        }
        
        _persist_task_result(task_id, result)
        _trigger_callback(task_id, "on_complete", result)
        
        return result
        
    except Exception as e:
        logger.error(f"Custom task {task_id} failed: {e}")
        error_result = {"task_id": task_id, "status": "FAILED", "error": str(e)}
        _persist_task_result(task_id, error_result)
        _trigger_callback(task_id, "on_failure", error_result)
        raise


def _persist_task_result(task_id: str, result: dict[str, Any]) -> None:
    """Persist task result to MongoDB."""
    try:
        db = get_mongo_db()
        db["tasks"].update_one(
            {"_id": task_id},
            {"$set": {"result": result.get("result"), "error": result.get("error")}}
        )
    except Exception as e:
        logger.error(f"Failed to persist result for task {task_id}: {e}")


def _trigger_callback(task_id: str, callback_type: str, data: dict[str, Any]) -> None:
    """Trigger callback by publishing to agent inbox."""
    try:
        db = get_mongo_db()
        task_doc = db["tasks"].find_one({"_id": task_id})
        
        if not task_doc:
            return
        
        callback_channel = task_doc.get(callback_type)
        if not callback_channel:
            return
        
        # Publish callback event to agent inbox
        agent_id = task_doc.get("agent_id")
        if agent_id:
            redis_client = get_redis_client()
            message = {"type": "task_callback", "task_id": task_id, "data": data}

            async def _publish():
                await redis_client.publish(f"agent:{agent_id}:inbox", json.dumps(message))

            asyncio.run(_publish())
            logger.info("Triggered %s callback for task %s", callback_type, task_id)
            
    except Exception as e:
        logger.error(f"Failed to trigger callback for task {task_id}: {e}")
