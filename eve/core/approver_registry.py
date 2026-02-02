"""
EVE Approver Registry
=====================
Founder-approved trust model för Trinity-verifiering.

Princip: Identitet är ett attribut, inte en implementation.

Just nu:
- Founder (Joakim) är root of trust
- can_verify_trinity = explicit flagga
- Ingen BankID/eIDAS krävs
- Arkitekturen är förberedd för starkare identitet senare

Uttryckligen INTE tillåtet:
- Delade konton får aldrig verifiera
- Att vara inloggad räcker inte
- Roller räcker inte
- Ingen får eskalera sig själv
- Ingen verifiering utan explicit founder-godkännande

Version: 1.0.0
Status: ACTIVE
"""

import hashlib
import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Dict, Optional, List
from pathlib import Path
from enum import Enum


class IdentityStrength(Enum):
    """
    Identitetsstyrka - attribut som kan uppgraderas.
    Arkitekturen stödjer alla nivåer utan workflow-ändringar.
    """
    FOUNDER_APPROVED = "founder_approved"   # Demo-fas: Joakim godkänner
    ORGANIZATION_IDP = "organization_idp"   # Företags-IdP
    BANKID_SE = "bankid_se"                 # Svensk BankID
    EIDAS_SUBSTANTIAL = "eidas_substantial" # eIDAS substantial
    EIDAS_HIGH = "eidas_high"               # eIDAS high (kvalificerad)


class ApproverRole(Enum):
    """
    Roller för olika typer av verifiering.
    Roll räcker INTE ensamt - kräver också can_verify_trinity.
    """
    LEGAL_REVIEWER = "legal_reviewer"
    TECHNICAL_REVIEWER = "technical_reviewer"
    COMPLIANCE_OFFICER = "compliance_officer"
    FOUNDER = "founder"


@dataclass
class Approver:
    """
    Registrerad person med verifieringsrätt.
    
    Kritiskt: can_verify_trinity är explicit flagga som endast
    founder kan sätta. Att ha en roll räcker INTE.
    """
    approver_id: str                        # Unik ID (key:hash)
    name: str                               # Fullt namn
    email: str                              # Kontakt
    roles: List[ApproverRole]               # Tillåtna roller
    identity_strength: IdentityStrength     # Hur stark identitet
    can_verify_trinity: bool                # KRITISK: Får verifiera till Trinity?
    granted_by: str                         # Vem godkände (approver_id)
    granted_at: str                         # När godkännandet gavs
    public_key: Optional[str] = None        # Publik nyckel (för signering)
    active: bool = True                     # Aktiv/inaktiv
    notes: str = ""                         # Anteckningar
    
    def to_dict(self) -> Dict:
        d = asdict(self)
        d['roles'] = [r.value for r in self.roles]
        d['identity_strength'] = self.identity_strength.value
        return d
    
    @classmethod
    def from_dict(cls, d: Dict) -> 'Approver':
        return cls(
            approver_id=d['approver_id'],
            name=d['name'],
            email=d['email'],
            roles=[ApproverRole(r) for r in d['roles']],
            identity_strength=IdentityStrength(d['identity_strength']),
            can_verify_trinity=d['can_verify_trinity'],
            granted_by=d['granted_by'],
            granted_at=d['granted_at'],
            public_key=d.get('public_key'),
            active=d.get('active', True),
            notes=d.get('notes', '')
        )


class ApproverRegistry:
    """
    Centralt register över godkända verifierare.
    
    Säkerhetsmodell:
    1. Founder är root of trust (bootstrap)
    2. Endast founder kan sätta can_verify_trinity = true
    3. Ingen kan eskalera sig själv
    4. WORM-princip: Händelser loggas, aldrig raderas
    
    Framtida uppgradering:
    - identity_strength kan höjas utan workflow-ändringar
    - Tidigare beslut förblir giltiga
    - BankID/eIDAS kan läggas till som identity_strength
    """
    
    REGISTRY_PATH = Path(os.environ.get(
        "EVE_APPROVER_REGISTRY_PATH",
        str(Path(__file__).parent.parent / "data" / "approver_registry.json")
    ))
    FOUNDER_ID = "key:founder_joakim"  # Bootstrap root of trust
    
    def __init__(self):
        self.approvers: Dict[str, Approver] = {}
        self.audit_log: List[Dict] = []
        self._load_registry()
    
    def _load_registry(self):
        """Ladda registry från disk, eller bootstrap om tom"""
        if self.REGISTRY_PATH.exists():
            data = json.loads(self.REGISTRY_PATH.read_text(encoding='utf-8'))
            for a in data.get('approvers', []):
                approver = Approver.from_dict(a)
                self.approvers[approver.approver_id] = approver
            self.audit_log = data.get('audit_log', [])
        else:
            # Bootstrap: Skapa founder som root of trust
            self._bootstrap_founder()
    
    def _bootstrap_founder(self):
        """
        Bootstrap founder som root of trust.
        Detta är den enda självgodkännande operationen.
        """
        founder = Approver(
            approver_id=self.FOUNDER_ID,
            name="Joakim Eklund",
            email="joakim@organiq.se",
            roles=[ApproverRole.FOUNDER, ApproverRole.LEGAL_REVIEWER, 
                   ApproverRole.TECHNICAL_REVIEWER, ApproverRole.COMPLIANCE_OFFICER],
            identity_strength=IdentityStrength.FOUNDER_APPROVED,
            can_verify_trinity=True,  # Founder är alltid trusted
            granted_by="BOOTSTRAP",   # Speciellt värde för initial setup
            granted_at=datetime.now(timezone.utc).isoformat(),
            notes="Root of trust - Founder bootstrap"
        )
        
        self.approvers[founder.approver_id] = founder
        self._log_audit("BOOTSTRAP", "FOUNDER_CREATED", founder.approver_id, "SYSTEM")
        self._save_registry()
    
    def _save_registry(self):
        """Spara registry till disk"""
        self.REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'version': '1.0.0',
            'model': 'founder_approved_trust',
            'root_of_trust': self.FOUNDER_ID,
            'approvers': [a.to_dict() for a in self.approvers.values()],
            'audit_log': self.audit_log
        }
        self.REGISTRY_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
    
    def _log_audit(self, action: str, detail: str, target: str, actor: str):
        """Logga händelse (WORM - append only)"""
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'action': action,
            'detail': detail,
            'target': target,
            'actor': actor
        }
        self.audit_log.append(entry)
    
    def grant_trinity_access(
        self,
        name: str,
        email: str,
        roles: List[ApproverRole],
        granted_by_id: str,
        notes: str = ""
    ) -> Approver:
        """
        Ge någon rätt att verifiera till Trinity.
        
        KRITISKT: Endast founder kan göra detta.
        
        Args:
            name: Personens namn
            email: Email
            roles: Vilka roller personen har
            granted_by_id: Approver ID för den som godkänner (måste vara founder)
            notes: Anteckningar
            
        Returns:
            Ny Approver med can_verify_trinity=True
            
        Raises:
            PermissionError: Om granted_by inte är founder
        """
        # Endast founder får ge Trinity-access
        if granted_by_id != self.FOUNDER_ID:
            granter = self.approvers.get(granted_by_id)
            if not granter or ApproverRole.FOUNDER not in granter.roles:
                self._log_audit(
                    "DENIED", 
                    "TRINITY_ACCESS_ATTEMPT_BY_NON_FOUNDER",
                    email,
                    granted_by_id
                )
                self._save_registry()
                raise PermissionError(
                    f"Endast founder kan ge Trinity-access. "
                    f"{granted_by_id} är inte founder."
                )
        
        # Generera approver ID
        approver_id = f"key:{hashlib.sha256(email.encode()).hexdigest()[:12]}"
        
        if approver_id in self.approvers:
            raise ValueError(f"Approver redan registrerad: {email}")
        
        approver = Approver(
            approver_id=approver_id,
            name=name,
            email=email,
            roles=roles,
            identity_strength=IdentityStrength.FOUNDER_APPROVED,
            can_verify_trinity=True,
            granted_by=granted_by_id,
            granted_at=datetime.now(timezone.utc).isoformat(),
            notes=notes
        )
        
        self.approvers[approver_id] = approver
        self._log_audit("GRANT", "TRINITY_ACCESS", approver_id, granted_by_id)
        self._save_registry()
        
        return approver
    
    def add_demo_user(
        self,
        name: str,
        email: str,
        roles: List[ApproverRole]
    ) -> Approver:
        """
        Lägg till demo-användare (kan INTE verifiera till Trinity).
        
        Alla kan logga in och använda Control Room, men VERIFY
        är spärrat som default.
        """
        approver_id = f"demo:{hashlib.sha256(email.encode()).hexdigest()[:12]}"
        
        if approver_id in self.approvers:
            raise ValueError(f"Användare redan registrerad: {email}")
        
        approver = Approver(
            approver_id=approver_id,
            name=name,
            email=email,
            roles=roles,
            identity_strength=IdentityStrength.FOUNDER_APPROVED,
            can_verify_trinity=False,  # KRITISKT: Demo-användare kan INTE verifiera
            granted_by="DEMO_REGISTRATION",
            granted_at=datetime.now(timezone.utc).isoformat(),
            notes="Demo user - cannot verify to Trinity"
        )
        
        self.approvers[approver_id] = approver
        self._log_audit("REGISTER", "DEMO_USER", approver_id, "DEMO_REGISTRATION")
        self._save_registry()
        
        return approver
    
    def can_verify(self, approver_id: str) -> bool:
        """
        Kontrollera om approver får verifiera till Trinity.
        
        Returnerar True ENDAST om:
        1. Approver finns
        2. Approver är aktiv
        3. can_verify_trinity == True (explicit founder-godkännande)
        """
        approver = self.approvers.get(approver_id)
        if not approver:
            return False
        if not approver.active:
            return False
        return approver.can_verify_trinity
    
    def verify_for_role(self, approver_id: str, required_role: ApproverRole) -> bool:
        """
        Kontrollera om approver har specifik roll OCH får verifiera.
        
        Båda krävs:
        1. can_verify_trinity == True
        2. required_role finns i approver.roles
        """
        if not self.can_verify(approver_id):
            return False
        
        approver = self.approvers.get(approver_id)
        return required_role in approver.roles
    
    def get_approver(self, approver_id: str) -> Optional[Approver]:
        """Hämta approver"""
        return self.approvers.get(approver_id)
    
    def list_trinity_verifiers(self) -> List[Approver]:
        """Lista alla som kan verifiera till Trinity"""
        return [
            a for a in self.approvers.values() 
            if a.active and a.can_verify_trinity
        ]
    
    def list_demo_users(self) -> List[Approver]:
        """Lista demo-användare (kan EJ verifiera)"""
        return [
            a for a in self.approvers.values() 
            if a.active and not a.can_verify_trinity
        ]
    
    def revoke_trinity_access(self, approver_id: str, revoked_by_id: str, reason: str):
        """
        Återkalla Trinity-access.
        
        Endast founder kan återkalla.
        Approver förblir i registret (WORM) men markeras inaktiv.
        """
        if revoked_by_id != self.FOUNDER_ID:
            raise PermissionError("Endast founder kan återkalla Trinity-access")
        
        approver = self.approvers.get(approver_id)
        if not approver:
            raise ValueError(f"Approver finns inte: {approver_id}")
        
        approver.can_verify_trinity = False
        approver.notes += f"\n[REVOKED {datetime.now(timezone.utc).isoformat()}] {reason}"
        
        self._log_audit("REVOKE", f"TRINITY_ACCESS: {reason}", approver_id, revoked_by_id)
        self._save_registry()
    
    def get_trust_chain(self, approver_id: str) -> List[Dict]:
        """
        Hämta förtroendekedja tillbaka till root of trust.
        
        Varje approver har granted_by som pekar på den som godkände.
        Kedjan slutar vid BOOTSTRAP (founder).
        """
        chain = []
        current_id = approver_id
        
        while current_id and current_id != "BOOTSTRAP":
            approver = self.approvers.get(current_id)
            if not approver:
                break
            
            chain.append({
                'approver_id': approver.approver_id,
                'name': approver.name,
                'granted_by': approver.granted_by,
                'granted_at': approver.granted_at,
                'identity_strength': approver.identity_strength.value
            })
            
            current_id = approver.granted_by
        
        return chain


# =============================================================================
# CLI / TEST
# =============================================================================
if __name__ == "__main__":
    import sys
    
    registry = ApproverRegistry()
    
    if len(sys.argv) < 2:
        print("""
EVE Approver Registry
=====================
Founder-approved trust model

Commands:
  list              - Lista alla godkända verifierare
  list-demo         - Lista demo-användare (kan EJ verifiera)
  check <id>        - Kontrollera om ID kan verifiera
  trust-chain <id>  - Visa förtroendekedja
  
Root of Trust: {founder}
Trinity Verifiers: {count}
        """.format(
            founder=registry.FOUNDER_ID,
            count=len(registry.list_trinity_verifiers())
        ))
        sys.exit(0)
    
    cmd = sys.argv[1]
    
    if cmd == "list":
        verifiers = registry.list_trinity_verifiers()
        print(f"\n✅ Trinity Verifiers ({len(verifiers)}):\n")
        for v in verifiers:
            print(f"  {v.approver_id}")
            print(f"    Name: {v.name}")
            print(f"    Roles: {[r.value for r in v.roles]}")
            print(f"    Strength: {v.identity_strength.value}")
            print(f"    Granted by: {v.granted_by}")
            print()
    
    elif cmd == "list-demo":
        demos = registry.list_demo_users()
        print(f"\n👤 Demo Users ({len(demos)}) - Cannot verify to Trinity:\n")
        for d in demos:
            print(f"  {d.approver_id}: {d.name}")
    
    elif cmd == "check" and len(sys.argv) > 2:
        approver_id = sys.argv[2]
        can = registry.can_verify(approver_id)
        approver = registry.get_approver(approver_id)
        
        if approver:
            print(f"\nApprover: {approver.name}")
            print(f"Can verify Trinity: {'✅ YES' if can else '❌ NO'}")
            print(f"Identity strength: {approver.identity_strength.value}")
        else:
            print(f"❌ Approver not found: {approver_id}")
    
    elif cmd == "trust-chain" and len(sys.argv) > 2:
        approver_id = sys.argv[2]
        chain = registry.get_trust_chain(approver_id)
        
        print(f"\n🔗 Trust Chain for {approver_id}:\n")
        for i, link in enumerate(chain):
            indent = "  " * i
            print(f"{indent}→ {link['name']} ({link['approver_id'][:20]}...)")
            print(f"{indent}  Granted by: {link['granted_by']}")
            print(f"{indent}  Strength: {link['identity_strength']}")
    
    else:
        print("Unknown command")
