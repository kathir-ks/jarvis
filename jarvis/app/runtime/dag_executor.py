"""DAG executor for task dependencies."""
import asyncio
import logging
from collections import defaultdict, deque
from typing import Any, Callable

from .task import Task, TaskStatus

logger = logging.getLogger(__name__)


class DAGExecutor:
    """Executes tasks based on dependency graph using topological sort."""

    def __init__(self, tasks: list[Task], max_concurrent: int = 5):
        self.tasks = tasks
        self.max_concurrent = max_concurrent
        self.task_map = {task.task_id: task for task in tasks}
        self.results: dict[str, Any] = {}

    def _build_graph(self) -> tuple[dict[str, list[str]], dict[str, int]]:
        """Build adjacency list and in-degree map."""
        graph: dict[str, list[str]] = defaultdict(list)
        in_degree: dict[str, int] = defaultdict(int)
        
        for task in self.tasks:
            if task.task_id not in in_degree:
                in_degree[task.task_id] = 0
            
            for dep_id in task.depends_on:
                if dep_id in self.task_map:
                    graph[dep_id].append(task.task_id)
                    in_degree[task.task_id] += 1
        
        return graph, in_degree

    async def execute(self, executor_fn: Callable[[Task], Any]) -> dict[str, Any]:
        """
        Execute tasks respecting dependencies with concurrency control.
        
        Args:
            executor_fn: Async function that executes a task and returns result
        
        Returns:
            Dictionary mapping task_id to execution result
        """
        graph, in_degree = self._build_graph()
        
        # Find tasks with no dependencies
        ready_queue = deque([
            task_id for task_id in self.task_map.keys()
            if in_degree[task_id] == 0
        ])
        
        completed = set()
        active_tasks: set[asyncio.Task] = set()
        
        while ready_queue or active_tasks:
            # Launch ready tasks up to concurrency limit
            while ready_queue and len(active_tasks) < self.max_concurrent:
                task_id = ready_queue.popleft()
                task = self.task_map[task_id]
                
                # Skip if cancelled
                if task.should_cancel():
                    logger.info(f"Skipping cancelled task {task_id}")
                    completed.add(task_id)
                    self._mark_descendants_cancelled(task_id, graph, completed)
                    continue
                
                # Launch task execution
                coro = self._execute_task(task, executor_fn)
                active_tasks.add(asyncio.create_task(coro))
            
            if not active_tasks:
                break
            
            # Wait for at least one task to complete
            done, active_tasks = await asyncio.wait(
                active_tasks,
                return_when=asyncio.FIRST_COMPLETED
            )
            
            # Process completed tasks
            for task_future in done:
                task_id, result, success = await task_future
                completed.add(task_id)
                self.results[task_id] = result
                
                if not success:
                    # Mark downstream tasks as cancelled on failure
                    self._mark_descendants_cancelled(task_id, graph, completed)
                    continue
                
                # Enqueue dependent tasks that are now ready
                for dependent_id in graph.get(task_id, []):
                    in_degree[dependent_id] -= 1
                    if in_degree[dependent_id] == 0 and dependent_id not in completed:
                        ready_queue.append(dependent_id)
        
        return self.results

    async def _execute_task(
        self,
        task: Task,
        executor_fn: Callable[[Task], Any]
    ) -> tuple[str, Any, bool]:
        """Execute single task and return (task_id, result, success)."""
        try:
            logger.info(f"Executing task {task.task_id} (priority {task.priority})")
            result = await executor_fn(task)
            return (task.task_id, result, True)
        except Exception as e:
            logger.error(f"Task {task.task_id} failed: {e}")
            return (task.task_id, {"error": str(e)}, False)

    def _mark_descendants_cancelled(
        self,
        task_id: str,
        graph: dict[str, list[str]],
        completed: set[str]
    ) -> None:
        """Mark all downstream tasks as cancelled."""
        queue = deque([task_id])
        
        while queue:
            current = queue.popleft()
            for dependent_id in graph.get(current, []):
                if dependent_id not in completed:
                    completed.add(dependent_id)
                    self.results[dependent_id] = {"status": "CANCELLED", "reason": "upstream_failure"}
                    queue.append(dependent_id)
