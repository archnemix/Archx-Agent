"""Ordered schema manifest. Each released version owns its SQL in one migration file.

Append versions; never rewrite, renumber or discover migrations by filesystem order.
"""

from archx_agent.helpers.sqlite_store import Migration

from .v01_conversations import CONVERSATIONS_V1 as CONVERSATIONS_V1
from .v02_projects import PROJECTS_V2 as PROJECTS_V2
from .v03_memory import MEMORY_V3 as MEMORY_V3
from .v04_context import CONTEXT_V4 as CONTEXT_V4
from .v05_tasks_history import TASKS_V5 as TASKS_V5
from .v06_tools_permissions import TOOLS_V6 as TOOLS_V6
from .v07_scheduler import JOBS_V7 as JOBS_V7
from .v08_feature_modes import FEATURES_V8 as FEATURES_V8
from .v09_retrieval import RETRIEVAL_V9 as RETRIEVAL_V9
from .v10_model_catalogue import MODELS_V10 as MODELS_V10
from .v11_context_proposals import CONTEXT_PROPOSALS_V11 as CONTEXT_PROPOSALS_V11
from .v12_provider_privacy import PROVIDERS_V12 as PROVIDERS_V12
from .v13_tool_permissions import PERMISSIONS_V13 as PERMISSIONS_V13
from .v14_mcp_extensions import MCP_V14 as MCP_V14
from .v15_task_history import TASKS_V15 as TASKS_V15
from .v16_agent_workflows import WORKFLOWS_V16 as WORKFLOWS_V16
from .v17_scheduler_claims import JOBS_V17 as JOBS_V17
from .v18_researcher_mode import RESEARCH_V18 as RESEARCH_V18
from .v19_learning_mode import LEARNING_V19 as LEARNING_V19
from .v20_research_closure import RESEARCH_CLOSURE_V20 as RESEARCH_CLOSURE_V20
from .v21_coding_workspace import CODING_V21 as CODING_V21
from .v22_experiments import EXPERIMENTS_V22 as EXPERIMENTS_V22
from .v23_play import PLAY_V23 as PLAY_V23
from .v24_media import MEDIA_V24 as MEDIA_V24
from .v25_datasets import DATASETS_V25 as DATASETS_V25
from .v26_training import TRAINING_V26 as TRAINING_V26
from .v27_remote import REMOTE_V27 as REMOTE_V27
from .v28_execution import EXECUTION_V28 as EXECUTION_V28
from .v29_scenes import SCENES_V29 as SCENES_V29
from .v30_automation_revisions import AUTOMATIONS_V30 as AUTOMATIONS_V30

from .v31_conversation_setting_keys import (
    CONVERSATION_SETTINGS_V31 as CONVERSATION_SETTINGS_V31,
)


MIGRATIONS: tuple[Migration, ...] = (
    CONVERSATIONS_V1,
    PROJECTS_V2,
    MEMORY_V3,
    CONTEXT_V4,
    TASKS_V5,
    TOOLS_V6,
    JOBS_V7,
    FEATURES_V8,
    RETRIEVAL_V9,
    MODELS_V10,
    CONTEXT_PROPOSALS_V11,
    PROVIDERS_V12,
    PERMISSIONS_V13,
    MCP_V14,
    TASKS_V15,
    WORKFLOWS_V16,
    JOBS_V17,
    RESEARCH_V18,
    LEARNING_V19,
    RESEARCH_CLOSURE_V20,
    CODING_V21,
    EXPERIMENTS_V22,
    PLAY_V23,
    MEDIA_V24,
    DATASETS_V25,
    TRAINING_V26,
    REMOTE_V27,
    EXECUTION_V28,
    SCENES_V29,
    AUTOMATIONS_V30,
    CONVERSATION_SETTINGS_V31,
)

SCHEMA_VERSION = max(m.version for m in MIGRATIONS)

__all__ = ["MIGRATIONS", "SCHEMA_VERSION"]
