"""
Task Complexity Analyzer

Analyzes task complexity to determine delegation strategy.
Prepares for Phase 4 multi-agent collaboration.
"""
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class TaskComplexityAnalyzer:
    """
    Analyzes task complexity using heuristics.

    Helps master agents decide whether to:
    - Execute tasks directly
    - Delegate to specialized sub-agents
    - Break into subtasks
    """

    # Keywords indicating different task types
    MULTI_STEP_KEYWORDS = [
        "first", "then", "after", "next", "finally",
        "step by step", "in order", "sequentially",
        "and then", "followed by", "multiple", "several",
    ]

    WEB_KEYWORDS = [
        "search", "google", "web", "online", "internet",
        "url", "website", "browse", "find information",
        "look up", "research", "investigate",
    ]

    CODE_KEYWORDS = [
        "code", "python", "execute", "run", "script",
        "program", "function", "implement", "algorithm",
        "calculate", "compute", "fibonacci", "sort",
    ]

    TIME_KEYWORDS = [
        "time", "date", "clock", "schedule", "deadline",
        "reminder", "timer", "alarm", "when", "until",
        "before", "after", "tomorrow", "yesterday",
    ]

    DATA_KEYWORDS = [
        "data", "analyze", "statistics", "chart", "graph",
        "visualization", "report", "summary", "aggregate",
        "average", "mean", "median", "count",
    ]

    PLANNING_KEYWORDS = [
        "plan", "strategy", "approach", "design", "architecture",
        "organize", "coordinate", "workflow", "process",
    ]

    def analyze_task_complexity(
        self,
        task_description: str,
    ) -> dict[str, Any]:
        """
        Analyze task complexity and suggest execution strategy.

        Args:
            task_description: The task description text

        Returns:
            Dict containing:
                - complexity_score: int (0-10)
                - should_delegate: bool
                - suggested_sub_agents: list[str]
                - estimated_subtasks: int
                - indicators: dict of detected patterns
                - reasoning: str explanation
        """
        description_lower = task_description.lower()

        # Detect indicators
        indicators = {
            "multi_step": self._has_multiple_steps(description_lower),
            "requires_web": self._mentions_web_search(description_lower),
            "requires_code": self._mentions_code_execution(description_lower),
            "time_sensitive": self._is_time_sensitive(description_lower),
            "requires_data_analysis": self._requires_data_analysis(description_lower),
            "requires_planning": self._requires_planning(description_lower),
        }

        # Calculate complexity score (0-10)
        complexity_score = sum([
            indicators["multi_step"] * 3,           # Multi-step adds 3 points
            indicators["requires_web"] * 2,         # Web search adds 2
            indicators["requires_code"] * 2,        # Code execution adds 2
            indicators["time_sensitive"] * 1,       # Time-sensitive adds 1
            indicators["requires_data_analysis"] * 2,  # Data analysis adds 2
            indicators["requires_planning"] * 3,    # Planning adds 3
        ])

        # Cap at 10
        complexity_score = min(complexity_score, 10)

        # Determine if delegation is recommended (score >= 5)
        should_delegate = complexity_score >= 5

        # Suggest sub-agents based on requirements
        suggested_sub_agents = self._suggest_sub_agents(indicators)

        # Estimate number of subtasks
        estimated_subtasks = self._estimate_subtasks(description_lower, indicators)

        # Generate reasoning
        reasoning = self._generate_reasoning(
            complexity_score,
            indicators,
            should_delegate,
        )

        result = {
            "complexity_score": complexity_score,
            "should_delegate": should_delegate,
            "suggested_sub_agents": suggested_sub_agents,
            "estimated_subtasks": estimated_subtasks,
            "indicators": indicators,
            "reasoning": reasoning,
        }

        logger.info(
            f"Task complexity analysis: score={complexity_score}, "
            f"delegate={should_delegate}, subtasks={estimated_subtasks}"
        )

        return result

    def _has_multiple_steps(self, text: str) -> bool:
        """Check if task mentions multiple steps."""
        for keyword in self.MULTI_STEP_KEYWORDS:
            if keyword in text:
                return True

        # Also check for numbered steps (1., 2., etc.)
        if re.search(r'\b\d+\)', text) or re.search(r'\b\d+\.', text):
            return True

        return False

    def _mentions_web_search(self, text: str) -> bool:
        """Check if task requires web search."""
        return any(keyword in text for keyword in self.WEB_KEYWORDS)

    def _mentions_code_execution(self, text: str) -> bool:
        """Check if task requires code execution."""
        return any(keyword in text for keyword in self.CODE_KEYWORDS)

    def _is_time_sensitive(self, text: str) -> bool:
        """Check if task is time-sensitive."""
        return any(keyword in text for keyword in self.TIME_KEYWORDS)

    def _requires_data_analysis(self, text: str) -> bool:
        """Check if task requires data analysis."""
        return any(keyword in text for keyword in self.DATA_KEYWORDS)

    def _requires_planning(self, text: str) -> bool:
        """Check if task requires planning."""
        return any(keyword in text for keyword in self.PLANNING_KEYWORDS)

    def _suggest_sub_agents(
        self,
        indicators: dict[str, bool],
    ) -> list[str]:
        """
        Suggest sub-agent types based on task requirements.

        Args:
            indicators: Dict of detected patterns

        Returns:
            List of suggested sub-agent capability IDs
        """
        suggestions = []

        if indicators.get("requires_web"):
            suggestions.append("web_research")

        if indicators.get("requires_code"):
            suggestions.append("code_execution")

        if indicators.get("time_sensitive"):
            suggestions.append("time_awareness")

        if indicators.get("requires_data_analysis"):
            suggestions.append("code_execution")  # Often requires code
            suggestions.append("calculation")

        if indicators.get("requires_planning"):
            suggestions.append("task_orchestration")

        # Remove duplicates while preserving order
        seen = set()
        unique_suggestions = []
        for item in suggestions:
            if item not in seen:
                seen.add(item)
                unique_suggestions.append(item)

        return unique_suggestions

    def _estimate_subtasks(
        self,
        text: str,
        indicators: dict[str, bool],
    ) -> int:
        """
        Estimate number of subtasks.

        Args:
            text: Task description (lowercase)
            indicators: Detected patterns

        Returns:
            Estimated number of subtasks
        """
        subtask_count = 1  # Default: at least one task

        # Count explicit step numbers
        step_numbers = re.findall(r'\b(\d+)[\.\)]', text)
        if step_numbers:
            subtask_count = max(int(n) for n in step_numbers if int(n) <= 20)

        # Add estimates based on indicators
        if indicators.get("multi_step"):
            subtask_count = max(subtask_count, 3)

        if indicators.get("requires_web") and indicators.get("requires_code"):
            subtask_count = max(subtask_count, 4)  # Research + code typically 4+ steps

        if indicators.get("requires_planning"):
            subtask_count = max(subtask_count, 5)  # Planning suggests complex workflow

        # Count conjunctions that might indicate multiple parts
        conjunction_count = text.count(" and ") + text.count(" then ")
        if conjunction_count > 0:
            subtask_count = max(subtask_count, conjunction_count + 1)

        return min(subtask_count, 20)  # Cap at 20

    def _generate_reasoning(
        self,
        complexity_score: int,
        indicators: dict[str, bool],
        should_delegate: bool,
    ) -> str:
        """
        Generate human-readable reasoning for the analysis.

        Args:
            complexity_score: Calculated complexity score
            indicators: Detected patterns
            should_delegate: Whether delegation is recommended

        Returns:
            Reasoning string
        """
        reasons = []

        # Identify active indicators
        active_indicators = [
            key.replace("_", " ")
            for key, value in indicators.items()
            if value
        ]

        if active_indicators:
            reasons.append(f"Detected: {', '.join(active_indicators)}")

        # Delegation recommendation
        if should_delegate:
            reasons.append(
                f"Complexity score ({complexity_score}/10) suggests delegating "
                "to specialized sub-agents for optimal execution"
            )
        else:
            reasons.append(
                f"Complexity score ({complexity_score}/10) suggests single-agent "
                "execution is sufficient"
            )

        return ". ".join(reasons)

    def categorize_task_type(self, task_description: str) -> str:
        """
        Categorize task into a primary type.

        Args:
            task_description: Task description

        Returns:
            Task category: 'research', 'code', 'planning', 'time', 'data', 'general'
        """
        description_lower = task_description.lower()

        # Check in priority order
        if self._requires_planning(description_lower):
            return "planning"

        if self._mentions_code_execution(description_lower):
            return "code"

        if self._mentions_web_search(description_lower):
            return "research"

        if self._requires_data_analysis(description_lower):
            return "data"

        if self._is_time_sensitive(description_lower):
            return "time"

        return "general"


# Global singleton
_task_analyzer_instance: TaskComplexityAnalyzer | None = None


def get_task_analyzer() -> TaskComplexityAnalyzer:
    """Get global TaskComplexityAnalyzer instance (singleton)."""
    global _task_analyzer_instance
    if _task_analyzer_instance is None:
        _task_analyzer_instance = TaskComplexityAnalyzer()
    return _task_analyzer_instance
