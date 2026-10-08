"""FREE-AUTO adaptive free-model router.

A local OpenAI-compatible gateway exposing one virtual model (``free-auto``)
that fans out to the currently healthiest free upstream model per request.

Pipeline per request: classify task -> filter incompatible -> drop
exhausted/unhealthy -> capability score -> task score -> live health ->
latency/quota -> highest wins, fail over to next on retryable failure.
"""

from lib.free_auto.task_classify import TaskClass, classify_task
from lib.free_auto.registry import ModelEntry, Registry, load_registry
from lib.free_auto.health import FailureClass, HealthStore
from lib.free_auto.scoring import rank_candidates, score_candidate
from lib.free_auto.gateway import FreeAutoRouter

__all__ = [
    "TaskClass",
    "classify_task",
    "ModelEntry",
    "Registry",
    "load_registry",
    "FailureClass",
    "HealthStore",
    "rank_candidates",
    "score_candidate",
    "FreeAutoRouter",
]
