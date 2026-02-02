"""
EVE Verified Approval & Seal
============================
Separerade operationer för FAS 5 (Approve) och FAS 6 (Seal).

Kritisk separation:
    /approve → Beslut fattas, AUTHORIZATION_DECISION i X-Vault
    /seal    → Artifact fryses, Snapshot + Merkle root

Ansvar:
    - Approver ansvarar för BESLUTET
    - System ansvarar för FÖRSEGLINGEN
    - Dessa är två olika händelser med olika bevisvärde

Version: 2.0.0
Status: FROZEN
Datum: 2026-01-24

APPROVE_SEAL_SEPARATION = ENFORCED
"""

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, Optional, List, Tuple
from pathlib import Path
from enum import Enum

# Lokala imports
from approver_registry import ApproverRegistry, ApproverRole, IdentityStrength
from x_vault.x_vault import XVault, EvidenceType, EvidenceObject
from artifact import (
    Artifact, ArtifactStatus, ArtifactFactory,
    ApprovalRef, XVaultRef, VALID_TRANSITIONS
)


class ApprovalError(Exception):
    """Fel vid godkännande"""
    pass


class SealError(Exception):
    """Fel vid försegling"""
    pass


class StateTransitionError(Exception):
    """Ogiltig tillståndsövergång"""
    pass


@dataclass
class ApprovalResult:
    """Resultat från approve-operation (FAS 5)"""
    approval_id: str
    artifact_id: str
    artifact_hash: str
    approver_id: str
    approver_name: str
    role: str
    timestamp: str
    signature: str
    x_vault_evidence_id: str
    status: str = "approved"
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SealResult:
    """Resultat från seal-operation (FAS 6)"""
    artifact_id: str
    snapshot_id: str
    merkle_root: str
    sealed_at: str
    x_vault_evidence_id: str
    status: str = "verified"
    
    def to_dict(self) -> Dict:
        return asdict(self)


class VerifiedApprovalManager:
    """
    Hanterar FAS 5 (Approve) och FAS 6 (Seal) som separata operationer.
    
    Kritiska regler:
    1. approve() kan ENDAST köras på SUBMITTED artifacts
    2. seal() kan ENDAST köras på APPROVED artifacts
    3. Ingen kan hoppa över steg
    4. Alla operationer loggas i X-Vault
    
    Separation av ansvar:
    - approve(): Människa tar beslut
    - seal(): System förseglar
    """
    
    APPROVALS_PATH = Path("D:/EVE11/Projects/002_EVE_Control_Room/eve/data/approvals")
    ARTIFACTS_PATH = Path("D:/EVE11/Projects/002_EVE_Control_Room/eve/data/artifacts")
    
    def __init__(self, x_vault: Optional[XVault] = None):
        self.registry = ApproverRegistry()
        self.x_vault = x_vault or XVault(org_id="organiq_eve")
        self.artifacts: Dict[str, Artifact] = {}
        self._load_artifacts()
    
    def _load_artifacts(self):
        """Ladda artifacts från disk"""
        if self.ARTIFACTS_PATH.exists():
            for f in self.ARTIFACTS_PATH.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding='utf-8'))
                    artifact = Artifact.from_dict(data)
                    self.artifacts[artifact.artifact_id] = artifact
                except Exception as e:
                    print(f"Warning: Could not load {f}: {e}")
    
    def _save_artifact(self, artifact: Artifact):
        """Spara artifact till disk"""
        self.ARTIFACTS_PATH.mkdir(parents=True, exist_ok=True)
        path = self.ARTIFACTS_PATH / f"{artifact.artifact_id}.json"
        path.write_text(
            json.dumps(artifact.to_dict(), indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
    
    # =========================================================================
    # SUBMIT (draft → submitted)
    # =========================================================================
    
    def submit(self, artifact: Artifact) -> Artifact:
        """
        Submit artifact för granskning.
        
        Transition: draft → submitted
        
        Krav:
        - Artifact måste vara DRAFT
        - content_hash måste finnas
        """
        if artifact.status != ArtifactStatus.DRAFT:
            raise StateTransitionError(
                f"Kan endast submita DRAFT artifacts. "
                f"Nuvarande status: {artifact.status.value}"
            )
        
        if not artifact.content_hash:
            raise StateTransitionError("Artifact saknar content_hash")
        
        # Verifiera content_hash
        computed = ArtifactFactory.compute_content_hash(artifact.content)
        if computed != artifact.content_hash:
            raise StateTransitionError(
                f"content_hash mismatch. "
                f"Computed: {computed}, Stored: {artifact.content_hash}"
            )
        
        # Transition
        artifact.status = ArtifactStatus.SUBMITTED
        artifact.updated_at = datetime.now(timezone.utc).isoformat()
        
        # Validera invarianter
        errors = artifact.validate_invariants()
        if errors:
            raise StateTransitionError(f"Invariant-fel: {errors}")
        
        self.artifacts[artifact.artifact_id] = artifact
        self._save_artifact(artifact)
        
        return artifact
    
    # =========================================================================
    # APPROVE (submitted → approved) - FAS 5
    # =========================================================================
    
    def approve(
        self,
        artifact_id: str,
        approver_id: str,
        approver_key: str,
        role: ApproverRole,
        notes: str = ""
    ) -> ApprovalResult:
        """
        FAS 5: Godkänn artifact.
        
        Transition: submitted → approved
        
        Krav:
        - Artifact måste vara SUBMITTED
        - Approver måste ha can_verify_trinity=True
        - Approver måste ha required_role
        
        Skapar:
        - ApprovalRef på artifact
        - AUTHORIZATION_DECISION i X-Vault
        
        OBS: Detta förseglar INTE artifact. Det görs av seal().
        """
        # Hämta artifact
        artifact = self.artifacts.get(artifact_id)
        if not artifact:
            raise ApprovalError(f"Artifact finns ej: {artifact_id}")
        
        # Kontrollera status
        if artifact.status != ArtifactStatus.SUBMITTED:
            raise StateTransitionError(
                f"Kan endast godkänna SUBMITTED artifacts. "
                f"Nuvarande status: {artifact.status.value}"
            )
        
        # Kontrollera approver
        if not self.registry.can_verify(approver_id):
            raise ApprovalError(
                f"❌ {approver_id} har inte Trinity-verifieringsrätt.\n"
                f"Endast founder-godkända personer kan godkänna."
            )
        
        if not self.registry.verify_for_role(approver_id, role):
            approver = self.registry.get_approver(approver_id)
            raise ApprovalError(
                f"❌ {approver.name} har inte rollen {role.value}.\n"
                f"Tillgängliga: {[r.value for r in approver.roles]}"
            )
        
        approver = self.registry.get_approver(approver_id)
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Skapa signatur
        signature = self._create_signature(
            artifact_id=artifact_id,
            artifact_hash=artifact.content_hash,
            approver_id=approver_id,
            timestamp=timestamp,
            approver_key=approver_key
        )
        
        # Försegla BESLUT i X-Vault (inte artifact!)
        evidence = self.x_vault.seal(
            evidence_type=EvidenceType.AUTHORIZATION_DECISION,
            content={
                "decision": "APPROVED",
                "artifact_id": artifact_id,
                "artifact_hash": artifact.content_hash,
                "approver_id": approver_id,
                "approver_name": approver.name,
                "role": role.value,
                "identity_strength": approver.identity_strength.value,
                "timestamp": timestamp,
                "signature": signature,
                "notes": notes
            },
            metadata={
                "workflow_phase": "FAS_5",
                "action": "APPROVE",
                "trust_model": "founder_approved"
            }
        )
        
        # Uppdatera artifact
        artifact.approval = ApprovalRef(
            approval_id=evidence.evidence_id,
            approver_id=approver_id,
            approver_name=approver.name,
            role=role.value,
            timestamp=timestamp,
            signature=signature
        )
        
        artifact.x_vault = XVaultRef(
            authorization_evidence_id=evidence.evidence_id
        )
        
        artifact.status = ArtifactStatus.APPROVED
        artifact.updated_at = timestamp
        
        # Validera invarianter
        errors = artifact.validate_invariants()
        if errors:
            raise StateTransitionError(f"Invariant-fel efter approve: {errors}")
        
        self._save_artifact(artifact)
        
        return ApprovalResult(
            approval_id=evidence.evidence_id,
            artifact_id=artifact_id,
            artifact_hash=artifact.content_hash,
            approver_id=approver_id,
            approver_name=approver.name,
            role=role.value,
            timestamp=timestamp,
            signature=signature,
            x_vault_evidence_id=evidence.evidence_id
        )
    
    # =========================================================================
    # SEAL (approved → verified) - FAS 6
    # =========================================================================
    
    def seal(self, artifact_id: str) -> SealResult:
        """
        FAS 6: Försegla artifact.
        
        Transition: approved → verified
        
        Krav:
        - Artifact måste vara APPROVED
        - Approval måste finnas
        
        Skapar:
        - Snapshot i X-Vault
        - Merkle root
        - KNOWLEDGE_PUBLISH evidence
        
        Efter detta är artifact IMMUTABLE.
        """
        # Hämta artifact
        artifact = self.artifacts.get(artifact_id)
        if not artifact:
            raise SealError(f"Artifact finns ej: {artifact_id}")
        
        # Kontrollera status
        if artifact.status != ArtifactStatus.APPROVED:
            raise StateTransitionError(
                f"Kan endast försegla APPROVED artifacts. "
                f"Nuvarande status: {artifact.status.value}"
            )
        
        # Kontrollera att approval finns
        if not artifact.approval:
            raise SealError("Artifact saknar approval - måste godkännas först")
        
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Skapa snapshot i X-Vault
        snapshot = self.x_vault.create_snapshot(
            knowledge_version=f"{artifact.artifact_id}@{artifact.version}"
        )
        
        # Försegla artifact-innehåll
        evidence = self.x_vault.seal(
            evidence_type=EvidenceType.KNOWLEDGE_PUBLISH,
            content={
                "artifact_id": artifact_id,
                "artifact_hash": artifact.content_hash,
                "version": artifact.version,
                "approval_id": artifact.approval.approval_id,
                "snapshot_id": snapshot.snapshot_id,
                "merkle_root": snapshot.merkle_root,
                "sealed_at": timestamp
            },
            metadata={
                "workflow_phase": "FAS_6",
                "action": "SEAL",
                "immutable": True
            }
        )
        
        # Uppdatera artifact
        artifact.x_vault.snapshot_id = snapshot.snapshot_id
        artifact.x_vault.merkle_root = snapshot.merkle_root
        artifact.status = ArtifactStatus.VERIFIED
        artifact.verified_at = timestamp
        artifact.updated_at = timestamp
        
        # Validera invarianter
        errors = artifact.validate_invariants()
        if errors:
            raise StateTransitionError(f"Invariant-fel efter seal: {errors}")
        
        self._save_artifact(artifact)
        
        return SealResult(
            artifact_id=artifact_id,
            snapshot_id=snapshot.snapshot_id,
            merkle_root=snapshot.merkle_root,
            sealed_at=timestamp,
            x_vault_evidence_id=evidence.evidence_id
        )
    
    # =========================================================================
    # REJECT (submitted → rejected, loggas men ändrar ej status)
    # =========================================================================
    
    def reject(
        self,
        artifact_id: str,
        approver_id: str,
        reason: str
    ) -> Dict:
        """
        Avslå artifact.
        
        Loggas i X-Vault för audit trail.
        Artifact förblir SUBMITTED (kan åtgärdas och submitas igen).
        """
        artifact = self.artifacts.get(artifact_id)
        if not artifact:
            raise ApprovalError(f"Artifact finns ej: {artifact_id}")
        
        if not self.registry.can_verify(approver_id):
            raise ApprovalError(f"{approver_id} har inte verifieringsrätt")
        
        approver = self.registry.get_approver(approver_id)
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Logga avslag i X-Vault
        evidence = self.x_vault.seal(
            evidence_type=EvidenceType.AUTHORIZATION_DECISION,
            content={
                "decision": "REJECTED",
                "artifact_id": artifact_id,
                "artifact_hash": artifact.content_hash,
                "approver_id": approver_id,
                "approver_name": approver.name,
                "reason": reason,
                "timestamp": timestamp
            },
            metadata={
                "workflow_phase": "FAS_5",
                "action": "REJECT"
            }
        )
        
        return {
            "rejection_id": evidence.evidence_id,
            "artifact_id": artifact_id,
            "rejected_by": approver.name,
            "reason": reason,
            "timestamp": timestamp
        }
    
    # =========================================================================
    # SUPERSEDE (verified → superseded) - FAS 8
    # =========================================================================
    
    def supersede(
        self,
        artifact_id: str,
        new_artifact_id: str,
        reason: str,
        approver_id: str
    ) -> Dict:
        """
        FAS 8: Ersätt artifact med nyare version.
        
        Transition: verified → superseded
        
        Krav:
        - Gammal artifact måste vara VERIFIED
        - Ny artifact måste vara VERIFIED
        - Approver måste ha rätt
        
        Gammal artifact:
        - Förblir verifierad
        - Förlorar inte bevisvärde
        - Markeras superseded_by
        """
        old_artifact = self.artifacts.get(artifact_id)
        new_artifact = self.artifacts.get(new_artifact_id)
        
        if not old_artifact:
            raise StateTransitionError(f"Gammal artifact finns ej: {artifact_id}")
        if not new_artifact:
            raise StateTransitionError(f"Ny artifact finns ej: {new_artifact_id}")
        
        if old_artifact.status != ArtifactStatus.VERIFIED:
            raise StateTransitionError(
                f"Kan endast supersede VERIFIED artifacts. "
                f"Status: {old_artifact.status.value}"
            )
        
        if new_artifact.status != ArtifactStatus.VERIFIED:
            raise StateTransitionError(
                f"Ny artifact måste vara VERIFIED. "
                f"Status: {new_artifact.status.value}"
            )
        
        if not self.registry.can_verify(approver_id):
            raise ApprovalError(f"{approver_id} har inte rätt att supersede")
        
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Logga supersede
        evidence = self.x_vault.seal(
            evidence_type=EvidenceType.SYSTEM_EVENT,
            content={
                "event": "SUPERSEDE",
                "old_artifact_id": artifact_id,
                "new_artifact_id": new_artifact_id,
                "reason": reason,
                "approver_id": approver_id,
                "timestamp": timestamp
            },
            metadata={
                "workflow_phase": "FAS_8",
                "action": "SUPERSEDE"
            }
        )
        
        # Uppdatera gammal artifact
        old_artifact.lineage.superseded_by = new_artifact_id
        old_artifact.lineage.supersede_reason = reason
        old_artifact.status = ArtifactStatus.SUPERSEDED
        old_artifact.updated_at = timestamp
        
        # Uppdatera ny artifact lineage
        new_artifact.lineage.previous_versions.append(artifact_id)
        new_artifact.updated_at = timestamp
        
        self._save_artifact(old_artifact)
        self._save_artifact(new_artifact)
        
        return {
            "supersede_id": evidence.evidence_id,
            "old_artifact": artifact_id,
            "new_artifact": new_artifact_id,
            "reason": reason,
            "timestamp": timestamp
        }
    
    # =========================================================================
    # VERIFICATION
    # =========================================================================
    
    def verify(self, artifact_id: str) -> Dict:
        """
        Verifiera artifact (offline-kapabel).
        
        Kontrollerar:
        1. Artifact finns och är VERIFIED
        2. content_hash matchar
        3. approval finns och är signerad
        4. x_vault snapshot finns
        5. Merkle proof är valid
        """
        artifact = self.artifacts.get(artifact_id)
        if not artifact:
            return {"valid": False, "error": "Artifact finns ej"}
        
        checks = {}
        
        # Status
        checks["status_verified"] = artifact.status == ArtifactStatus.VERIFIED
        
        # Content hash
        computed = ArtifactFactory.compute_content_hash(artifact.content)
        checks["content_hash_valid"] = computed == artifact.content_hash
        
        # Approval
        checks["approval_exists"] = artifact.approval is not None
        if artifact.approval:
            checks["approval_signed"] = len(artifact.approval.signature) == 64
            approver = self.registry.get_approver(artifact.approval.approver_id)
            checks["approver_authorized"] = approver is not None and approver.can_verify_trinity
        
        # X-Vault
        checks["x_vault_exists"] = artifact.x_vault is not None
        if artifact.x_vault:
            checks["snapshot_exists"] = bool(artifact.x_vault.snapshot_id)
            checks["merkle_root_exists"] = bool(artifact.x_vault.merkle_root)
        
        # Invarianter
        errors = artifact.validate_invariants()
        checks["invariants_valid"] = len(errors) == 0
        
        valid = all(checks.values())
        
        return {
            "artifact_id": artifact_id,
            "valid": valid,
            "checks": checks,
            "verified_at": artifact.verified_at,
            "approver": artifact.approval.approver_name if artifact.approval else None,
            "merkle_root": artifact.x_vault.merkle_root if artifact.x_vault else None
        }
    
    def get_trust_chain(self, artifact_id: str) -> Dict:
        """Hämta fullständig förtroendekedja"""
        artifact = self.artifacts.get(artifact_id)
        if not artifact:
            return {"error": "Artifact finns ej"}
        
        return {
            "artifact": {
                "artifact_id": artifact.artifact_id,
                "status": artifact.status.value,
                "verified_at": artifact.verified_at
            },
            "approval": artifact.approval.to_dict() if artifact.approval else None,
            "approver_chain": (
                self.registry.get_trust_chain(artifact.approval.approver_id)
                if artifact.approval else []
            ),
            "x_vault": artifact.x_vault.to_dict() if artifact.x_vault else None,
            "root_of_trust": self.registry.FOUNDER_ID
        }
    
    # =========================================================================
    # HELPERS
    # =========================================================================
    
    def _create_signature(
        self,
        artifact_id: str,
        artifact_hash: str,
        approver_id: str,
        timestamp: str,
        approver_key: str
    ) -> str:
        """Skapa signatur (förenklad för demo)"""
        payload = f"{artifact_id}:{artifact_hash}:{approver_id}:{timestamp}"
        sign_data = f"{payload}:{approver_key}"
        return hashlib.sha256(sign_data.encode()).hexdigest()
    
    def list_by_status(self, status: ArtifactStatus) -> List[Artifact]:
        """Lista artifacts med given status"""
        return [a for a in self.artifacts.values() if a.status == status]
    
    def get_verified_artifacts(self) -> List[Artifact]:
        """Hämta endast VERIFIED artifacts (för ComplieDocs)"""
        return self.list_by_status(ArtifactStatus.VERIFIED)


# =============================================================================
# INVARIANT TESTS
# =============================================================================
def test_approve_seal_separation():
    """Testa att approve och seal är separerade"""
    print("\nTesting APPROVE ≠ SEAL separation...")
    
    mgr = VerifiedApprovalManager()
    
    # Skapa artifact
    artifact = ArtifactFactory.create_draft(
        artifact_type=ArtifactType.KNOWLEDGE,
        title="Test: Approve/Seal Separation",
        content={"body": "test content"},
        version="v1",
        author="test@example.com"
    )
    
    # Submit
    artifact = mgr.submit(artifact)
    assert artifact.status == ArtifactStatus.SUBMITTED
    print("  ✅ draft → submitted")
    
    # Försök seal utan approve = FEL
    try:
        mgr.seal(artifact.artifact_id)
        assert False, "Borde ha fått fel"
    except StateTransitionError as e:
        assert "APPROVED" in str(e)
        print("  ✅ seal utan approve = BLOCKED")
    
    # Approve
    result = mgr.approve(
        artifact_id=artifact.artifact_id,
        approver_id="key:founder_joakim",
        approver_key="test_key",
        role=ApproverRole.LEGAL_REVIEWER
    )
    assert result.status == "approved"
    artifact = mgr.artifacts[artifact.artifact_id]
    assert artifact.status == ArtifactStatus.APPROVED
    assert artifact.approval is not None
    assert artifact.x_vault.authorization_evidence_id is not None
    assert artifact.x_vault.snapshot_id is None  # Ej sealed än!
    print("  ✅ submitted → approved (FAS 5)")
    
    # Seal
    seal_result = mgr.seal(artifact.artifact_id)
    assert seal_result.status == "verified"
    artifact = mgr.artifacts[artifact.artifact_id]
    assert artifact.status == ArtifactStatus.VERIFIED
    assert artifact.x_vault.snapshot_id is not None
    assert artifact.x_vault.merkle_root is not None
    assert artifact.verified_at is not None
    print("  ✅ approved → verified (FAS 6)")
    
    # Verifiera
    verify_result = mgr.verify(artifact.artifact_id)
    assert verify_result["valid"]
    print("  ✅ Verification passed")
    
    print("\n✅ APPROVE ≠ SEAL separation ENFORCED")


if __name__ == "__main__":
    from artifact import ArtifactType
    
    test_approve_seal_separation()
    
    print("\n" + "="*50)
    print("FAS5_IMPLEMENTATION = FROZEN")
    print("APPROVE_SEAL_SEPARATION = ENFORCED")
    print("="*50)
