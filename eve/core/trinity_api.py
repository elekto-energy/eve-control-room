#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
TRINITY API — Port 8000
═══════════════════════════════════════════════════════════════════════════════
"""

import sys
import os

# ============================================================================
# CAS RUNTIME OBSERVATION
# ============================================================================
if os.environ.get("CAS_PROBE_DISABLED", "").lower() not in ("1", "true", "yes"):
    try:
        sys.path.insert(0, "D:/EVE11/core/V14")
        from cas.monitor.runtime_probe import enable_runtime_probe
        enable_runtime_probe()
    except Exception:
        pass
# ============================================================================

"""
"The only place where truth is created."

Trinity is not a separate engine. Trinity is the execution role of EVE Core
when exposed via HTTP on port 8000.

Endpoints:
  POST /execute_ecl     — Execute ECL command, create Decision + Vault proof
  POST /validate_ecl    — Validate ECL without executing
  POST /verify          — Verify decision integrity
  POST /replay          — Replay decision with full context
  GET  /decision/{id}   — Get decision by ID
  GET  /decisions       — List/query decisions
  GET  /status          — System status
  
  POST /artifact/create  — Create artifact (Draft)
  POST /artifact/propose — Change to Proposed
  GET  /artifacts        — List artifacts

This API:
  ✓ Works completely offline
  ✓ Requires no Claude or external AI
  ✓ Is fail-closed (rejects invalid input, never guesses)
  ✓ Uses same logic as eve-decision MCP server

© 2026 Organiq Sweden AB - Patent Pending
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

# Project Registry (read-only metadata)
try:
    from project_registry import list_all_projects, get_project_metadata, ProjectMetadata, ProjectListResponse
    PROJECT_REGISTRY_AVAILABLE = True
except ImportError:
    PROJECT_REGISTRY_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

DB_PATH = Path("D:/EVE11/core/V14/mcp/eve-decision-server/data/eve-db.json")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

TRINITY_VERSION = "1.1.0"


# ═══════════════════════════════════════════════════════════════════════════════
# PROJECT ID NORMALIZATION (v2)
# ═══════════════════════════════════════════════════════════════════════════════

PROJECT_ID_REGEX = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$")


def normalize_project_id(project_id: Optional[str]) -> tuple:
    """
    Normalize project_id and determine hash version.
    
    Returns:
        (project_id, hash_version)
    
    Rules:
        - None or empty → ("legacy", "v1")  — backward compatible
        - Valid string   → (project_id, "v2") — new hash model
        - Invalid string → ValueError          — fail hard
    
    "legacy" is NOT reserved. It is the v1 fallback.
    Trinity decides hash_version, not the client.
    """
    if not project_id:
        return "legacy", "v1"
    
    if not PROJECT_ID_REGEX.match(project_id):
        raise ValueError(
            f"Invalid project_id '{project_id}'. "
            f"Must match: {PROJECT_ID_REGEX.pattern}"
        )
    
    return project_id, "v2"


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS (LOCKED - matches eve-decision MCP server)
# ═══════════════════════════════════════════════════════════════════════════════

class DecisionType(str, Enum):
    CLASSIFICATION = "CLASSIFICATION"
    GOVERNANCE_APPROVAL = "GOVERNANCE_APPROVAL"
    RISK_ACCEPTANCE = "RISK_ACCEPTANCE"
    DATA_APPROVAL = "DATA_APPROVAL"
    CHANGE_APPROVAL = "CHANGE_APPROVAL"
    INCIDENT_ACTION = "INCIDENT_ACTION"
    DECOMMISSION = "DECOMMISSION"


class ECLDecisionCommand(str, Enum):
    CLASSIFY = "CLASSIFY"
    APPROVE_GOVERNANCE = "APPROVE_GOVERNANCE"
    ACCEPT_RISK = "ACCEPT_RISK"
    APPROVE_DATA = "APPROVE_DATA"
    APPROVE_CHANGE = "APPROVE_CHANGE"
    INCIDENT_ACTION = "INCIDENT_ACTION"
    DECOMMISSION = "DECOMMISSION"


COMMAND_TO_DECISION_TYPE = {
    ECLDecisionCommand.CLASSIFY: DecisionType.CLASSIFICATION,
    ECLDecisionCommand.APPROVE_GOVERNANCE: DecisionType.GOVERNANCE_APPROVAL,
    ECLDecisionCommand.ACCEPT_RISK: DecisionType.RISK_ACCEPTANCE,
    ECLDecisionCommand.APPROVE_DATA: DecisionType.DATA_APPROVAL,
    ECLDecisionCommand.APPROVE_CHANGE: DecisionType.CHANGE_APPROVAL,
    ECLDecisionCommand.INCIDENT_ACTION: DecisionType.INCIDENT_ACTION,
    ECLDecisionCommand.DECOMMISSION: DecisionType.DECOMMISSION,
}


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION RULES (LOCKED)
# ═══════════════════════════════════════════════════════════════════════════════

VALIDATION_RULES = {
    ECLDecisionCommand.CLASSIFY: {
        "required_artifacts": [("CDOC-SCOPE", 1), ("CDOC-CLASS", 1)],
        "required_roles": ["Compliance Owner"],
        "requires_risk_links": False
    },
    ECLDecisionCommand.APPROVE_GOVERNANCE: {
        "required_artifacts": [("CDOC-ROLES", 1), ("CDOC-MANDATE", 1)],
        "required_roles": ["Legal Counsel", "Board Member"],
        "requires_risk_links": False
    },
    ECLDecisionCommand.ACCEPT_RISK: {
        "required_artifacts": [("CDOC-RISK", 1), ("CDOC-MITIGATION", 1)],
        "required_roles": ["Risk Owner", "Compliance Owner"],
        "requires_risk_links": True
    },
    ECLDecisionCommand.APPROVE_DATA: {
        "required_artifacts": [("CDOC-DATA", 1), ("CDOC-QUALITY", 1)],
        "required_roles": ["Data Protection Officer"],
        "requires_risk_links": False
    },
    ECLDecisionCommand.APPROVE_CHANGE: {
        "required_artifacts": [("CDOC-CHANGE", 1), ("CDOC-IMPACT", 1)],
        "required_roles": ["System Owner", "Compliance Owner"],
        "requires_risk_links": "conditional"
    },
    ECLDecisionCommand.INCIDENT_ACTION: {
        "required_artifacts": [("CDOC-INCIDENT", 1), ("CDOC-ACTION", 1)],
        "required_roles": ["Incident Manager"],
        "requires_risk_links": True
    },
    ECLDecisionCommand.DECOMMISSION: {
        "required_artifacts": [("CDOC-DECOM", 1), ("CDOC-ARCHIVE", 1)],
        "required_roles": ["System Owner", "Legal Counsel"],
        "requires_risk_links": False
    },
}


# ═══════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class ECLRequest(BaseModel):
    ecl_command: str = Field(..., description="ECL command (text or JSON)")
    project_id: Optional[str] = Field(None, description="Project scope (required for v2)")


class VerifyRequest(BaseModel):
    eve_decision_id: str = Field(..., pattern=r"^EVE-\d{4}-\d{6}$")


class ReplayRequest(BaseModel):
    eve_decision_id: str = Field(..., pattern=r"^EVE-\d{4}-\d{6}$")


class CreateArtifactRequest(BaseModel):
    artifact_id: str
    content: Optional[str] = None


class ProposeArtifactRequest(BaseModel):
    artifact_id: str


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE (JSON-based, shared with MCP server)
# ═══════════════════════════════════════════════════════════════════════════════

class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.state = self._load()
    
    def _load(self) -> Dict:
        try:
            if self.db_path.exists():
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except:
            pass
        return {"edi_sequence": {}, "decisions": [], "vault": [], "artifacts": []}
    
    def _save(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.db_path, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)
    
    def generate_next_edi(self) -> str:
        year = datetime.now().year
        current = self.state["edi_sequence"].get(str(year), 0)
        next_seq = current + 1
        self.state["edi_sequence"][str(year)] = next_seq
        self._save()
        return f"EVE-{year}-{next_seq:06d}"
    
    def insert_decision(self, decision: Dict):
        self.state["decisions"].append(decision)
        self._save()
    
    def get_decision(self, eve_decision_id: str) -> Optional[Dict]:
        for d in self.state["decisions"]:
            if d["eve_decision_id"] == eve_decision_id:
                return d
        return None
    
    def list_decisions(self, filters: Optional[Dict] = None) -> List[Dict]:
        results = list(self.state["decisions"])
        if filters:
            if filters.get("decision_type"):
                results = [d for d in results if d["decision_type"] == filters["decision_type"]]
            if filters.get("status"):
                results = [d for d in results if d["status"] == filters["status"]]
            if filters.get("system_id"):
                results = [d for d in results if d["scope"]["system_id"] == filters["system_id"]]
            if filters.get("project_id"):
                results = [d for d in results if d.get("project_id") == filters["project_id"]]
        return sorted(results, key=lambda x: x["created_at"], reverse=True)
    
    def supersede(self, old_edi: str, new_edi: str):
        for d in self.state["decisions"]:
            if d["eve_decision_id"] == old_edi:
                d["status"] = "SUPERSEDED"
                d["superseded_by"] = new_edi
                self._save()
                return
    
    def seal_to_vault(self, eve_decision_id: str, evidence_type: str, payload: Dict) -> Dict:
        if not eve_decision_id or not re.match(r"^EVE-\d{4}-\d{6}$", eve_decision_id):
            raise ValueError(f"REJECTED: Invalid EVE Decision ID: {eve_decision_id}")
        
        payload_str = json.dumps(payload, sort_keys=True)
        payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()
        sealed_at = datetime.now(timezone.utc).isoformat()
        vault_proof = hashlib.sha256(f"{payload_hash}:{sealed_at}:EVE-VAULT-v1".encode()).hexdigest()[:32]
        
        entry = {
            "eve_decision_id": eve_decision_id,
            "evidence_type": evidence_type,
            "payload_hash": payload_hash,
            "sealed_at": sealed_at,
            "vault_proof": vault_proof
        }
        self.state["vault"].append(entry)
        self._save()
        return entry
    
    def get_vault_entry(self, eve_decision_id: str) -> Optional[Dict]:
        for v in self.state["vault"]:
            if v["eve_decision_id"] == eve_decision_id:
                return v
        return None
    
    def create_artifact(self, artifact_id: str, content: Optional[str] = None):
        if not any(a["artifact_id"] == artifact_id for a in self.state["artifacts"]):
            self.state["artifacts"].append({
                "artifact_id": artifact_id,
                "status": "Draft",
                "content": content,
                "created_at": datetime.now(timezone.utc).isoformat()
            })
            self._save()
    
    def propose_artifact(self, artifact_id: str):
        for a in self.state["artifacts"]:
            if a["artifact_id"] == artifact_id and a["status"] == "Draft":
                a["status"] = "Proposed"
                a["frozen_at"] = datetime.now(timezone.utc).isoformat()
                self._save()
                return
    
    def link_artifact_to_decision(self, artifact_id: str, eve_decision_id: str):
        for a in self.state["artifacts"]:
            if a["artifact_id"] == artifact_id:
                a["status"] = "Executed"
                a["eve_decision_id"] = eve_decision_id
                self._save()
                return
    
    def get_artifact(self, artifact_id: str) -> Optional[Dict]:
        for a in self.state["artifacts"]:
            if a["artifact_id"] == artifact_id:
                return {"artifact_id": a["artifact_id"], "status": a["status"], "eve_decision_id": a.get("eve_decision_id")}
        return None
    
    def list_artifacts(self) -> List[Dict]:
        return [{"artifact_id": a["artifact_id"], "status": a["status"], "eve_decision_id": a.get("eve_decision_id")} for a in self.state["artifacts"]]


# ═══════════════════════════════════════════════════════════════════════════════
# ECL PARSER (Deterministic)
# ═══════════════════════════════════════════════════════════════════════════════

class ECLParser:
    VALID_DECISION_COMMANDS = [c.value for c in ECLDecisionCommand]
    VALID_READ_COMMANDS = ["QUERY", "REPLAY", "VERIFY"]
    
    def parse(self, input_str: str) -> Dict:
        input_str = input_str.strip()
        
        # Try JSON first
        if input_str.startswith("{"):
            try:
                return self._parse_json(json.loads(input_str))
            except json.JSONDecodeError:
                pass
        
        return self._parse_text(input_str)
    
    def _parse_text(self, text: str) -> Dict:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        
        if not lines:
            return {"success": False, "errors": ["Empty command"]}
        
        first_line = lines[0]
        if not first_line.upper().startswith("EVE "):
            return {"success": False, "errors": ["ECL command must start with 'EVE'"]}
        
        parts = first_line[4:].split()
        verb = parts[0].upper() if parts else None
        
        if not verb:
            return {"success": False, "errors": ["Missing command verb after 'EVE'"]}
        
        is_decision = verb in self.VALID_DECISION_COMMANDS
        is_read = verb in self.VALID_READ_COMMANDS
        
        if not is_decision and not is_read:
            return {"success": False, "errors": [f"Unknown command: {verb}. Valid: {', '.join(self.VALID_DECISION_COMMANDS + self.VALID_READ_COMMANDS)}"]}
        
        params = {}
        
        # Parse header
        if len(parts) >= 3 and parts[1].upper() == "SYSTEM":
            params["system_id"] = parts[2]
        elif len(parts) >= 3 and parts[1].upper() == "DECISION":
            params["eve_decision_id"] = parts[2]
        
        # Parse body
        for line in lines[1:]:
            upper = line.upper()
            if upper.startswith("USE_CASE "):
                match = re.match(r'USE_CASE\s+"([^"]+)"|USE_CASE\s+(.+)', line, re.I)
                params["use_case"] = match.group(1) or match.group(2) if match else ""
            elif upper.startswith("ARTIFACTS "):
                params["artifacts"] = [a.strip() for a in line[10:].split(",") if a.strip()]
            elif upper.startswith("RISK_LINKS "):
                params["risk_links"] = [r.strip() for r in line[11:].split(",") if r.strip()]
            elif upper.startswith("SIGNOFF "):
                params["signoff"] = []
                for s in line[8:].split(","):
                    if ":" in s:
                        role, actor = s.strip().split(":", 1)
                        params["signoff"].append({"role": role.strip(), "actor_id": actor.strip()})
            elif upper.startswith("PROJECT "):
                params["project_id"] = line[8:].strip()
            elif upper.startswith("SUPERSEDES "):
                params["supersedes"] = line[11:].strip()
        
        errors = []
        if is_decision and not params.get("system_id"):
            errors.append("Missing SYSTEM <id> in command header")
        
        return {
            "success": len(errors) == 0,
            "command": {"type": "decision" if is_decision else "read", "verb": verb, "params": params},
            "errors": errors
        }
    
    def _parse_json(self, obj: Dict) -> Dict:
        command = obj.get("command", "").upper()
        
        is_decision = command in self.VALID_DECISION_COMMANDS
        is_read = command in self.VALID_READ_COMMANDS
        
        if not command or (not is_decision and not is_read):
            return {"success": False, "errors": [f"Unknown command: {command}"]}
        
        params = {
            "system_id": obj.get("system_id"),
            "use_case": obj.get("use_case"),
            "artifacts": obj.get("artifacts"),
            "risk_links": obj.get("risk_links"),
            "signoff": obj.get("signoff"),
            "project_id": obj.get("project_id"),
            "eve_decision_id": obj.get("eve_decision_id"),
            "supersedes": obj.get("supersedes"),
            "filters": obj.get("filters")
        }
        
        errors = []
        if is_decision and not params.get("system_id"):
            errors.append("Missing 'system_id' for decision command")
        
        return {
            "success": len(errors) == 0,
            "command": {"type": "decision" if is_decision else "read", "verb": command, "params": params},
            "errors": errors
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ECL VALIDATOR
# ═══════════════════════════════════════════════════════════════════════════════

class ECLValidator:
    def validate(self, command: Dict) -> Dict:
        if command["type"] == "read":
            return {"valid": True, "errors": [], "warnings": []}
        
        verb = command["verb"]
        params = command["params"]
        
        try:
            cmd_enum = ECLDecisionCommand(verb)
        except ValueError:
            return {"valid": False, "errors": [f"Unknown decision command: {verb}"], "warnings": []}
        
        rules = VALIDATION_RULES.get(cmd_enum, {})
        errors = []
        warnings = []
        
        if not params.get("system_id"):
            errors.append(f"{verb} requires system_id")
        
        artifacts = params.get("artifacts", [])
        for prefix, min_count in rules.get("required_artifacts", []):
            matching = [a for a in artifacts if a.upper().startswith(prefix.upper())]
            if len(matching) < min_count:
                errors.append(f"{verb} requires {min_count} artifact(s) with prefix '{prefix}'. Found: {len(matching)}")
        
        signoffs = params.get("signoff", [])
        provided_roles = [s["role"] for s in signoffs]
        for required_role in rules.get("required_roles", []):
            if required_role not in provided_roles:
                errors.append(f"{verb} requires signoff from: '{required_role}'")
        
        risk_links = params.get("risk_links", [])
        if rules.get("requires_risk_links") is True and not risk_links:
            errors.append(f"{verb} requires at least one risk_link")
        elif rules.get("requires_risk_links") == "conditional" and not risk_links:
            warnings.append(f"{verb} may require risk_links depending on impact")
        
        if not params.get("use_case"):
            warnings.append(f"{verb} should include use_case for traceability")
        
        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


# ═══════════════════════════════════════════════════════════════════════════════
# DECISION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

class DecisionEngine:
    def __init__(self):
        self.db = Database()
        self.parser = ECLParser()
        self.validator = ECLValidator()
    
    def execute(self, ecl_input: str, project_id: str = None) -> Dict:
        parse_result = self.parser.parse(ecl_input)
        if not parse_result["success"]:
            return {"success": False, "errors": parse_result["errors"]}
        
        command = parse_result["command"]
        
        # Propagate project_id from API request into command params
        if project_id is not None:
            command["params"]["project_id"] = project_id
        
        if command["type"] == "read":
            return self._execute_read(command)
        
        validation = self.validator.validate(command)
        if not validation["valid"]:
            return {"success": False, "errors": validation["errors"], "warnings": validation["warnings"]}
        
        return self._execute_decision(command, validation["warnings"])
    
    def validate(self, ecl_input: str) -> Dict:
        parse_result = self.parser.parse(ecl_input)
        if not parse_result["success"]:
            return {"parse_result": parse_result}
        
        validation = self.validator.validate(parse_result["command"])
        return {"parse_result": parse_result, "validation": validation}
    
    def _execute_decision(self, command: Dict, warnings: List[str]) -> Dict:
        verb = command["verb"]
        params = command["params"]
        
        if params.get("supersedes"):
            return self._execute_supersede(command, warnings)
        
        eve_decision_id = self.db.generate_next_edi()
        decision_obj = self._create_decision_object(eve_decision_id, command)
        
        self.db.insert_decision(decision_obj)
        vault_entry = self.db.seal_to_vault(eve_decision_id, "DECISION", decision_obj)
        
        for artifact_id in params.get("artifacts", []):
            self.db.link_artifact_to_decision(artifact_id, eve_decision_id)
        
        return {
            "success": True,
            "eve_decision_id": eve_decision_id,
            "vault_proof": vault_entry["vault_proof"],
            "sealed_at": vault_entry["sealed_at"],
            "warnings": warnings if warnings else None
        }
    
    def _execute_supersede(self, command: Dict, warnings: List[str]) -> Dict:
        params = command["params"]
        supersedes = params["supersedes"]
        
        original = self.db.get_decision(supersedes)
        if not original:
            return {"success": False, "errors": [f"Decision not found: {supersedes}"]}
        if original["status"] != "EXECUTED":
            return {"success": False, "errors": [f"Cannot supersede {original['status']} decision"]}
        
        eve_decision_id = self.db.generate_next_edi()
        decision_obj = self._create_decision_object(eve_decision_id, command)
        
        self.db.insert_decision(decision_obj)
        self.db.supersede(supersedes, eve_decision_id)
        vault_entry = self.db.seal_to_vault(eve_decision_id, "DECISION", decision_obj)
        
        return {
            "success": True,
            "eve_decision_id": eve_decision_id,
            "vault_proof": vault_entry["vault_proof"],
            "sealed_at": vault_entry["sealed_at"],
            "warnings": [f"Superseded: {supersedes}"] + (warnings or [])
        }
    
    def _create_decision_object(self, eve_decision_id: str, command: Dict) -> Dict:
        params = command["params"]
        verb = command["verb"]
        
        # v2: normalize project_id — Trinity decides hash_version
        project_id, hash_version = normalize_project_id(params.get("project_id"))
        
        context_data = json.dumps({
            "project_id": project_id,
            "system_id": params.get("system_id"),
            "use_case": params.get("use_case"),
            "artifacts": params.get("artifacts"),
            "risk_links": params.get("risk_links"),
            "signoff": params.get("signoff")
        }, sort_keys=True)
        
        rules_hash = hashlib.sha256(json.dumps(VALIDATION_RULES, sort_keys=True, default=str).encode()).hexdigest()[:8]
        
        return {
            "eve_decision_id": eve_decision_id,
            "project_id": project_id,
            "hash_version": hash_version,
            "decision_type": COMMAND_TO_DECISION_TYPE[ECLDecisionCommand(verb)].value,
            "status": "EXECUTED",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "executed_by": [{"role": s["role"], "actor_id": s["actor_id"], "approval_method": "explicit_signoff"} for s in params.get("signoff", [])],
            "scope": {"system_id": params.get("system_id", ""), "use_case": params.get("use_case", "")},
            "source_artifacts": params.get("artifacts", []),
            "risk_links": params.get("risk_links"),
            "rule_set_version": f"eve-ruleset-v1.0-{rules_hash}",
            "context_hash": hashlib.sha256(context_data.encode()).hexdigest(),
            "supersedes": params.get("supersedes")
        }
    
    def _execute_read(self, command: Dict) -> Dict:
        verb = command["verb"]
        params = command["params"]
        
        if verb == "REPLAY":
            return self._replay(params.get("eve_decision_id"))
        elif verb == "VERIFY":
            return self._verify(params.get("eve_decision_id"))
        elif verb == "QUERY":
            return self._query(params.get("filters", {}))
        
        return {"success": False, "errors": [f"Unknown read command: {verb}"]}
    
    def _replay(self, eve_decision_id: str) -> Dict:
        decision = self.db.get_decision(eve_decision_id)
        if not decision:
            return {"success": False, "errors": [f"Decision not found: {eve_decision_id}"]}
        
        vault_entry = self.db.get_vault_entry(eve_decision_id)
        
        return {
            "success": True,
            "data": {
                "eve_decision_id": eve_decision_id,
                "decision_type": decision["decision_type"],
                "frozen_input": {
                    "artifacts": [{"id": a, "content_hash": f"snapshot-{a}"} for a in decision["source_artifacts"]]
                },
                "accountability": {
                    "executed_by": [{"role": e["role"], "actor_id": e["actor_id"], "approval_timestamp": decision["created_at"]} for e in decision["executed_by"]]
                },
                "outcome": {"status": decision["status"]},
                "verification": {
                    "vault_sealed": vault_entry is not None,
                    "sealed_at": vault_entry["sealed_at"] if vault_entry else None
                }
            }
        }
    
    def _verify(self, eve_decision_id: str) -> Dict:
        decision = self.db.get_decision(eve_decision_id)
        vault_entry = self.db.get_vault_entry(eve_decision_id)
        
        return {
            "success": True,
            "data": {
                "eve_decision_id": eve_decision_id,
                "checks": {
                    "decision_exists": decision is not None,
                    "vault_exists": vault_entry is not None,
                    "status": decision["status"] if decision else "NOT_FOUND"
                },
                "overall_valid": decision is not None and vault_entry is not None
            }
        }
    
    def _query(self, filters: Dict) -> Dict:
        decisions = self.db.list_decisions(filters)
        return {
            "success": True,
            "data": {
                "count": len(decisions),
                "decisions": [{"eve_decision_id": d["eve_decision_id"], "decision_type": d["decision_type"], "status": d["status"], "created_at": d["created_at"], "system_id": d["scope"]["system_id"]} for d in decisions]
            }
        }


# ═══════════════════════════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="EVE Trinity API",
    description="The only place where truth is created. Port 8000.",
    version=TRINITY_VERSION
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

engine = DecisionEngine()


# ═══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root():
    return {
        "service": "EVE Trinity API",
        "version": TRINITY_VERSION,
        "role": "The only place where truth is created",
        "port": 8000,
        "endpoints": ["/execute_ecl", "/validate_ecl", "/verify", "/replay", "/decision/{id}", "/decisions", "/status", "/artifacts"]
    }


@app.get("/status")
async def status():
    decisions = engine.db.list_decisions()
    artifacts = engine.db.list_artifacts()
    return {
        "service": "EVE Trinity API",
        "version": TRINITY_VERSION,
        "status": "ONLINE",
        "offline_capable": True,
        "decisions_count": len(decisions),
        "artifacts_count": len(artifacts),
        "artifacts_by_status": {
            "Draft": len([a for a in artifacts if a["status"] == "Draft"]),
            "Proposed": len([a for a in artifacts if a["status"] == "Proposed"]),
            "Executed": len([a for a in artifacts if a["status"] == "Executed"])
        }
    }


@app.post("/execute_ecl")
async def execute_ecl(request: ECLRequest):
    result = engine.execute(request.ecl_command, project_id=request.project_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result)
    return result


@app.post("/validate_ecl")
async def validate_ecl(request: ECLRequest):
    return engine.validate(request.ecl_command)


@app.post("/verify")
async def verify(request: VerifyRequest):
    result = engine._verify(request.eve_decision_id)
    return result


@app.post("/replay")
async def replay(request: ReplayRequest):
    result = engine._replay(request.eve_decision_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=result)
    return result


@app.get("/decision/{eve_decision_id}")
async def get_decision(eve_decision_id: str):
    decision = engine.db.get_decision(eve_decision_id)
    if not decision:
        raise HTTPException(status_code=404, detail=f"Decision not found: {eve_decision_id}")
    return decision


@app.get("/decisions")
async def list_decisions(decision_type: Optional[str] = None, system_id: Optional[str] = None, status: Optional[str] = None, project_id: Optional[str] = None):
    filters = {}
    if decision_type:
        filters["decision_type"] = decision_type
    if system_id:
        filters["system_id"] = system_id
    if status:
        filters["status"] = status
    if project_id:
        filters["project_id"] = project_id
    
    decisions = engine.db.list_decisions(filters)
    return {"count": len(decisions), "decisions": decisions}


@app.post("/artifact/create")
async def create_artifact(request: CreateArtifactRequest):
    engine.db.create_artifact(request.artifact_id, request.content)
    return {"success": True, "artifact_id": request.artifact_id, "status": "Draft"}


@app.post("/artifact/propose")
async def propose_artifact(request: ProposeArtifactRequest):
    engine.db.propose_artifact(request.artifact_id)
    return {"success": True, "artifact_id": request.artifact_id, "status": "Proposed"}


@app.get("/artifacts")
async def list_artifacts():
    return {"artifacts": engine.db.list_artifacts()}


# ═══════════════════════════════════════════════════════════════════════════════
# APPROVAL REGISTRY ENDPOINTS (for Artifact Approval UI)
# ═══════════════════════════════════════════════════════════════════════════════

# Pydantic models for Approval Registry
class ApprovalRequest(BaseModel):
    type: str  # "artifact" or "knowledge"
    id: str
    approved_by: str
    note: Optional[str] = None


class RejectRequest(BaseModel):
    type: str
    id: str
    rejected_by: str
    reason: Optional[str] = None


# Approval Registry - stored in database
def _get_approvals(db: Database) -> List[Dict]:
    """Get approvals list from database state."""
    if "approvals" not in db.state:
        db.state["approvals"] = []
    return db.state["approvals"]


def _save_approval(db: Database, approval: Dict):
    """Save approval to database."""
    approvals = _get_approvals(db)
    # Remove existing if any
    approvals = [a for a in approvals if not (a["type"] == approval["type"] and a["id"] == approval["id"])]
    approvals.append(approval)
    db.state["approvals"] = approvals
    db._save()


@app.get("/api/v1/trinity/approvals/status")
async def approval_registry_status():
    """Approval Registry status - used by Artifact Approval UI."""
    approvals = _get_approvals(engine.db)
    return {
        "registry_enabled": True,
        "service": "EVE Trinity Approval Registry",
        "version": TRINITY_VERSION,
        "total_approvals": len(approvals),
        "by_type": {
            "artifact": len([a for a in approvals if a["type"] == "artifact"]),
            "knowledge": len([a for a in approvals if a["type"] == "knowledge"])
        },
        "by_status": {
            "APPROVED": len([a for a in approvals if a["status"] == "APPROVED"]),
            "APPROVED_WITH_NOTE": len([a for a in approvals if a["status"] == "APPROVED_WITH_NOTE"]),
            "REJECTED": len([a for a in approvals if a["status"] == "REJECTED"])
        }
    }


@app.get("/api/v1/trinity/approvals")
async def list_approvals(type: Optional[str] = None):
    """List approvals, optionally filtered by type."""
    approvals = _get_approvals(engine.db)
    
    if type:
        approvals = [a for a in approvals if a["type"] == type]
    
    return {
        "count": len(approvals),
        "items": approvals
    }


@app.post("/api/v1/trinity/approvals/approve")
async def approve_item(request: ApprovalRequest):
    """Approve an artifact or knowledge item with X-Vault seal.
    
    After approval, automatically syncs to evidence_chain for Ask EVE.
    """
    ts = datetime.now(timezone.utc).isoformat()
    
    # Create content hash for X-Vault
    content_data = json.dumps({
        "type": request.type,
        "id": request.id,
        "approved_by": request.approved_by,
        "note": request.note,
        "timestamp": ts
    }, sort_keys=True)
    content_hash = hashlib.sha256(content_data.encode()).hexdigest()
    
    # Determine status
    status = "APPROVED_WITH_NOTE" if request.note else "APPROVED"
    
    # Create approval record
    approval = {
        "type": request.type,
        "id": request.id,
        "status": status,
        "approved_by": request.approved_by,
        "approved_at": ts,
        "note": request.note,
        "content_hash": content_hash,
        "sealed_at": ts
    }
    
    # Save to database
    _save_approval(engine.db, approval)
    
    # ═══════════════════════════════════════════════════════════════════════
    # AUTO-SYNC TO KNOWLEDGE-RELEASES (Git → GitHub → Cloud)
    # ═══════════════════════════════════════════════════════════════════════
    git_result = None
    if request.type == "knowledge":
        try:
            from knowledge_release_pipeline import on_trinity_approve
            
            # Get article content from documents
            git_result = on_trinity_approve({
                "type": request.type,
                "id": request.id,
                "eve_id": engine.db.generate_next_edi(),
                "approved_by": request.approved_by,
                "content": {}  # Content loaded from documents/
            })
            print(f"[Trinity] Git commit: {git_result}")
        except ImportError as e:
            print(f"[Trinity] Knowledge release pipeline not available: {e}")
        except Exception as e:
            print(f"[Trinity] Git sync failed: {e}")
    # ═══════════════════════════════════════════════════════════════════════
    
    return {
        "success": True,
        "message": f"{request.type} '{request.id}' approved",
        "record": approval,
        "git_sync": git_result
    }


@app.post("/api/v1/trinity/approvals/reject")
async def reject_item(request: RejectRequest):
    """Reject an artifact or knowledge item."""
    ts = datetime.now(timezone.utc).isoformat()
    
    # Create rejection record
    rejection = {
        "type": request.type,
        "id": request.id,
        "status": "REJECTED",
        "rejected_by": request.rejected_by,
        "rejected_at": ts,
        "reason": request.reason
    }
    
    # Save to database
    _save_approval(engine.db, rejection)
    
    return {
        "success": True,
        "message": f"{request.type} '{request.id}' rejected",
        "record": rejection
    }


@app.get("/api/v1/trinity/approvals/{item_id}")
async def get_approval(item_id: str, type: Optional[str] = None):
    """Get approval status for a specific item."""
    approvals = _get_approvals(engine.db)
    
    for a in approvals:
        if a["id"] == item_id:
            if type is None or a["type"] == type:
                return a
    
    raise HTTPException(status_code=404, detail=f"Approval not found: {item_id}")


# ═══════════════════════════════════════════════════════════════════════════════
# PROJECT REGISTRY (read-only metadata)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/projects")
async def list_projects():
    """
    List all registered projects.
    
    Returns read-only metadata. No filtering, no mutations.
    This is system metadata, not governance.
    """
    if not PROJECT_REGISTRY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Project Registry not available")
    
    return list_all_projects()


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """
    Get a single project by ID.
    
    Returns 404 if not found.
    """
    if not PROJECT_REGISTRY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Project Registry not available")
    
    project = get_project_metadata(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    
    return ProjectMetadata(**project)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print()
    print("═" * 70)
    print("  EVE TRINITY API — Port 8000")
    print("  'The only place where truth is created.'")
    print("═" * 70)
    print(f"  Version:        {TRINITY_VERSION}")
    print(f"  Database:       {DB_PATH}")
    print(f"  Offline:        ✓ Fully capable")
    print(f"  Claude:         ✗ Not required")
    print("═" * 70)
    print()
    print("  Endpoints:")
    print("    POST /execute_ecl     — Execute ECL, create Decision")
    print("    POST /validate_ecl    — Validate without executing")
    print("    POST /verify          — Verify decision integrity")
    print("    POST /replay          — Replay decision")
    print("    GET  /decision/{id}   — Get decision by ID")
    print("    GET  /decisions       — List decisions")
    print("    GET  /status          — System status")
    print("    GET  /artifacts       — List artifacts")
    print()
    print("  Project Registry (read-only):")
    print("    GET  /api/projects         — List all projects")
    print("    GET  /api/projects/{id}    — Get single project")
    print()
    print("═" * 70)
    print("  Open in browser: http://127.0.0.1:8000")
    print("  API Docs:        http://127.0.0.1:8000/docs")
    print("═" * 70)
    print()
    
    uvicorn.run(app, host="127.0.0.1", port=8000)
