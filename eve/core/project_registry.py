#!/usr/bin/env python3
"""
EVE Project Registry — Loader
=============================
Read-only metadata loader for project listing.

This module is imported by trinity_api.py.
It does NOT run as a standalone service.

© 2026 Organiq Sweden AB
"""

import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

# ════════════════════════════════════════════════════════════════
# CONFIGURATION
# ════════════════════════════════════════════════════════════════

PROJECTS_FILE = Path(__file__).parent.parent / "data" / "projects.json"

# ════════════════════════════════════════════════════════════════
# MODELS (read-only, no mutations)
# ════════════════════════════════════════════════════════════════

class ProjectMetadata(BaseModel):
    """Read-only project metadata."""
    project_id: str
    label: str
    project_class: str = Field(description="system | legal | medical | energy | custom")
    trust_tier: str = Field(description="T0 (system) | T1 | T2 | T3 (production)")
    description: Optional[str] = None
    locked: bool = False


class ProjectListResponse(BaseModel):
    """Response for GET /api/projects."""
    projects: List[ProjectMetadata]
    count: int


# ════════════════════════════════════════════════════════════════
# REGISTRY LOADER
# ════════════════════════════════════════════════════════════════

_cached_projects: Optional[List[Dict[str, Any]]] = None


def load_projects() -> List[Dict[str, Any]]:
    """
    Load projects from JSON file.
    
    Validates:
    - File exists
    - Valid JSON
    - No duplicate project_ids
    - 'legacy' project exists
    """
    global _cached_projects
    
    if _cached_projects is not None:
        return _cached_projects
    
    if not PROJECTS_FILE.exists():
        raise RuntimeError(f"Projects file not found: {PROJECTS_FILE}")
    
    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    if not isinstance(data, list):
        raise RuntimeError("projects.json must be a JSON array")
    
    # Validate no duplicates
    ids = [p.get("project_id") for p in data]
    duplicates = [pid for pid in ids if ids.count(pid) > 1]
    if duplicates:
        raise RuntimeError(f"Duplicate project_id(s): {set(duplicates)}")
    
    # Validate legacy exists
    if "legacy" not in ids:
        raise RuntimeError("'legacy' project is required but missing")
    
    _cached_projects = data
    return _cached_projects


def get_project_metadata(project_id: str) -> Optional[Dict[str, Any]]:
    """Get a single project by ID."""
    projects = load_projects()
    for p in projects:
        if p.get("project_id") == project_id:
            return p
    return None


def list_all_projects() -> ProjectListResponse:
    """Get all projects as response model."""
    projects = load_projects()
    return ProjectListResponse(
        projects=[ProjectMetadata(**p) for p in projects],
        count=len(projects)
    )
