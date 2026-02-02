#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
EVE VERIFIED STORE
═══════════════════════════════════════════════════════════════════════════════

Central module for creating and managing EVE VERIFIED records.

Witness-kod skapar bevis.       → /witness/ (this is code)
Verified-storage bevarar bevis. → /witness_store/ (this is storage)

This module creates EVEV-* records in witness_store/<domain>/verified/

Usage:
    from verified_store import VerifiedStore
    
    store = VerifiedStore()
    evev_id = store.create_verified_record(
        domain="compliedocs",
        object_type="artifact",
        object_id="access_control_policy",
        content_hash="8779FA4E...",
        trinity_approval_ref="trinity_approvals/artifact/access_control_policy.json",
        xvault_ref="branches/artifact_factory/artifacts/access_control_policy/xvault.json",
        approved_by="joakim",
        approved_role="Compliance Owner"
    )

© 2026 Organiq Sweden AB - Patent Pending
═══════════════════════════════════════════════════════════════════════════════
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, asdict
from enum import Enum


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

WITNESS_STORE_BASE = Path("D:/EVE11/core/V14/witness_store")

# Domain codes (4-char)
DOMAIN_CODES = {
    "compliedocs": "COMP",
    "trading": "TRAD",
    "elekto": "ELEK",
    "medical": "MEDI",
    "finance": "FINA",
    "legal": "LEGL",
}


# ═══════════════════════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════════════════════

class VerifiedStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


@dataclass
class VerifiedRecord:
    """EVE VERIFIED record structure."""
    eve_verified_id: str
    domain: str
    object_type: str  # "artifact", "knowledge", "rule", etc.
    object_id: str
    content_hash: str
    
    # References to source records
    references: Dict[str, str]
    
    # Verification chain
    verification_chain: Dict[str, Any]
    
    # Timestamps
    verified_at: str
    
    # Status
    status: str = "ACTIVE"
    supersedes: Optional[str] = None
    superseded_by: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════════
# SEQUENCE MANAGER
# ═══════════════════════════════════════════════════════════════════════════════

class SequenceManager:
    """Manages EVEV-* sequence numbers per day."""
    
    def __init__(self, base_path: Path):
        self.sequence_file = base_path / ".sequence.json"
        self._ensure_file()
    
    def _ensure_file(self):
        if not self.sequence_file.exists():
            self.sequence_file.parent.mkdir(parents=True, exist_ok=True)
            self._save({})
    
    def _load(self) -> Dict:
        try:
            with open(self.sequence_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    
    def _save(self, data: Dict):
        with open(self.sequence_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    
    def get_next(self, domain_code: str, date_str: str) -> int:
        """Get next sequence number for domain+date."""
        data = self._load()
        key = f"{domain_code}-{date_str}"
        current = data.get(key, 0)
        next_seq = current + 1
        data[key] = next_seq
        self._save(data)
        return next_seq


# ═══════════════════════════════════════════════════════════════════════════════
# VERIFIED STORE
# ═══════════════════════════════════════════════════════════════════════════════

class VerifiedStore:
    """
    Central store for EVE VERIFIED records.
    
    This is the ONLY place that means "EVE VERIFIED".
    If a record exists in witness_store/<domain>/verified/EVEV-*.json, it is verified.
    If not, it is not.
    """
    
    def __init__(self, base_path: Path = WITNESS_STORE_BASE):
        self.base_path = base_path
        self.sequence = SequenceManager(base_path)
        self._ensure_structure()
    
    def _ensure_structure(self):
        """Ensure all domain directories exist."""
        for domain in DOMAIN_CODES.keys():
            domain_path = self.base_path / domain
            (domain_path / "domain_events").mkdir(parents=True, exist_ok=True)
            (domain_path / "trinity_runs").mkdir(parents=True, exist_ok=True)
            (domain_path / "verified").mkdir(parents=True, exist_ok=True)
    
    def _generate_evev_id(self, domain: str) -> str:
        """Generate next EVEV-* ID for domain."""
        domain_code = DOMAIN_CODES.get(domain, domain[:4].upper())
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        seq = self.sequence.get_next(domain_code, date_str)
        return f"EVEV-{domain_code}-{date_str}-{seq:06d}"
    
    def _get_verified_path(self, domain: str) -> Path:
        """Get verified/ path for domain."""
        return self.base_path / domain / "verified"
    
    def create_verified_record(
        self,
        domain: str,
        object_type: str,
        object_id: str,
        content_hash: str,
        trinity_approval_ref: str,
        xvault_ref: str,
        approved_by: str,
        approved_role: str = "Approver",
        trinity_decision_id: Optional[str] = None,
        xvault_hash: Optional[str] = None,
        human_audit_ref: Optional[str] = None,
        supersedes: Optional[str] = None,
        extra_metadata: Optional[Dict] = None
    ) -> str:
        """
        Create a new EVE VERIFIED record.
        
        This is called AFTER:
        1. Trinity approval exists
        2. X-Vault seal exists
        3. Human signoff is confirmed
        
        Returns the EVEV-* ID.
        """
        # Generate ID
        evev_id = self._generate_evev_id(domain)
        
        # Build references
        references = {
            "trinity_approval": trinity_approval_ref,
            "xvault_seal": xvault_ref,
        }
        if human_audit_ref:
            references["human_audit"] = human_audit_ref
        
        # Build verification chain
        verification_chain = {
            "trinity_decision_id": trinity_decision_id,
            "xvault_hash": xvault_hash or content_hash,
            "human_signoff": True,
            "signoff_by": approved_by,
            "signoff_role": approved_role,
        }
        
        # Create record
        record = VerifiedRecord(
            eve_verified_id=evev_id,
            domain=domain,
            object_type=object_type,
            object_id=object_id,
            content_hash=content_hash,
            references=references,
            verification_chain=verification_chain,
            verified_at=datetime.now(timezone.utc).isoformat(),
            status="ACTIVE",
            supersedes=supersedes,
        )
        
        # Add extra metadata if provided
        record_dict = record.to_dict()
        if extra_metadata:
            record_dict["metadata"] = extra_metadata
        
        # Handle supersede
        if supersedes:
            self._mark_superseded(domain, supersedes, evev_id)
        
        # Write to file
        verified_path = self._get_verified_path(domain)
        record_file = verified_path / f"{evev_id}.json"
        
        with open(record_file, 'w', encoding='utf-8') as f:
            json.dump(record_dict, f, indent=2, ensure_ascii=False)
        
        print(f"✅ EVE VERIFIED: {evev_id}")
        print(f"   Object: {object_type}/{object_id}")
        print(f"   Domain: {domain}")
        print(f"   Signed by: {approved_by} ({approved_role})")
        
        return evev_id
    
    def _mark_superseded(self, domain: str, old_evev_id: str, new_evev_id: str):
        """Mark an old record as superseded."""
        verified_path = self._get_verified_path(domain)
        old_file = verified_path / f"{old_evev_id}.json"
        
        if old_file.exists():
            with open(old_file, 'r', encoding='utf-8') as f:
                old_record = json.load(f)
            
            old_record["status"] = "SUPERSEDED"
            old_record["superseded_by"] = new_evev_id
            old_record["superseded_at"] = datetime.now(timezone.utc).isoformat()
            
            with open(old_file, 'w', encoding='utf-8') as f:
                json.dump(old_record, f, indent=2, ensure_ascii=False)
            
            print(f"   Superseded: {old_evev_id}")
    
    def get_verified_record(self, evev_id: str) -> Optional[Dict]:
        """Get a verified record by EVEV ID."""
        # Parse domain from ID: EVEV-COMP-20260122-000001
        parts = evev_id.split("-")
        if len(parts) < 4:
            return None
        
        domain_code = parts[1]
        
        # Find domain by code
        domain = None
        for d, code in DOMAIN_CODES.items():
            if code == domain_code:
                domain = d
                break
        
        if not domain:
            # Try all domains
            for d in DOMAIN_CODES.keys():
                record_file = self._get_verified_path(d) / f"{evev_id}.json"
                if record_file.exists():
                    with open(record_file, 'r', encoding='utf-8') as f:
                        return json.load(f)
            return None
        
        record_file = self._get_verified_path(domain) / f"{evev_id}.json"
        if record_file.exists():
            with open(record_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        return None
    
    def get_verified_by_object(self, domain: str, object_id: str) -> Optional[Dict]:
        """Get the ACTIVE verified record for an object."""
        verified_path = self._get_verified_path(domain)
        
        if not verified_path.exists():
            return None
        
        # Find record with matching object_id and ACTIVE status
        for record_file in verified_path.glob("EVEV-*.json"):
            with open(record_file, 'r', encoding='utf-8') as f:
                record = json.load(f)
            
            if record.get("object_id") == object_id and record.get("status") == "ACTIVE":
                return record
        
        return None
    
    def list_verified(
        self,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        object_type: Optional[str] = None
    ) -> List[Dict]:
        """List verified records with optional filters."""
        results = []
        
        domains = [domain] if domain else list(DOMAIN_CODES.keys())
        
        for d in domains:
            verified_path = self._get_verified_path(d)
            if not verified_path.exists():
                continue
            
            for record_file in sorted(verified_path.glob("EVEV-*.json"), reverse=True):
                with open(record_file, 'r', encoding='utf-8') as f:
                    record = json.load(f)
                
                # Apply filters
                if status and record.get("status") != status:
                    continue
                if object_type and record.get("object_type") != object_type:
                    continue
                
                results.append(record)
        
        return results
    
    def verify_integrity(self, evev_id: str) -> Dict:
        """Verify integrity of an EVEV record."""
        record = self.get_verified_record(evev_id)
        
        if not record:
            return {
                "valid": False,
                "evev_id": evev_id,
                "error": "Record not found"
            }
        
        checks = {
            "record_exists": True,
            "has_trinity_ref": bool(record.get("references", {}).get("trinity_approval")),
            "has_xvault_ref": bool(record.get("references", {}).get("xvault_seal")),
            "has_human_signoff": record.get("verification_chain", {}).get("human_signoff", False),
            "has_content_hash": bool(record.get("content_hash")),
            "status": record.get("status"),
        }
        
        all_valid = all([
            checks["record_exists"],
            checks["has_trinity_ref"],
            checks["has_xvault_ref"],
            checks["has_human_signoff"],
            checks["has_content_hash"],
        ])
        
        return {
            "valid": all_valid,
            "evev_id": evev_id,
            "checks": checks,
            "verified_at": record.get("verified_at"),
            "object_id": record.get("object_id"),
            "domain": record.get("domain"),
        }
    
    def get_statistics(self) -> Dict:
        """Get statistics about verified records."""
        stats = {
            "total": 0,
            "by_domain": {},
            "by_status": {"ACTIVE": 0, "SUPERSEDED": 0},
            "by_object_type": {},
        }
        
        for domain in DOMAIN_CODES.keys():
            verified_path = self._get_verified_path(domain)
            if not verified_path.exists():
                continue
            
            domain_count = 0
            
            for record_file in verified_path.glob("EVEV-*.json"):
                with open(record_file, 'r', encoding='utf-8') as f:
                    record = json.load(f)
                
                stats["total"] += 1
                domain_count += 1
                
                status = record.get("status", "ACTIVE")
                stats["by_status"][status] = stats["by_status"].get(status, 0) + 1
                
                obj_type = record.get("object_type", "unknown")
                stats["by_object_type"][obj_type] = stats["by_object_type"].get(obj_type, 0) + 1
            
            if domain_count > 0:
                stats["by_domain"][domain] = domain_count
        
        return stats


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def create_verified_for_artifact(
    artifact_id: str,
    content_hash: str,
    approved_by: str,
    approved_role: str = "Compliance Owner",
    xvault_path: Optional[str] = None,
    trinity_approval_path: Optional[str] = None,
) -> str:
    """
    Convenience function to create EVEV record for a ComplieDocs artifact.
    
    Call this after successful artifact approval + seal.
    """
    store = VerifiedStore()
    
    # Default paths
    if not xvault_path:
        xvault_path = f"branches/artifact_factory/artifacts/{artifact_id}/xvault.json"
    if not trinity_approval_path:
        trinity_approval_path = f"trinity_approvals/artifact/{artifact_id}.json"
    
    evev_id = store.create_verified_record(
        domain="compliedocs",
        object_type="artifact",
        object_id=artifact_id,
        content_hash=content_hash,
        trinity_approval_ref=trinity_approval_path,
        xvault_ref=xvault_path,
        approved_by=approved_by,
        approved_role=approved_role,
        human_audit_ref="Projects/002_EVE_Control_Room/eve/logs/artifact_audit.log",
    )
    
    return evev_id


def is_verified(domain: str, object_id: str) -> bool:
    """Check if an object is EVE VERIFIED (has ACTIVE record)."""
    store = VerifiedStore()
    record = store.get_verified_by_object(domain, object_id)
    return record is not None


# ═══════════════════════════════════════════════════════════════════════════════
# CLI / TESTING
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print("  EVE VERIFIED STORE")
    print("=" * 70)
    
    store = VerifiedStore()
    stats = store.get_statistics()
    
    print(f"\n📊 Statistics:")
    print(f"   Total records: {stats['total']}")
    print(f"   By status: {stats['by_status']}")
    print(f"   By domain: {stats['by_domain']}")
    print(f"   By type: {stats['by_object_type']}")
    
    print(f"\n📁 Storage location: {WITNESS_STORE_BASE}")
    print()
    
    # Test: list recent
    records = store.list_verified(status="ACTIVE")
    if records:
        print(f"📜 Recent ACTIVE records ({len(records)}):")
        for r in records[:5]:
            print(f"   {r['eve_verified_id']} | {r['object_type']}/{r['object_id']}")
    else:
        print("📜 No verified records yet.")
    
    print()
    print("=" * 70)
