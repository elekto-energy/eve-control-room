"""
EVE Artifact Model
==================
Kanonisk datamodell för artifacts i EVE-ekosystemet.

State Machine:
    draft → submitted → approved → verified → superseded

Invarianter:
    - verified kräver approval_id OCH snapshot_id
    - approved kräver approval_id
    - submitted kräver content_hash
    - superseded kräver superseded_by

Version: 1.0.0
Status: FROZEN
Datum: 2026-01-24
"""

import hashlib
import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Dict, Optional, List, Any
from enum import Enum
from uuid import uuid4


class ArtifactType(Enum):
    """Typer av artifacts som kan verifieras"""
    KNOWLEDGE = "knowledge"     # Juridisk/regulatorisk kunskap
    RULE = "rule"               # Affärsregel/constraint
    TEMPLATE = "template"       # Dokumentmall
    CODE = "code"               # Verifierad kodartefakt
    WORKFLOW = "workflow"       # Verifierat arbetsflöde


class ArtifactStatus(Enum):
    """
    Artifact lifecycle states.
    
    State Machine (strikt, ingen bakåtgång):
    
        draft → submitted → approved → verified
                                           ↓
                                      superseded
    """
    DRAFT = "draft"             # Skapad, ej inskickad
    SUBMITTED = "submitted"     # Inskickad för granskning
    APPROVED = "approved"       # FAS 5: Godkänd av approver
    VERIFIED = "verified"       # FAS 6: Förseglad i X-Vault
    SUPERSEDED = "superseded"   # Ersatt av nyare version
    REVOKED = "revoked"         # Återkallad (sällsynt)


# Tillåtna tillståndsövergångar
VALID_TRANSITIONS = {
    ArtifactStatus.DRAFT: [ArtifactStatus.SUBMITTED],
    ArtifactStatus.SUBMITTED: [ArtifactStatus.APPROVED],
    ArtifactStatus.APPROVED: [ArtifactStatus.VERIFIED],
    ArtifactStatus.VERIFIED: [ArtifactStatus.SUPERSEDED, ArtifactStatus.REVOKED],
    ArtifactStatus.SUPERSEDED: [],  # Terminal
    ArtifactStatus.REVOKED: [],     # Terminal
}


@dataclass
class ArtifactSource:
    """Spårbarhet: Var kom artifact ifrån?"""
    origin: str                     # EVE_CONTROL_ROOM, EXTERNAL, MIGRATION
    author: str                     # Email eller user ID
    created_at: str                 # ISO8601
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'ArtifactSource':
        return cls(**d)


@dataclass
class ApprovalRef:
    """Referens till godkännande (FAS 5)"""
    approval_id: str
    approver_id: str
    approver_name: str
    role: str
    timestamp: str
    signature: str
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'ApprovalRef':
        return cls(**d)


@dataclass
class XVaultRef:
    """Referens till X-Vault evidence (FAS 5 + FAS 6)"""
    authorization_evidence_id: Optional[str] = None  # FAS 5: Approve
    snapshot_id: Optional[str] = None                # FAS 6: Seal
    merkle_root: Optional[str] = None                # FAS 6: Seal
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'XVaultRef':
        return cls(**d)


@dataclass
class Lineage:
    """Versionshistorik för supersede-hantering"""
    previous_versions: List[str] = field(default_factory=list)
    superseded_by: Optional[str] = None
    supersede_reason: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'Lineage':
        return cls(**d)


@dataclass
class Artifact:
    """
    Kanonisk artifact i EVE-ekosystemet.
    
    Livscykel:
    1. Control Room skapar artifact (draft)
    2. Submit till eveverified.com (submitted)
    3. Approver godkänner (approved) - FAS 5
    4. System förseglar (verified) - FAS 6
    5. Vid uppdatering: supersede (superseded) - FAS 8
    
    Invarianter (enforced):
    - VERIFIED kräver approval + snapshot
    - APPROVED kräver approval
    - SUBMITTED kräver content_hash
    - Ingen bakåtgång i state machine
    """
    # Identitet
    artifact_id: str
    type: ArtifactType
    version: str
    title: str
    
    # Innehåll
    content: Dict[str, Any]
    content_hash: str
    
    # Status
    status: ArtifactStatus
    
    # Spårbarhet
    source: ArtifactSource
    
    # Godkännande (None tills approved)
    approval: Optional[ApprovalRef] = None
    
    # X-Vault (None tills sealed)
    x_vault: Optional[XVaultRef] = None
    
    # Versionshistorik
    lineage: Lineage = field(default_factory=Lineage)
    
    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    verified_at: Optional[str] = None
    
    def to_dict(self) -> Dict:
        d = {
            'artifact_id': self.artifact_id,
            'type': self.type.value,
            'version': self.version,
            'title': self.title,
            'content': self.content,
            'content_hash': self.content_hash,
            'status': self.status.value,
            'source': self.source.to_dict(),
            'approval': self.approval.to_dict() if self.approval else None,
            'x_vault': self.x_vault.to_dict() if self.x_vault else None,
            'lineage': self.lineage.to_dict(),
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'verified_at': self.verified_at
        }
        return d
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'Artifact':
        return cls(
            artifact_id=d['artifact_id'],
            type=ArtifactType(d['type']),
            version=d['version'],
            title=d['title'],
            content=d['content'],
            content_hash=d['content_hash'],
            status=ArtifactStatus(d['status']),
            source=ArtifactSource.from_dict(d['source']),
            approval=ApprovalRef.from_dict(d['approval']) if d.get('approval') else None,
            x_vault=XVaultRef.from_dict(d['x_vault']) if d.get('x_vault') else None,
            lineage=Lineage.from_dict(d.get('lineage', {})),
            created_at=d.get('created_at', ''),
            updated_at=d.get('updated_at', ''),
            verified_at=d.get('verified_at')
        )
    
    def can_transition_to(self, new_status: ArtifactStatus) -> bool:
        """Kontrollera om övergång är tillåten"""
        return new_status in VALID_TRANSITIONS.get(self.status, [])
    
    def validate_invariants(self) -> List[str]:
        """
        Validera alla invarianter.
        Returnerar lista med fel (tom om OK).
        """
        errors = []
        
        # SUBMITTED kräver content_hash
        if self.status in [ArtifactStatus.SUBMITTED, ArtifactStatus.APPROVED, 
                           ArtifactStatus.VERIFIED, ArtifactStatus.SUPERSEDED]:
            if not self.content_hash:
                errors.append("SUBMITTED+ kräver content_hash")
        
        # APPROVED kräver approval
        if self.status in [ArtifactStatus.APPROVED, ArtifactStatus.VERIFIED, 
                           ArtifactStatus.SUPERSEDED]:
            if not self.approval:
                errors.append("APPROVED+ kräver approval")
            elif not self.approval.approval_id:
                errors.append("APPROVED+ kräver approval.approval_id")
        
        # VERIFIED kräver x_vault med snapshot
        if self.status in [ArtifactStatus.VERIFIED, ArtifactStatus.SUPERSEDED]:
            if not self.x_vault:
                errors.append("VERIFIED+ kräver x_vault")
            elif not self.x_vault.snapshot_id:
                errors.append("VERIFIED+ kräver x_vault.snapshot_id")
            elif not self.x_vault.merkle_root:
                errors.append("VERIFIED+ kräver x_vault.merkle_root")
            if not self.verified_at:
                errors.append("VERIFIED+ kräver verified_at")
        
        # SUPERSEDED kräver superseded_by
        if self.status == ArtifactStatus.SUPERSEDED:
            if not self.lineage.superseded_by:
                errors.append("SUPERSEDED kräver lineage.superseded_by")
        
        return errors


class ArtifactFactory:
    """Factory för att skapa artifacts korrekt"""
    
    @staticmethod
    def create_draft(
        artifact_type: ArtifactType,
        title: str,
        content: Dict[str, Any],
        version: str,
        author: str,
        origin: str = "EVE_CONTROL_ROOM"
    ) -> Artifact:
        """Skapa ny draft artifact"""
        artifact_id = f"{artifact_type.value.upper()}-{datetime.now().year}-{uuid4().hex[:6].upper()}"
        
        content_hash = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        
        return Artifact(
            artifact_id=artifact_id,
            type=artifact_type,
            version=version,
            title=title,
            content=content,
            content_hash=f"sha256:{content_hash}",
            status=ArtifactStatus.DRAFT,
            source=ArtifactSource(
                origin=origin,
                author=author,
                created_at=datetime.now(timezone.utc).isoformat()
            )
        )
    
    @staticmethod
    def compute_content_hash(content: Dict) -> str:
        """Beräkna content hash"""
        h = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return f"sha256:{h}"


# =============================================================================
# INVARIANT TESTS
# =============================================================================
def test_state_machine():
    """Testa state machine invarianter"""
    print("Testing state machine invariants...")
    
    # Skapa draft
    artifact = ArtifactFactory.create_draft(
        artifact_type=ArtifactType.KNOWLEDGE,
        title="Test Artifact",
        content={"body": "test"},
        version="v1",
        author="test@example.com"
    )
    
    assert artifact.status == ArtifactStatus.DRAFT
    assert artifact.can_transition_to(ArtifactStatus.SUBMITTED)
    assert not artifact.can_transition_to(ArtifactStatus.VERIFIED)  # Ej direkt!
    
    # Draft → Submitted
    artifact.status = ArtifactStatus.SUBMITTED
    errors = artifact.validate_invariants()
    assert len(errors) == 0, f"Unexpected errors: {errors}"
    
    # Submitted → Approved (utan approval = FEL)
    artifact.status = ArtifactStatus.APPROVED
    errors = artifact.validate_invariants()
    assert "APPROVED+ kräver approval" in errors
    
    # Lägg till approval
    artifact.approval = ApprovalRef(
        approval_id="test-approval",
        approver_id="key:test",
        approver_name="Test User",
        role="legal_reviewer",
        timestamp=datetime.now(timezone.utc).isoformat(),
        signature="abc123"
    )
    artifact.x_vault = XVaultRef(authorization_evidence_id="ev-123")
    errors = artifact.validate_invariants()
    assert len(errors) == 0, f"Unexpected errors: {errors}"
    
    # Approved → Verified (utan snapshot = FEL)
    artifact.status = ArtifactStatus.VERIFIED
    errors = artifact.validate_invariants()
    assert "VERIFIED+ kräver x_vault.snapshot_id" in errors
    
    # Lägg till snapshot
    artifact.x_vault.snapshot_id = "snap-123"
    artifact.x_vault.merkle_root = "merkle-abc"
    artifact.verified_at = datetime.now(timezone.utc).isoformat()
    errors = artifact.validate_invariants()
    assert len(errors) == 0, f"Unexpected errors: {errors}"
    
    print("✅ All state machine invariants passed")


def test_no_backward_transitions():
    """Testa att bakåtgång ej är tillåten"""
    print("Testing no backward transitions...")
    
    for status, allowed in VALID_TRANSITIONS.items():
        # Kontrollera att ingen tillåten övergång går bakåt
        status_order = [
            ArtifactStatus.DRAFT,
            ArtifactStatus.SUBMITTED,
            ArtifactStatus.APPROVED,
            ArtifactStatus.VERIFIED
        ]
        
        if status in status_order:
            current_idx = status_order.index(status)
            for allowed_status in allowed:
                if allowed_status in status_order:
                    allowed_idx = status_order.index(allowed_status)
                    assert allowed_idx > current_idx, \
                        f"Backward transition allowed: {status} → {allowed_status}"
    
    print("✅ No backward transitions allowed")


if __name__ == "__main__":
    test_state_machine()
    test_no_backward_transitions()
    
    print("\n" + "="*50)
    print("ARTIFACT MODEL: ALL INVARIANTS VERIFIED")
    print("="*50)
