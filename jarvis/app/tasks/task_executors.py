"""Celery task executors with real tool integration and MongoDB persistence."""
from __future__ import annotations

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

    result = executor.apply_async(
        args=[task.task_id, task.task_params],
        soft_time_limit=task.max_duration,
        time_limit=task.max_duration + 30,
    )

    return {"celery_task_id": result.id, "status": "SUBMITTED"}


def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    return asyncio.run(coro)


@celery_app.task(bind=True, name="jarvis.tasks.research")
def execute_research_task(self, task_id: str, params: dict) -> dict[str, Any]:
    """Execute a research task: web search + URL reading."""
    logger.info("Executing research task %s with params %s", task_id, params)

    try:
        if _is_cancelled(task_id):
            return {"status": "CANCELLED", "task_id": task_id}

        query = params.get("query", "")
        num_results = params.get("num_results", 5)

        from ..llm.tools.web_tools import web_search_handler, read_url_handler

        search_results = _run_async(
            web_search_handler({"query": query, "num_results": num_results})
        )

        sources: list[dict[str, str]] = []
        for item in search_results[:3]:
            url = item.get("url", "")
            if not url:
                continue
            try:
                page = _run_async(
                    read_url_handler({"url": url, "max_length": 3000})
                )
                sources.append({
                    "title": item.get("title", ""),
                    "url": url,
                    "snippet": item.get("snippet", ""),
                    "content": page.get("content", "")[:2000],
                })
            except Exception as e:
                logger.warning("Failed to read %s: %s", url, e)
                sources.append({
                    "title": item.get("title", ""),
                    "url": url,
                    "snippet": item.get("snippet", ""),
                    "content": "",
                })

        findings = [
            s["snippet"] or s["content"][:200] for s in sources if s.get("snippet") or s.get("content")
        ]

        result = {
            "task_id": task_id,
            "status": "COMPLETED",
            "result": {
                "query": query,
                "summary": f"Research results for: {query}",
                "sources": [{"title": s["title"], "url": s["url"]} for s in sources],
                "findings": findings,
                "raw_results": search_results,
            },
        }

        _persist_task_result(task_id, result)
        _trigger_callback(task_id, "on_complete", result)
        return result

    except Exception as e:
        logger.error("Research task %s failed: %s", task_id, e, exc_info=True)
        error_result = {"task_id": task_id, "status": "FAILED", "error": str(e)}
        _persist_task_result(task_id, error_result)
        _trigger_callback(task_id, "on_failure", error_result)
        raise


@celery_app.task(bind=True, name="jarvis.tasks.exploration")
def execute_exploration_task(self, task_id: str, params: dict) -> dict[str, Any]:
    """Execute an exploration task: fetch URLs and extract content."""
    logger.info("Executing exploration task %s", task_id)

    try:
        if _is_cancelled(task_id):
            return {"status": "CANCELLED", "task_id": task_id}

        from ..llm.tools.web_tools import read_url_handler

        url = params.get("url", "")
        urls = params.get("urls", [url] if url else [])

        discoveries: list[dict[str, Any]] = []
        for target_url in urls:
            if not target_url:
                continue
            try:
                page = _run_async(
                    read_url_handler({"url": target_url, "max_length": 5000})
                )
                discoveries.append({
                    "url": target_url,
                    "title": page.get("title", ""),
                    "content_length": len(page.get("content", "")),
                    "content_preview": page.get("content", "")[:500],
                })
            except Exception as e:
                logger.warning("Failed to explore %s: %s", target_url, e)
                discoveries.append({"url": target_url, "error": str(e)})

        result = {
            "task_id": task_id,
            "status": "COMPLETED",
            "result": {
                "urls_explored": len(urls),
                "discoveries": discoveries,
                "entities_extracted": len(discoveries),
            },
        }

        _persist_task_result(task_id, result)
        _trigger_callback(task_id, "on_complete", result)
        return result

    except Exception as e:
        logger.error("Exploration task %s failed: %s", task_id, e, exc_info=True)
        error_result = {"task_id": task_id, "status": "FAILED", "error": str(e)}
        _persist_task_result(task_id, error_result)
        _trigger_callback(task_id, "on_failure", error_result)
        raise


@celery_app.task(bind=True, name="jarvis.tasks.purchase")
def execute_purchase_task(self, task_id: str, params: dict) -> dict[str, Any]:
    """Execute purchase task (requires user approval)."""
    logger.info("Executing purchase task %s — approval required", task_id)
    result = {
        "task_id": task_id,
        "status": "WAITING_APPROVAL",
        "result": {
            "action": "purchase",
            "item": params.get("item"),
            "price": params.get("price"),
            "message": "Awaiting user approval for purchase",
        },
    }
    _persist_task_result(task_id, result)
    return result


@celery_app.task(bind=True, name="jarvis.tasks.booking")
def execute_booking_task(self, task_id: str, params: dict) -> dict[str, Any]:
    """Execute booking task (requires user approval)."""
    logger.info("Executing booking task %s — approval required", task_id)
    result = {
        "task_id": task_id,
        "status": "WAITING_APPROVAL",
        "result": {
            "action": "booking",
            "details": params,
            "message": "Awaiting user approval for booking",
        },
    }
    _persist_task_result(task_id, result)
    return result


@celery_app.task(bind=True, name="jarvis.tasks.custom")
def execute_custom_task(self, task_id: str, params: dict) -> dict[str, Any]:
    """Execute a custom task — dispatches based on params."""
    logger.info("Executing custom task %s", task_id)

    try:
        if _is_cancelled(task_id):
            return {"status": "CANCELLED", "task_id": task_id}

        action = params.get("action", "")
        task_result: dict[str, Any] = {}

        if action == "execute_code" or "code" in params:
            from ..llm.tools.core_tools import execute_code_handler
            task_result = _run_async(
                execute_code_handler({"code": params.get("code", ""), "timeout": params.get("timeout", 10)})
            )
        elif action == "web_search" or "query" in params:
            from ..llm.tools.web_tools import web_search_handler
            task_result = _run_async(
                web_search_handler({"query": params.get("query", ""), "num_results": params.get("num_results", 5)})
            )
        elif action == "read_url" or "url" in params:
            from ..llm.tools.web_tools import read_url_handler
            task_result = _run_async(
                read_url_handler({"url": params.get("url", ""), "max_length": params.get("max_length", 5000)})
            )
        elif action == "calculator" or "expression" in params:
            from ..llm.tools.core_tools import calculator_handler
            task_result = _run_async(
                calculator_handler({"expression": params.get("expression", "")})
            )
        else:
            task_result = {"message": "Custom task completed", "params": params}

        result = {"task_id": task_id, "status": "COMPLETED", "result": task_result}
        _persist_task_result(task_id, result)
        _trigger_callback(task_id, "on_complete", result)
        return result

    except Exception as e:
        logger.error("Custom task %s failed: %s", task_id, e)
        error_result = {"task_id": task_id, "status": "FAILED", "error": str(e)}
        _persist_task_result(task_id, error_result)
        _trigger_callback(task_id, "on_failure", error_result)
        raise


def _is_cancelled(task_id: str) -> bool:
    try:
        db = get_mongo_db()
        task_doc = db["tasks"].find_one({"_id": task_id})
        if task_doc and task_doc.get("status") == "CANCELLED_REQUESTED":
            return True
    except Exception as e:
        logger.warning("Failed to check cancellation for task %s: %s", task_id, e)
    return False


def _persist_task_result(task_id: str, result: dict[str, Any]) -> None:
    try:
        db = get_mongo_db()
        db["tasks"].update_one(
            {"_id": task_id},
            {"$set": {"result": result.get("result"), "error": result.get("error")}},
        )
    except Exception as e:
        logger.error("Failed to persist result for task %s: %s", task_id, e)


def _trigger_callback(task_id: str, callback_type: str, data: dict[str, Any]) -> None:
    """Trigger callback by publishing to the agent's Redis Stream inbox."""
    try:
        db = get_mongo_db()
        task_doc = db["tasks"].find_one({"_id": task_id})
        if not task_doc:
            return

        callback_channel = task_doc.get(callback_type)
        if not callback_channel:
            return

        agent_id = task_doc.get("agent_id")
        if agent_id:
            redis_client = get_redis_client()
            stream_key = f"agent:{agent_id}:inbox"
            payload = json.dumps({"type": "task_callback", "task_id": task_id, "data": data})

            async def _publish():
                await redis_client.xadd(stream_key, {"payload": payload}, maxlen=10_000, approximate=True)

            asyncio.run(_publish())
            logger.info("Triggered %s callback for task %s", callback_type, task_id)
    except Exception as e:
        logger.error("Failed to trigger callback for task %s: %s", task_id, e)
