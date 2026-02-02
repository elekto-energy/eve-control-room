"""
EVE CORE - X-VAULT
==================
Kryptografiskt verifieringslager för beviskedja.
Skapar immutabla evidence objects med Merkle-träd.

Patent-referens: Komponent (40) - "Verifieringslager"
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict, field
from enum import Enum
from uuid import uuid4
import base64


class EvidenceType(Enum):
    """Typer av evidence objects"""
    WITNESS_RESPONSE = "witness_response"
    AUTHORIZATION_DECISION = "authorization_decision"
    KNOWLEDGE_PUBLISH = "knowledge_publish"
    RULE_PROFILE_CHANGE = "rule_profile_change"
    SYSTEM_EVENT = "system_event"
    EXPORT_EVENT = "export_event"


@dataclass
class EvidenceObject:
    """
    Kryptografiskt bevis av en händelse.
    Immutabelt efter skapande.
    """
    evidence_id: str
    evidence_type: EvidenceType
    timestamp: str
    content_hash: str
    content: Dict
    merkle_path: List[str]
    previous_hash: str
    signature: str
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['evidence_type'] = self.evidence_type.value
        return result
    
    def verify(self) -> bool:
        """Verifiera att content matchar hash"""
        computed = hashlib.sha256(
            json.dumps(self.content, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return computed == self.content_hash


@dataclass
class Snapshot:
    """
    Signerad representation av systemtillstånd.
    Används för offline-verifiering.
    """
    snapshot_id: str
    timestamp: str
    knowledge_version: str
    object_count: int
    merkle_root: str
    object_hashes: Dict[str, str]
    signature: str
    previous_snapshot: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class RegulatorPackage:
    """
    Exportpaket för revision/tillsyn.
    Innehåller allt som behövs för offline-verifiering.
    """
    package_id: str
    created_at: str
    period_start: str
    period_end: str
    evidence_objects: List[EvidenceObject]
    snapshots: List[Snapshot]
    merkle_root: str
    verification_instructions: str
    signature: str
    
    def to_dict(self) -> Dict:
        result = {
            "package_id": self.package_id,
            "created_at": self.created_at,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "evidence_count": len(self.evidence_objects),
            "snapshot_count": len(self.snapshots),
            "merkle_root": self.merkle_root,
            "verification_instructions": self.verification_instructions,
            "signature": self.signature
        }
        return result


class MerkleTree:
    """
    Merkle-träd implementation för effektiv verifiering.
    """
    
    def __init__(self, leaves: List[str] = None):
        self.leaves = leaves or []
        self.tree: List[List[str]] = []
        if self.leaves:
            self._build_tree()
    
    def _hash_pair(self, left: str, right: str) -> str:
        """Hash två noder tillsammans"""
        combined = left + right
        return hashlib.sha256(combined.encode()).hexdigest()
    
    def _build_tree(self):
        """Bygg Merkle-trädet från löven"""
        if not self.leaves:
            return
            
        self.tree = [self.leaves.copy()]
        
        while len(self.tree[-1]) > 1:
            level = self.tree[-1]
            next_level = []
            
            for i in range(0, len(level), 2):
                left = level[i]
                right = level[i + 1] if i + 1 < len(level) else level[i]
                next_level.append(self._hash_pair(left, right))
                
            self.tree.append(next_level)
    
    def add_leaf(self, leaf_hash: str):
        """Lägg till ett löv och återbygg trädet"""
        self.leaves.append(leaf_hash)
        self._build_tree()
    
    @property
    def root(self) -> Optional[str]:
        """Hämta Merkle-root"""
        if not self.tree:
            return None
        return self.tree[-1][0] if self.tree[-1] else None
    
    def get_proof(self, leaf_index: int) -> List[Tuple[str, str]]:
        """
        Hämta Merkle-proof för ett specifikt löv.
        Returnerar lista av (sibling_hash, position) tupler.
        """
        if leaf_index >= len(self.leaves):
            return []
            
        proof = []
        index = leaf_index
        
        for level in self.tree[:-1]:
            if index % 2 == 0:
                sibling_index = index + 1
                position = "right"
            else:
                sibling_index = index - 1
                position = "left"
                
            if sibling_index < len(level):
                proof.append((level[sibling_index], position))
                
            index //= 2
            
        return proof
    
    @staticmethod
    def verify_proof(
        leaf_hash: str,
        proof: List[Tuple[str, str]],
        root: str
    ) -> bool:
        """Verifiera ett Merkle-proof"""
        current = leaf_hash
        
        for sibling_hash, position in proof:
            if position == "right":
                combined = current + sibling_hash
            else:
                combined = sibling_hash + current
            current = hashlib.sha256(combined.encode()).hexdigest()
            
        return current == root


class XVault:
    """
    EVE Core X-Vault
    
    Kryptografiskt verifieringslager som:
    1. Skapar immutabla evidence objects
    2. Bygger Merkle-träd för effektiv verifiering
    3. Genererar snapshots för offline-verifiering
    4. Exporterar regulator packages
    
    WORM-princip: Write Once, Read Many
    """
    
    def __init__(self, org_id: str, signing_key: str = "default_key"):
        self.org_id = org_id
        self.signing_key = signing_key
        self.evidence_chain: List[EvidenceObject] = []
        self.snapshots: List[Snapshot] = []
        self.merkle_tree = MerkleTree()
        self.last_hash = "genesis"
        
    def seal(
        self,
        evidence_type: EvidenceType,
        content: Dict,
        metadata: Optional[Dict] = None
    ) -> EvidenceObject:
        """
        Försegla data som ett evidence object.
        
        Args:
            evidence_type: Typ av bevis
            content: Data att försegla
            metadata: Extra metadata
            
        Returns:
            EvidenceObject med hash och Merkle-path
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Hash content
        content_hash = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        
        # Lägg till i Merkle-träd
        self.merkle_tree.add_leaf(content_hash)
        leaf_index = len(self.merkle_tree.leaves) - 1
        merkle_proof = self.merkle_tree.get_proof(leaf_index)
        merkle_path = [f"{h}:{p}" for h, p in merkle_proof]
        
        # Skapa signatur
        signature = self._sign(content_hash, timestamp)
        
        evidence = EvidenceObject(
            evidence_id=str(uuid4()),
            evidence_type=evidence_type,
            timestamp=timestamp,
            content_hash=content_hash,
            content=content,
            merkle_path=merkle_path,
            previous_hash=self.last_hash,
            signature=signature,
            metadata=metadata or {}
        )
        
        self.evidence_chain.append(evidence)
        self.last_hash = content_hash
        
        return evidence
    
    def create_snapshot(self, knowledge_version: str) -> Snapshot:
        """
        Skapa en snapshot av aktuellt tillstånd.
        
        Args:
            knowledge_version: Version av kunskapsbasen
            
        Returns:
            Snapshot med Merkle-root och alla object hashes
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        
        object_hashes = {
            e.evidence_id: e.content_hash
            for e in self.evidence_chain
        }
        
        snapshot = Snapshot(
            snapshot_id=str(uuid4()),
            timestamp=timestamp,
            knowledge_version=knowledge_version,
            object_count=len(self.evidence_chain),
            merkle_root=self.merkle_tree.root or "",
            object_hashes=object_hashes,
            signature=self._sign(self.merkle_tree.root or "", timestamp),
            previous_snapshot=self.snapshots[-1].snapshot_id if self.snapshots else None
        )
        
        self.snapshots.append(snapshot)
        return snapshot
    
    def export_regulator_package(
        self,
        period_start: str,
        period_end: str
    ) -> RegulatorPackage:
        """
        Exportera ett regulator package för revision.
        
        Args:
            period_start: Startdatum (ISO format)
            period_end: Slutdatum (ISO format)
            
        Returns:
            RegulatorPackage med all evidence och verification data
        """
        # Filtrera evidence för perioden
        filtered_evidence = [
            e for e in self.evidence_chain
            if period_start <= e.timestamp <= period_end
        ]
        
        # Filtrera snapshots för perioden
        filtered_snapshots = [
            s for s in self.snapshots
            if period_start <= s.timestamp <= period_end
        ]
        
        timestamp = datetime.now(timezone.utc).isoformat()
        
        package = RegulatorPackage(
            package_id=str(uuid4()),
            created_at=timestamp,
            period_start=period_start,
            period_end=period_end,
            evidence_objects=filtered_evidence,
            snapshots=filtered_snapshots,
            merkle_root=self.merkle_tree.root or "",
            verification_instructions=self._get_verification_instructions(),
            signature=self._sign(self.merkle_tree.root or "", timestamp)
        )
        
        # Logga exporten som egen evidence
        self.seal(
            evidence_type=EvidenceType.EXPORT_EVENT,
            content={
                "package_id": package.package_id,
                "period_start": period_start,
                "period_end": period_end,
                "evidence_count": len(filtered_evidence)
            }
        )
        
        return package
    
    def verify_evidence(self, evidence: EvidenceObject) -> bool:
        """
        Verifiera ett evidence object.
        
        Returns:
            True om verifiering lyckas
        """
        # Verifiera content hash
        if not evidence.verify():
            return False
            
        # Verifiera Merkle-proof (om tillgängligt)
        if evidence.merkle_path and self.merkle_tree.root:
            proof = []
            for item in evidence.merkle_path:
                h, p = item.split(":")
                proof.append((h, p))
            return MerkleTree.verify_proof(
                evidence.content_hash,
                proof,
                self.merkle_tree.root
            )
            
        return True
    
    def verify_chain(self) -> Tuple[bool, List[str]]:
        """
        Verifiera hela beviskedjan.
        
        Returns:
            (success, list of errors)
        """
        errors = []
        
        for i, evidence in enumerate(self.evidence_chain):
            # Verifiera content hash
            if not evidence.verify():
                errors.append(f"Evidence {evidence.evidence_id}: content hash mismatch")
                
            # Verifiera previous hash (utom för första)
            if i > 0:
                expected_prev = self.evidence_chain[i-1].content_hash
                if evidence.previous_hash != expected_prev:
                    errors.append(f"Evidence {evidence.evidence_id}: chain broken")
                    
        return len(errors) == 0, errors
    
    def _sign(self, data: str, timestamp: str) -> str:
        """Generera signatur (förenklad implementation)"""
        sign_data = f"{data}:{timestamp}:{self.org_id}:{self.signing_key}"
        return hashlib.sha256(sign_data.encode()).hexdigest()
    
    def _get_verification_instructions(self) -> str:
        """Instruktioner för offline-verifiering"""
        return """
VERIFICATION INSTRUCTIONS
=========================

1. For each evidence object:
   - Compute SHA-256 of content (JSON, sorted keys)
   - Compare with content_hash
   - Verify Merkle proof against merkle_root

2. For chain integrity:
   - Verify each previous_hash matches prior content_hash
   - First evidence should have previous_hash = "genesis"

3. For snapshot verification:
   - Verify merkle_root matches computed Merkle tree
   - Verify object_hashes match evidence objects

Tools: Standard SHA-256 implementation, JSON parser
No network access required for verification.
"""
    
    def get_stats(self) -> Dict:
        """Hämta statistik"""
        return {
            "org_id": self.org_id,
            "evidence_count": len(self.evidence_chain),
            "snapshot_count": len(self.snapshots),
            "merkle_root": self.merkle_tree.root,
            "last_hash": self.last_hash
        }


# =============================================================================
# EXEMPEL PÅ ANVÄNDNING
# =============================================================================
if __name__ == "__main__":
    # Skapa X-Vault
    vault = XVault(org_id="org_acme")
    
    # Seal några evidence objects
    e1 = vault.seal(
        evidence_type=EvidenceType.WITNESS_RESPONSE,
        content={
            "query": "Vad säger AI Act om mänsklig tillsyn?",
            "response": "Enligt artikel 14...",
            "sources": ["eu/ai_act/article_14"]
        }
    )
    print(f"Evidence 1: {e1.evidence_id[:8]}... hash={e1.content_hash[:16]}...")
    
    e2 = vault.seal(
        evidence_type=EvidenceType.AUTHORIZATION_DECISION,
        content={
            "request_id": "req_123",
            "decision": "approved",
            "approver": "user_456"
        }
    )
    print(f"Evidence 2: {e2.evidence_id[:8]}... hash={e2.content_hash[:16]}...")
    
    # Skapa snapshot
    snapshot = vault.create_snapshot(knowledge_version="2026-01-17")
    print(f"\nSnapshot: {snapshot.snapshot_id[:8]}...")
    print(f"Merkle root: {snapshot.merkle_root[:16]}...")
    
    # Verifiera kedjan
    valid, errors = vault.verify_chain()
    print(f"\nChain valid: {valid}")
    
    # Verifiera enskilt evidence
    print(f"Evidence 1 valid: {vault.verify_evidence(e1)}")
    
    # Exportera regulator package
    package = vault.export_regulator_package(
        period_start="2026-01-01T00:00:00+00:00",
        period_end="2026-12-31T23:59:59+00:00"
    )
    print(f"\nRegulator package: {package.package_id[:8]}...")
    print(f"Evidence objects: {len(package.evidence_objects)}")
    
    print(f"\nStats: {vault.get_stats()}")
