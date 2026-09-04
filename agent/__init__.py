"""Agent package — Phase 13.1: Planner, BaseAgent, orchestrator, verifier.

Public API:
    Task, TaskStatus           — agent task model
    Planner, StubPlanner       — goal -> task planning
    LLMPlanner                 — LLM-backed planning (fallback to StubPlanner)
    BaseAgent                  — ReAct act-loop over secured tool registry
    StubReasoner, LLMReasoner  — iteration-bounded reasoning layer
    AgentOrchestrator          — multi-agent workflow coordinator
    AgentVerifier              — Step 8: verifies execution results
    VerificationResult         — structured verification outcome
    VerificationStatus         — PASSED / NEEDS_REVIEW / FAILED
"""

from agent.base import BaseAgent
from agent.orchestrator import AgentOrchestrator
from agent.planner import LLMPlanner, Planner, StubPlanner
from agent.reasoning import LLMReasoner, StubReasoner
from agent.selector import AgentSelector
from agent.task import Task, TaskStatus
from agent.verifier import AgentVerifier, VerificationResult, VerificationStatus

__all__ = [
    "AgentOrchestrator",
    "AgentSelector",
    "AgentVerifier",
    "BaseAgent",
    "LLMPlanner",
    "LLMReasoner",
    "Planner",
    "StubPlanner",
    "StubReasoner",
    "Task",
    "TaskStatus",
    "VerificationResult",
    "VerificationStatus",
]
