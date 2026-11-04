"""组织域服务：公司 / 部门 / 岗位 / 组织树。

业务规则见 M1_PLAN_HANDOFF.md §4.2（BR-02/03/04/05）与 §12 B2。
"""
from .companies import archive_company, create_company, get_company, list_companies, update_company
from .departments import (
    create_department,
    delete_department,
    list_departments,
    move_department,
    update_department,
)
from .positions import create_position, delete_position, get_position, list_positions, update_position
from .tree import build_org_tree

__all__ = [
    "archive_company",
    "build_org_tree",
    "create_company",
    "create_department",
    "create_position",
    "delete_department",
    "delete_position",
    "get_company",
    "get_position",
    "list_companies",
    "list_departments",
    "list_positions",
    "move_department",
    "update_company",
    "update_department",
    "update_position",
]
