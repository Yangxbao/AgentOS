"""提示词版本化（B4）。"""
from .service import (
    activate_revision,
    create_revision,
    diff_against_previous,
    get_revision,
    list_revisions,
    load_active_prompt,
    serialize_revision,
)

__all__ = [
    "activate_revision",
    "create_revision",
    "diff_against_previous",
    "get_revision",
    "list_revisions",
    "load_active_prompt",
    "serialize_revision",
]
