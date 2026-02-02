#!/usr/bin/env python3
"""
EVE Artifact Approval API
=========================

FastAPI backend för Artifact Approval UI.
Serverar data från artifacts/ och hanterar approve/reject.

Port: 8003 (för att inte krocka med Knowledge API på 8002)

Usage:
  python artifact_api.py

© 2026 Organiq Sweden AB - Patent Pending
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

import json
import yaml
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn
import httpx

# Lägg till core i path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

try:
    from core.artifacts import (
        seal_artifact,
        approve_artifact,
        reject_artifact,
        load_manifest,
        ManifestStatus
    )
    from core.artifacts.seal import verify_seal
    from core.artifacts.manifest import list_manifests
    CORE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import core.artifacts: {e}")
    CORE_AVAILABLE = False

# Import EVE VERIFIED store
try:
    from verified_store import VerifiedStore, create_verified_for_artifact, is_verified
    VERIFIED_STORE_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import verified_store: {e}")
    VERIFIED_STORE_AVAILABLE = False


# ============================================
# CONFIGURATION
# ============================================

ARTIFACTS_BASE = Path("D:/EVE11/core/V14/branches/artifact_factory/artifacts")
UI_PATH = Path(__file__).parent.parent / "ui"
AUDIT_LOG = Path("D:/EVE11/Projects/002_EVE_Control_Room/eve/logs/artifact_audit.log")

# Ensure log directory exists
AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)

# ============================================
# TRINITY CONNECTION (Single Source of Truth)
# ============================================
# GOVERNANCE RULE (LOCKED):
# All approvals/rejections MUST go via Trinity (SSOT).
# No local approval logic is allowed in endpoints.
# Clients initiate → Trinity decides → All others read.
# ============================================

TRINITY_API = "https://api.eveverified.com"
TRINITY_API_KEY = os.environ.get("EVE_TRINITY_API_KEY", "")  # Required for write ops

if not TRINITY_API_KEY:
    print("\n" + "=" * 60)
    print("  ⚠️  WARNING: EVE_TRINITY_API_KEY not set")
    print("     Approvals will fail without valid API key.")
    print("     Set: $env:EVE_TRINITY_API_KEY = 'eve_prod_xxx...'")
    print("=" * 60 + "\n")


def _trinity_headers(approver_id: str) -> Dict[str, str]:
    """Build headers for Trinity API calls."""
    return {
        "X-EVE-API-Key": TRINITY_API_KEY,
        "X-EVE-Approver-ID": approver_id
    }


async def trinity_health_check() -> bool:
    """Check if Trinity is online."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(f"{TRINITY_API}/api/v1/trinity/approvals/status")
            return res.status_code == 200
    except:
        return False


async def get_trinity_approvals(type_filter: str = "artifact") -> Dict[str, Dict]:
    """Get all approvals from Trinity, return as dict keyed by id."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(f"{TRINITY_API}/api/v1/trinity/approvals", params={"type": type_filter})
            if res.status_code == 200:
                data = res.json()
                return {item["id"]: item for item in data.get("items", [])}
    except Exception as e:
        print(f"⚠️  Failed to get Trinity approvals: {e}")
    return {}


async def approve_via_trinity(artifact_id: str, approved_by: str, note: Optional[str] = None, project_id: Optional[str] = None) -> Dict:
    """Send approval to Trinity Approval Registry (with auth)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            f"{TRINITY_API}/api/v1/trinity/approvals/approve",
            headers=_trinity_headers(approved_by),
            json={
                "type": "artifact",
                "id": artifact_id,
                "approved_by": approved_by,
                "note": note,
                "project_id": project_id
            }
        )
        if res.status_code == 200:
            return res.json()
        elif res.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid or missing API key. Set EVE_TRINITY_API_KEY.")
        elif res.status_code == 403:
            raise HTTPException(status_code=403, detail="API key does not have 'approve' permission.")
        else:
            raise HTTPException(status_code=res.status_code, detail=res.json().get("detail", "Trinity error"))


async def reject_via_trinity(artifact_id: str, rejected_by: str, reason: Optional[str] = None, project_id: Optional[str] = None) -> Dict:
    """Send rejection to Trinity Approval Registry (with auth)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        res = await client.post(
            f"{TRINITY_API}/api/v1/trinity/approvals/reject",
            headers=_trinity_headers(rejected_by),
            json={
                "type": "artifact",
                "id": artifact_id,
                "rejected_by": rejected_by,
                "reason": reason,
                "project_id": project_id
            }
        )
        if res.status_code == 200:
            return res.json()
        elif res.status_code == 401:
            raise HTTPException(status_code=401, detail="Invalid or missing API key. Set EVE_TRINITY_API_KEY.")
        elif res.status_code == 403:
            raise HTTPException(status_code=403, detail="API key does not have 'approve' permission.")
        else:
            raise HTTPException(status_code=res.status_code, detail=res.json().get("detail", "Trinity error"))


# ============================================
# PYDANTIC MODELS
# ============================================

class ApproveRequest(BaseModel):
    approved_by: str
    note: str
    project_id: Optional[str] = None


class RejectRequest(BaseModel):
    rejected_by: str
    reason: str
    project_id: Optional[str] = None


# ============================================
# FASTAPI APP
# ============================================

app = FastAPI(
    title="EVE Artifact Approval API",
    description="API for Artifact Approval Witness UI",
    version="1.0.0"
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# AUDIT LOGGING
# ============================================

def log_audit(action: str, artifact_id: str, user: str, details: str = ""):
    """Log audit event."""
    timestamp = datetime.now(timezone.utc).isoformat()
    log_line = f"{timestamp} | {action} | {artifact_id} | {user} | {details}\n"
    
    with open(AUDIT_LOG, 'a', encoding='utf-8') as f:
        f.write(log_line)
    
    print(f"📝 AUDIT: {action} | {artifact_id} | {user}")


def get_last_action() -> Optional[str]:
    """Get last audit action."""
    if not AUDIT_LOG.exists():
        return None
    
    try:
        lines = AUDIT_LOG.read_text().strip().split('\n')
        if lines and lines[-1]:
            parts = lines[-1].split(' | ')
            if len(parts) >= 4:
                timestamp = parts[0][:16].replace('T', ' ')
                action = parts[1]
                artifact = parts[2]
                user = parts[3]
                return f"{action} {artifact} by {user} @ {timestamp}"
    except:
        pass
    
    return None


# ============================================
# HELPER FUNCTIONS
# ============================================

def load_manifest_raw(artifact_path: Path) -> Dict:
    """Load manifest.yml as raw dict."""
    manifest_file = artifact_path / "manifest.yml"
    if not manifest_file.exists():
        return {}
    
    with open(manifest_file, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def load_schema(artifact_path: Path) -> str:
    """Load schema files (form.yml, variables.yml, or schema.json)."""
    schema_content = ""
    
    for filename in ["form.yml", "variables.yml", "schema.json"]:
        schema_file = artifact_path / filename
        if schema_file.exists():
            schema_content += f"--- {filename} ---\n"
            schema_content += schema_file.read_text(encoding='utf-8')
            schema_content += "\n\n"
    
    return schema_content.strip() if schema_content else "No schema files found"


def load_content(artifact_path: Path) -> str:
    """Load content.md."""
    content_file = artifact_path / "content.md"
    if content_file.exists():
        return content_file.read_text(encoding='utf-8')
    return ""


def get_artifact_list() -> List[Dict]:
    """Get list of all artifacts with basic info including EVE VERIFIED status."""
    artifacts = []
    
    if not ARTIFACTS_BASE.exists():
        return artifacts
    
    # Get verified store if available
    verified_store = None
    if VERIFIED_STORE_AVAILABLE:
        try:
            verified_store = VerifiedStore()
        except:
            pass
    
    for artifact_dir in sorted(ARTIFACTS_BASE.iterdir()):
        if not artifact_dir.is_dir():
            continue
        
        manifest = load_manifest_raw(artifact_dir)
        
        artifact_info = manifest.get("artifact", {})
        approval_info = manifest.get("approval", {})
        xvault_info = manifest.get("xvault", {})
        
        # Check EVE VERIFIED status
        eve_verified = False
        evev_id = None
        if verified_store:
            try:
                record = verified_store.get_verified_by_object("compliedocs", artifact_dir.name)
                if record:
                    eve_verified = True
                    evev_id = record.get("eve_verified_id")
            except:
                pass
        
        artifacts.append({
            "id": artifact_dir.name,
            "name": artifact_info.get("name", artifact_dir.name),
            "version": artifact_info.get("version", 0),
            "category": artifact_info.get("category", "general"),
            "status": approval_info.get("status", "NO_MANIFEST"),
            "sealed": bool(xvault_info),
            "sealed_at": xvault_info.get("sealed_at"),
            "sealed_by": xvault_info.get("sealed_by"),
            "eve_verified": eve_verified,
            "eve_verified_id": evev_id
        })
    
    return artifacts


# ============================================
# API ENDPOINTS
# ============================================

@app.get("/")
async def root():
    """Serve the UI."""
    ui_file = UI_PATH / "artifact_approval.html"
    if ui_file.exists():
        return FileResponse(ui_file)
    return {"message": "EVE Artifact Approval API", "ui": "Not found"}


@app.get("/api/artifacts")
async def list_artifacts(project_id: Optional[str] = None):
    """List all artifacts."""
    artifacts = get_artifact_list()
    
    if project_id:
        artifacts = [a for a in artifacts if a.get('project_id') == project_id]
    
    return {
        "artifacts": artifacts,
        "total": len(artifacts),
        "pending": len([a for a in artifacts if a["status"] == "PENDING"]),
        "approved": len([a for a in artifacts if a["status"] == "APPROVED"]),
        "rejected": len([a for a in artifacts if a["status"] == "REJECTED"]),
        "eve_verified": len([a for a in artifacts if a.get("eve_verified")]),
        "last_action": get_last_action()
    }


@app.get("/api/artifacts/{artifact_id}")
async def get_artifact(artifact_id: str):
    """Get artifact details."""
    artifact_path = ARTIFACTS_BASE / artifact_id
    
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")
    
    manifest = load_manifest_raw(artifact_path)
    content = load_content(artifact_path)
    schema = load_schema(artifact_path)
    
    # Verify seal if available
    integrity = None
    if CORE_AVAILABLE:
        try:
            is_valid, message = verify_seal(artifact_path)
            integrity = {"valid": is_valid, "message": message}
        except Exception as e:
            integrity = {"valid": False, "message": str(e)}
    
    return {
        "artifact": {
            "id": artifact_id,
            "path": str(artifact_path)
        },
        "manifest": manifest,
        "content": content,
        "schema": schema,
        "integrity": integrity
    }


@app.post("/api/artifacts/{artifact_id}/approve")
async def approve(artifact_id: str, request: ApproveRequest):
    """
    Approve an artifact via Trinity (SSOT).
    
    NOTE: All approvals MUST go via Trinity. No local approval logic allowed.
    This endpoint is a command client - Trinity is the decision point.
    """
    artifact_path = ARTIFACTS_BASE / artifact_id
    
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")
    
    # Validate
    if len(request.note) < 10:
        raise HTTPException(status_code=400, detail="Approval note must be at least 10 characters")
    
    if not request.approved_by:
        raise HTTPException(status_code=400, detail="approved_by is required")
    
    # Check Trinity is online
    if not await trinity_health_check():
        raise HTTPException(status_code=503, detail="Trinity (SSOT) is offline. Cannot approve.")
    
    try:
        # Send approval to Trinity (SSOT) - this IS the approval
        trinity_result = await approve_via_trinity(
            artifact_id=artifact_id,
            approved_by=request.approved_by,
            note=request.note,
            project_id=request.project_id
        )
        
        log_audit("APPROVED", artifact_id, request.approved_by, f"via Trinity: {request.note}")
        
        return {
            "success": True,
            "message": f"Artifact '{artifact_id}' approved via Trinity",
            "artifact_id": artifact_id,
            "source": "trinity",
            "trinity_record": trinity_result.get("record")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/artifacts/{artifact_id}/reject")
async def reject(artifact_id: str, request: RejectRequest):
    """
    Reject an artifact via Trinity (SSOT).
    
    NOTE: All rejections MUST go via Trinity. No local rejection logic allowed.
    """
    artifact_path = ARTIFACTS_BASE / artifact_id
    
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")
    
    if not request.rejected_by:
        raise HTTPException(status_code=400, detail="rejected_by is required")
    
    # Check Trinity is online
    if not await trinity_health_check():
        raise HTTPException(status_code=503, detail="Trinity (SSOT) is offline. Cannot reject.")
    
    try:
        # Send rejection to Trinity (SSOT)
        trinity_result = await reject_via_trinity(
            artifact_id=artifact_id,
            rejected_by=request.rejected_by,
            reason=request.reason,
            project_id=request.project_id
        )
        
        log_audit("REJECTED", artifact_id, request.rejected_by, f"via Trinity: {request.reason}")
        
        return {
            "success": True,
            "message": f"Artifact '{artifact_id}' rejected via Trinity",
            "artifact_id": artifact_id,
            "source": "trinity",
            "trinity_record": trinity_result.get("record")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/artifacts/{artifact_id}/seal")
async def seal(artifact_id: str, sealed_by: str = "api"):
    """Seal an artifact (create/update X-Vault hash)."""
    artifact_path = ARTIFACTS_BASE / artifact_id
    
    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_id}")
    
    if not CORE_AVAILABLE:
        raise HTTPException(status_code=500, detail="Core module not available")
    
    try:
        manifest, hashes = seal_artifact(artifact_path, sealed_by=sealed_by)
        
        log_audit("SEALED", artifact_id, sealed_by, f"v{manifest.artifact.version}")
        
        return {
            "success": True,
            "artifact_id": artifact_id,
            "version": manifest.artifact.version,
            "hashes": hashes
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/audit")
async def get_audit_log(limit: int = 50):
    """Get recent audit log entries."""
    if not AUDIT_LOG.exists():
        return {"entries": []}
    
    try:
        lines = AUDIT_LOG.read_text().strip().split('\n')
        entries = []
        
        for line in lines[-limit:]:
            parts = line.split(' | ')
            if len(parts) >= 4:
                entries.append({
                    "timestamp": parts[0],
                    "action": parts[1],
                    "artifact_id": parts[2],
                    "user": parts[3],
                    "details": parts[4] if len(parts) > 4 else ""
                })
        
        return {"entries": list(reversed(entries))}
        
    except Exception as e:
        return {"entries": [], "error": str(e)}


@app.get("/api/stats")
async def get_stats():
    """Get statistics."""
    artifacts = get_artifact_list()
    
    return {
        "total": len(artifacts),
        "pending": len([a for a in artifacts if a["status"] == "PENDING"]),
        "approved": len([a for a in artifacts if a["status"] == "APPROVED"]),
        "rejected": len([a for a in artifacts if a["status"] == "REJECTED"]),
        "no_manifest": len([a for a in artifacts if a["status"] == "NO_MANIFEST"]),
        "sealed": len([a for a in artifacts if a["sealed"]])
    }


@app.post("/api/refresh-from-factory")
async def refresh_from_factory():
    """
    Refresh all artifacts from factory disk and seal with X-Vault.
    
    Flow:
    1. Read content.md from each artifact
    2. Compute SHA-256 content hash
    3. Write X-Vault seal to manifest.yml
    4. Artifact is now frozen and ready for Trinity approval
    """
    import hashlib
    
    if not ARTIFACTS_BASE.exists():
        raise HTTPException(status_code=500, detail=f"Factory path not found: {ARTIFACTS_BASE}")
    
    sealed_count = 0
    errors = []
    
    for artifact_dir in sorted(ARTIFACTS_BASE.iterdir()):
        if not artifact_dir.is_dir():
            continue
        
        artifact_id = artifact_dir.name
        content_file = artifact_dir / "content.md"
        manifest_file = artifact_dir / "manifest.yml"
        meta_file = artifact_dir / "meta.yml"
        
        if not content_file.exists():
            continue
        
        try:
            # Read content and compute hash
            content = content_file.read_text(encoding='utf-8')
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
            
            # Create X-Vault seal timestamp
            sealed_at = datetime.now(timezone.utc).isoformat()
            
            # Load or create manifest
            manifest = {}
            if manifest_file.exists():
                manifest = yaml.safe_load(manifest_file.read_text(encoding='utf-8')) or {}
            
            # Load meta for artifact info
            meta = {}
            if meta_file.exists():
                meta = yaml.safe_load(meta_file.read_text(encoding='utf-8')) or {}
            
            # Update X-Vault section
            manifest['xvault'] = {
                'content_hash': content_hash,
                'algorithm': 'SHA-256',
                'sealed_at': sealed_at,
                'sealed_by': 'artifact_factory',
                'integrity_status': 'SEALED',
                'content_length': len(content)
            }
            
            # Update artifact section
            if 'artifact' not in manifest:
                manifest['artifact'] = {}
            manifest['artifact']['id'] = artifact_id
            manifest['artifact']['name'] = meta.get('artifact', {}).get('name', artifact_id)
            manifest['artifact']['category'] = meta.get('artifact', {}).get('category', 'general')
            manifest['artifact']['version'] = meta.get('artifact', {}).get('version', 1)
            
            # Update approval section - ready for Trinity
            if 'approval' not in manifest:
                manifest['approval'] = {}
            manifest['approval']['status'] = 'PENDING'
            manifest['approval']['xvault_sealed'] = True
            manifest['approval']['ready_for_trinity'] = True
            
            # Write manifest
            with open(manifest_file, 'w', encoding='utf-8') as f:
                yaml.dump(manifest, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            
            sealed_count += 1
            
        except Exception as e:
            errors.append(f"{artifact_id}: {str(e)}")
    
    log_audit("SEAL_ALL", "FACTORY", "system", f"Sealed {sealed_count} artifacts with X-Vault")
    
    return {
        "success": True,
        "message": f"Sealed {sealed_count} artifacts with X-Vault",
        "sealed_count": sealed_count,
        "errors": errors if errors else None,
        "factory_path": str(ARTIFACTS_BASE),
        "next_step": "Artifacts are now ready for Trinity approval"
    }


# ============================================
# EVE VERIFIED ENDPOINTS
# ============================================

@app.get("/api/verified/{artifact_id}")
async def get_verified_status(artifact_id: str):
    """Get EVE VERIFIED status for an artifact."""
    if not VERIFIED_STORE_AVAILABLE:
        return {
            "eve_verified": False,
            "reason": "Verified store not available"
        }
    
    try:
        store = VerifiedStore()
        record = store.get_verified_by_object("compliedocs", artifact_id)
        
        if record:
            return {
                "eve_verified": True,
                "eve_verified_id": record["eve_verified_id"],
                "verified_at": record["verified_at"],
                "signed_by": record.get("verification_chain", {}).get("signoff_by"),
                "status": record.get("status"),
                "content_hash": record.get("content_hash", "")[:16] + "..."
            }
        else:
            return {
                "eve_verified": False,
                "reason": "No EVEV record found"
            }
    except Exception as e:
        return {
            "eve_verified": False,
            "error": str(e)
        }


@app.get("/api/verified")
async def list_verified_artifacts(status: Optional[str] = "ACTIVE"):
    """List all EVE VERIFIED artifacts."""
    if not VERIFIED_STORE_AVAILABLE:
        return {
            "count": 0,
            "items": [],
            "error": "Verified store not available"
        }
    
    try:
        store = VerifiedStore()
        records = store.list_verified(domain="compliedocs", status=status)
        
        return {
            "count": len(records),
            "items": [
                {
                    "eve_verified_id": r["eve_verified_id"],
                    "object_id": r["object_id"],
                    "verified_at": r["verified_at"],
                    "status": r.get("status"),
                    "signed_by": r.get("verification_chain", {}).get("signoff_by")
                }
                for r in records
            ]
        }
    except Exception as e:
        return {
            "count": 0,
            "items": [],
            "error": str(e)
        }


@app.post("/api/verified/verify/{evev_id}")
async def verify_evev_integrity(evev_id: str):
    """Verify integrity of an EVEV record."""
    if not VERIFIED_STORE_AVAILABLE:
        raise HTTPException(status_code=500, detail="Verified store not available")
    
    try:
        store = VerifiedStore()
        result = store.verify_integrity(evev_id)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/verified/stats")
async def get_verified_stats():
    """Get EVE VERIFIED statistics."""
    if not VERIFIED_STORE_AVAILABLE:
        return {
            "available": False,
            "error": "Verified store not available"
        }
    
    try:
        store = VerifiedStore()
        stats = store.get_statistics()
        stats["available"] = True
        return stats
    except Exception as e:
        return {
            "available": False,
            "error": str(e)
        }


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    print("=" * 60)
    print("🏛️  EVE Artifact Approval API")
    print("=" * 60)
    print(f"📁 Artifacts: {ARTIFACTS_BASE}")
    print(f"🖥️  UI: {UI_PATH / 'artifact_approval.html'}")
    print(f"📝 Audit Log: {AUDIT_LOG}")
    print(f"🔧 Core Available: {CORE_AVAILABLE}")
    print(f"✅ Verified Store: {VERIFIED_STORE_AVAILABLE}")
    print("=" * 60)
    print()
    print("  Endpoints:")
    print("    GET  /api/artifacts                - List artifacts")
    print("    POST /api/artifacts/{id}/approve   - Approve + EVEV")
    print("    GET  /api/verified/{id}            - Check EVEV status")
    print("    GET  /api/verified                 - List all EVEV")
    print("    GET  /api/verified/stats           - EVEV statistics")
    print()
    print("🌐 Open in browser: http://127.0.0.1:8003")
    print()
    
    uvicorn.run(app, host="127.0.0.1", port=8003)
