"""
EVE Knowledge API v6.0 (TRINITY SYNC)
=====================================

FastAPI backend för Knowledge Approval UI.
Sparar godkännanden BÅDE lokalt OCH till Trinity cloud.

ARCHITECTURE:
- Knowledge API (8002) = lokal + Trinity sync
- Godkännanden sparas lokalt i eve_metadata
- Godkännanden synkas till Trinity cloud (api.eveverified.com)
- Trinity = Single Source of Truth för godkännanden

UPGRADE v5.0 → v6.0:
- Lade till Trinity sync vid godkännande
- Lade till httpx för async API-anrop
- EVE_TRINITY_API_KEY krävs för sync

Kör: python knowledge_api.py
API: http://127.0.0.1:8002

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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime
import hashlib
import json
import sys
import os
import uvicorn

# HTTP client for Trinity sync
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    print("⚠️  httpx not installed - Trinity sync disabled. Run: pip install httpx")

# Add paths
sys.path.insert(0, str(Path(__file__).parent))

# Import for fetching
try:
    from eurlex_cellar_api import fetch_regulation_cellar as fetch_regulation_articles, REGULATIONS
    print("✅ Using CELLAR API (official EUR-Lex API)")
except ImportError:
    from eurlex_fetcher import fetch_regulation_articles, REGULATIONS
    print("⚠️  Using legacy HTML fetcher (may be blocked by WAF)")

# Paths
KNOWLEDGE_PATH = Path("D:/EVE11/Projects/002_EVE_Control_Room/eve/knowledge")
PENDING_PATH = KNOWLEDGE_PATH / "pending"

# ============================================================
# TRINITY CONNECTION (Single Source of Truth)
# ============================================================

TRINITY_API = "https://api.eveverified.com"
TRINITY_API_KEY = os.environ.get("EVE_TRINITY_API_KEY", "")

TRINITY_ENABLED = bool(TRINITY_API_KEY) and HTTPX_AVAILABLE

if not TRINITY_API_KEY:
    print("\n" + "=" * 60)
    print("  ⚠️  WARNING: EVE_TRINITY_API_KEY not set")
    print("     Approvals will be LOCAL ONLY (not synced to cloud).")
    print("     Set: $env:EVE_TRINITY_API_KEY = 'eve_prod_xxx...'")
    print("=" * 60 + "\n")
else:
    print("✅ Trinity sync enabled (api.eveverified.com)")


def _trinity_headers(approver_id: str) -> Dict[str, str]:
    """Build headers for Trinity API calls."""
    return {
        "X-EVE-API-Key": TRINITY_API_KEY,
        "X-EVE-Approver-ID": approver_id
    }


async def sync_to_trinity(article_id: str, approved_by: str, content_hash: str, 
                          regulation: str, article_number: str,
                          project_id: Optional[str] = None,
                          observation: Optional[str] = None) -> Dict:
    """Sync approval to Trinity cloud."""
    if not TRINITY_ENABLED:
        return {"synced": False, "reason": "Trinity not configured"}
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(
                f"{TRINITY_API}/api/v1/trinity/approvals/approve",
                headers=_trinity_headers(approved_by),
                json={
                    "type": "knowledge",
                    "id": article_id,
                    "approved_by": approved_by,
                    "note": observation,
                    "project_id": project_id,
                    "metadata": {
                        "regulation": regulation,
                        "article_number": article_number,
                        "content_hash": content_hash
                    }
                }
            )
            if res.status_code == 200:
                data = res.json()
                print(f"  ☁️  Synced to Trinity: {article_id}")
                return {"synced": True, "trinity_response": data}
            else:
                print(f"  ⚠️  Trinity sync failed: {res.status_code} {res.text}")
                return {"synced": False, "error": res.text}
    except Exception as e:
        print(f"  ⚠️  Trinity sync error: {e}")
        return {"synced": False, "error": str(e)}


async def get_trinity_approvals() -> Dict[str, Dict]:
    """Get all knowledge approvals from Trinity."""
    if not TRINITY_ENABLED:
        return {}
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.get(
                f"{TRINITY_API}/api/v1/trinity/approvals",
                params={"type": "knowledge"}
            )
            if res.status_code == 200:
                data = res.json()
                return {item["id"]: item for item in data.get("items", [])}
    except Exception as e:
        print(f"⚠️  Failed to get Trinity approvals: {e}")
    return {}


# ============================================================
# LOCAL MODE + TRINITY SYNC
# ============================================================

READ_ONLY_MODE = os.environ.get("READ_ONLY", "false").lower() == "true"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")


def check_write_allowed():
    """Raise 403 if in read-only mode."""
    if READ_ONLY_MODE:
        raise HTTPException(
            status_code=403,
            detail="Knowledge API is in READ_ONLY mode. Write operations disabled."
        )


def get_local_status(article_data: dict) -> dict:
    """Extract status from local eve_metadata."""
    meta = article_data.get("eve_metadata", {})
    return {
        "status": meta.get("status", "PLACEHOLDER"),
        "approved": meta.get("approved", False),
        "approved_by": meta.get("approved_by"),
        "approved_date": meta.get("approved_date"),
        "observation": meta.get("observation")
    }


def create_approval_signature(content_hash: str, approved_by: str, timestamp: str) -> str:
    """Create deterministic approval signature."""
    data = f"{content_hash}:{approved_by}:{timestamp}"
    return hashlib.sha256(data.encode()).hexdigest()


# ============================================================
# WITNESS SMART IMPORT
# ============================================================
try:
    from witness_ai.witness_smart import (
        witness_smart_query_async,
        SmartWitnessResponse
    )
    WITNESS_SMART_ENABLED = True
    print("✅ Witness Smart module loaded")
except ImportError as e:
    WITNESS_SMART_ENABLED = False
    print(f"⚠️  Witness Smart not available: {e}")


# ============================================================
# API SETUP
# ============================================================

app = FastAPI(
    title="EVE Knowledge API",
    description="Knowledge approval with Trinity cloud sync.",
    version="6.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UI_PATH = Path(__file__).parent.parent / "ui"


# ============================================================
# MODELS
# ============================================================

class ApproveRequest(BaseModel):
    regulation: str
    article_number: str
    approved_by: str
    observation: Optional[str] = None
    project_id: Optional[str] = None

class RejectRequest(BaseModel):
    regulation: str
    article_number: str
    rejected_by: str
    reason: Optional[str] = "No reason given"
    project_id: Optional[str] = None

class FetchRequest(BaseModel):
    regulation: str
    articles: Optional[List[int]] = None

class WitnessSmartRequest(BaseModel):
    question: str
    language: str = "en"
    jurisdiction: str = "EU"
    regulations: Optional[List[str]] = None


# ============================================================
# ROUTES
# ============================================================

@app.get("/")
async def root():
    """Serve the UI."""
    return FileResponse(UI_PATH / "knowledge_approval.html")


@app.get("/api/health")
async def health():
    return {
        "status": "ok", 
        "service": "EVE Knowledge API",
        "version": "6.0.0",
        "mode": "LOCAL + TRINITY SYNC" if TRINITY_ENABLED else "LOCAL ONLY",
        "trinity_enabled": TRINITY_ENABLED,
        "read_only": READ_ONLY_MODE,
        "witness_smart_enabled": WITNESS_SMART_ENABLED,
        "anthropic_api_configured": bool(ANTHROPIC_API_KEY)
    }


@app.get("/api/stats")
async def get_stats():
    """Get knowledge base statistics from LOCAL files."""
    stats = {
        "total": 0,
        "approved": 0,
        "pending": 0,
        "placeholder": 0,
        "with_observation": 0,
        "regulations": {},
        "mode": "LOCAL + TRINITY" if TRINITY_ENABLED else "LOCAL",
        "trinity_enabled": TRINITY_ENABLED
    }
    
    for reg_key in REGULATIONS.keys():
        reg_stats = {
            "total": REGULATIONS[reg_key]["articles"],
            "approved": 0,
            "pending": 0,
            "placeholder": 0
        }
        
        # Count pending (local disk)
        pending_dir = PENDING_PATH / reg_key
        pending_articles = set()
        
        if pending_dir.exists():
            for f in pending_dir.glob("article_*.json"):
                pending_articles.add(f.stem)
                reg_stats["pending"] += 1
                stats["pending"] += 1
        
        # Count approved and placeholder from LOCAL files
        articles_dir = KNOWLEDGE_PATH / "documents/eu" / reg_key / "articles"
        
        if articles_dir.exists():
            for f in articles_dir.glob("article_*.json"):
                if f.stem in pending_articles:
                    continue
                
                try:
                    data = json.loads(f.read_text(encoding='utf-8'))
                    local_status = get_local_status(data)
                    
                    if local_status["status"] == "APPROVED":
                        reg_stats["approved"] += 1
                        stats["approved"] += 1
                        if local_status.get("observation"):
                            stats["with_observation"] += 1
                    else:
                        reg_stats["placeholder"] += 1
                        stats["placeholder"] += 1
                except Exception as e:
                    print(f"⚠️  Error reading {f}: {e}")
                    reg_stats["placeholder"] += 1
                    stats["placeholder"] += 1
        
        stats["total"] += reg_stats["total"]
        stats["regulations"][reg_key] = reg_stats
    
    return stats


@app.get("/api/articles")
async def get_articles(regulation: Optional[str] = None, status: Optional[str] = None, project_id: Optional[str] = None, limit: int = 500):
    """Get articles with optional filtering. Status from LOCAL files."""
    articles = {}
    regs = [regulation] if regulation else list(REGULATIONS.keys())
    
    for reg_key in regs:
        if reg_key not in REGULATIONS:
            continue
            
        reg_meta = REGULATIONS[reg_key]
        articles_dir = KNOWLEDGE_PATH / "documents/eu" / reg_key / "articles"
        pending_dir = PENDING_PATH / reg_key
        
        # Load pending articles (local)
        if pending_dir.exists():
            for f in sorted(pending_dir.glob("article_*.json")):
                try:
                    data = json.loads(f.read_text(encoding='utf-8'))
                    art_num = data.get("article_number")
                    key = f"{reg_key}_{art_num}"
                    
                    if status and status != "PENDING_REVIEW":
                        continue
                    
                    articles[key] = {
                        "id": data.get("id", key),
                        "regulation": reg_meta["short_name"],
                        "regulation_key": reg_key,
                        "article_number": art_num,
                        "title": data.get("title", f"Article {art_num}"),
                        "content": data.get("content", "")[:500],
                        "status": "PENDING_REVIEW",
                        "content_hash": data.get("content_hash"),
                        "approved_by": None,
                        "source": "pending"
                    }
                except Exception as e:
                    print(f"⚠️  Error reading pending {f}: {e}")
        
        # Load document articles (status from LOCAL eve_metadata)
        if articles_dir.exists():
            for f in sorted(articles_dir.glob("article_*.json")):
                try:
                    data = json.loads(f.read_text(encoding='utf-8'))
                    art_num = data.get("article_number")
                    key = f"{reg_key}_{art_num}"
                    
                    if key in articles:
                        continue
                    
                    # Get status from LOCAL eve_metadata
                    local_status = get_local_status(data)
                    art_status = local_status["status"]
                    approved_by = local_status["approved_by"]
                    
                    if status and art_status != status:
                        continue
                    
                    articles[key] = {
                        "id": data.get("id", key),
                        "regulation": reg_meta["short_name"],
                        "regulation_key": reg_key,
                        "article_number": art_num,
                        "title": data.get("title", f"Article {art_num}"),
                        "content": data.get("content", "")[:500],
                        "status": art_status,
                        "content_hash": data.get("content_hash"),
                        "approved_by": approved_by,
                        "source": "documents"
                    }
                except Exception as e:
                    print(f"⚠️  Error reading {f}: {e}")
    
    result = list(articles.values())
    result.sort(key=lambda x: (x['regulation_key'], int(x['article_number'])))
    
    if project_id:
        result = [a for a in result if a.get('project_id') == project_id]
    
    return result[:limit]


@app.get("/api/articles/{regulation}/{article_number}")
async def get_article(regulation: str, article_number: str):
    """Get single article with full content. Status from LOCAL files."""
    # Check pending first
    pending_path = PENDING_PATH / regulation / f"article_{article_number}.json"
    
    if pending_path.exists():
        data = json.loads(pending_path.read_text(encoding='utf-8'))
        data['_source'] = 'pending'
        data['eve_metadata'] = data.get('eve_metadata', {})
        data['eve_metadata']['status'] = 'PENDING_REVIEW'
        return data
    
    # Check documents
    article_path = KNOWLEDGE_PATH / "documents/eu" / regulation / "articles" / f"article_{article_number}.json"
    
    if article_path.exists():
        data = json.loads(article_path.read_text(encoding='utf-8'))
        data['_source'] = 'documents'
        # Status already in eve_metadata from local file
        return data
    
    raise HTTPException(status_code=404, detail="Article not found")


@app.post("/api/fetch")
async def fetch_articles(request: FetchRequest):
    """Fetch articles from EUR-Lex (local operation)."""
    check_write_allowed()
    
    if request.regulation not in REGULATIONS:
        raise HTTPException(status_code=400, detail=f"Unknown regulation: {request.regulation}")
    
    try:
        result = fetch_regulation_articles(
            regulation=request.regulation,
            articles=request.articles,
            force_refetch=True
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/approve")
async def approve_article(request: ApproveRequest):
    """
    Approve a pending article.
    
    v6.0: Saves locally AND syncs to Trinity cloud.
    """
    check_write_allowed()
    
    pending_file = PENDING_PATH / request.regulation / f"article_{request.article_number}.json"
    
    if not pending_file.exists():
        raise HTTPException(status_code=404, detail="Pending article not found")
    
    try:
        # Read pending article
        article_data = json.loads(pending_file.read_text(encoding='utf-8'))
        
        # Create approval timestamp and signature
        now = datetime.utcnow().isoformat() + "Z"
        content_hash = article_data.get("content_hash", "")
        signature = create_approval_signature(content_hash, request.approved_by, now)
        article_id = f"{request.regulation}_article_{request.article_number}"
        
        # Update local metadata
        article_data['eve_metadata'] = article_data.get('eve_metadata', {})
        article_data['eve_metadata']['status'] = 'APPROVED'
        article_data['eve_metadata']['approved'] = True
        article_data['eve_metadata']['approved_by'] = request.approved_by
        article_data['eve_metadata']['approved_date'] = now
        article_data['eve_metadata']['approval_signature'] = signature
        if request.observation:
            article_data['eve_metadata']['observation'] = request.observation
        
        # Move file from pending to documents
        target_dir = KNOWLEDGE_PATH / "documents/eu" / request.regulation / "articles"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_file = target_dir / f"article_{request.article_number}.json"
        
        # Save to documents
        target_file.write_text(json.dumps(article_data, indent=2, ensure_ascii=False), encoding='utf-8')
        
        # Remove from pending
        pending_file.unlink()
        
        print(f"  ✅ Approved locally: {article_id}")
        
        # Sync to Trinity cloud
        trinity_result = await sync_to_trinity(
            article_id=article_id,
            approved_by=request.approved_by,
            content_hash=content_hash,
            regulation=request.regulation,
            article_number=request.article_number,
            project_id=request.project_id,
            observation=request.observation
        )
        
        return {
            "success": True,
            "article": f"{request.regulation} Article {request.article_number}",
            "approved_by": request.approved_by,
            "approved_date": now,
            "signature": signature,
            "message": "Approved and saved locally",
            "trinity_sync": trinity_result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/reject")
async def reject_article(request: RejectRequest):
    """
    Reject a pending article.
    
    LOCAL MODE: Just removes the pending file.
    """
    check_write_allowed()
    
    pending_file = PENDING_PATH / request.regulation / f"article_{request.article_number}.json"
    
    if not pending_file.exists():
        raise HTTPException(status_code=404, detail="Pending article not found")
    
    try:
        # Remove from pending
        pending_file.unlink()
        
        return {
            "success": True,
            "article": f"{request.regulation} Article {request.article_number}",
            "rejected_by": request.rejected_by,
            "reason": request.reason,
            "message": "Rejected and removed from pending"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# TRINITY STATUS ENDPOINT
# ============================================================

@app.get("/api/trinity/status")
async def trinity_status():
    """Check Trinity connection status."""
    if not TRINITY_ENABLED:
        return {
            "enabled": False,
            "reason": "EVE_TRINITY_API_KEY not set" if not TRINITY_API_KEY else "httpx not installed"
        }
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(f"{TRINITY_API}/api/v1/trinity/approvals/status")
            online = res.status_code == 200
    except:
        online = False
    
    return {
        "enabled": True,
        "online": online,
        "api": TRINITY_API
    }


@app.get("/api/trinity/approvals")
async def get_trinity_knowledge_approvals():
    """Get all knowledge approvals from Trinity cloud."""
    approvals = await get_trinity_approvals()
    return {
        "count": len(approvals),
        "items": list(approvals.values())
    }


# ============================================================
# COMPLIDOCS INTEGRATION (Read-Only)
# ============================================================

@app.get("/api/approved")
async def get_approved_articles(
    regulation: Optional[str] = None,
    articles: Optional[str] = None,
    project_id: Optional[str] = None
):
    """
    Get APPROVED articles only - for ComplieDocs integration.
    
    Approval status is read from LOCAL eve_metadata.
    """
    result = []
    
    article_filter = None
    if articles:
        article_filter = set(articles.split(","))
    
    regs = [regulation] if regulation else list(REGULATIONS.keys())
    
    for reg_key in regs:
        if reg_key not in REGULATIONS:
            continue
            
        reg_meta = REGULATIONS[reg_key]
        articles_dir = KNOWLEDGE_PATH / "documents/eu" / reg_key / "articles"
        
        if not articles_dir.exists():
            continue
        
        for f in sorted(articles_dir.glob("article_*.json")):
            try:
                data = json.loads(f.read_text(encoding='utf-8'))
                art_num = str(data.get("article_number"))
                
                if article_filter and art_num not in article_filter:
                    continue
                
                # Check LOCAL eve_metadata for approval status
                local_status = get_local_status(data)
                
                if local_status["status"] != "APPROVED":
                    continue
                
                result.append({
                    "regulation": reg_meta["short_name"],
                    "regulation_key": reg_key,
                    "article_number": art_num,
                    "title": data.get("title", f"Article {art_num}"),
                    "content": data.get("content", ""),
                    "content_hash": data.get("content_hash"),
                    "status": local_status["status"],
                    "approved_by": local_status["approved_by"],
                    "approved_at": local_status["approved_date"],
                    "observation": local_status.get("observation"),
                    "source_url": data.get("source_url"),
                    "celex": data.get("source_celex")
                })
            except Exception as e:
                print(f"⚠️  Error reading {f}: {e}")
    
    result.sort(key=lambda x: (x['regulation_key'], int(x['article_number'])))
    
    if project_id:
        result = [a for a in result if a.get('project_id') == project_id]
    
    return {
        "count": len(result),
        "source": "EVE Knowledge Base",
        "approval_source": "LOCAL + TRINITY" if TRINITY_ENABLED else "LOCAL",
        "mode": "local",
        "articles": result
    }


# ============================================================
# WITNESS SMART ENDPOINT
# ============================================================

@app.post("/api/witness/smart")
async def witness_smart(request: WitnessSmartRequest):
    """
    Smart Witness Mode — Ask questions about approved knowledge.
    """
    if not WITNESS_SMART_ENABLED:
        raise HTTPException(
            status_code=503, 
            detail="Witness Smart module not loaded. Check server logs."
        )
    
    if not ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY environment variable not set."
        )
    
    try:
        response = await witness_smart_query_async(
            question=request.question,
            knowledge_path=str(KNOWLEDGE_PATH),
            language=request.language,
            regulations=request.regulations
        )
        return response.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        print(f"[ERROR] Witness Smart failed: {e}")
        raise HTTPException(status_code=500, detail=f"Witness query failed: {str(e)}")


@app.get("/api/witness/status")
async def witness_status():
    """Check Witness Smart status and capabilities."""
    return {
        "enabled": WITNESS_SMART_ENABLED,
        "anthropic_api_configured": bool(ANTHROPIC_API_KEY),
        "knowledge_path": str(KNOWLEDGE_PATH),
        "approval_source": "LOCAL + TRINITY" if TRINITY_ENABLED else "LOCAL",
        "capabilities": [
            "question_interpretation",
            "semantic_search",
            "answer_synthesis"
        ] if WITNESS_SMART_ENABLED else [],
        "limitations": [
            "Only answers from APPROVED articles",
            "No legal advice or recommendations",
            "No external knowledge"
        ]
    }


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("🚀 EVE Knowledge API v6.0 (TRINITY SYNC)")
    if TRINITY_ENABLED:
        print("   ☁️  Trinity sync: ENABLED")
        print(f"   📡 API: {TRINITY_API}")
    else:
        print("   ⚠️  Trinity sync: DISABLED (local only)")
    print("=" * 60)
    print(f"UI:           http://127.0.0.1:8002")
    print(f"API:          http://127.0.0.1:8002/api")
    print(f"Witness:      {'✅ Enabled' if WITNESS_SMART_ENABLED else '❌ Disabled'}")
    print(f"Claude API:   {'✅ Configured' if ANTHROPIC_API_KEY else '❌ Not set'}")
    print(f"Read-Only:    {READ_ONLY_MODE}")
    print("=" * 60)
    print()
    
    uvicorn.run(app, host="127.0.0.1", port=8002)
