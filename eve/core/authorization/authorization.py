"""
EVE CORE - AUTHORIZATION MODULE
===============================
Säkerställer att alla förändringar kräver explicit mänskligt godkännande.
Ingen automatisk auktorisation. Identifierad användare krävs.

Patent-referens: Komponent (30) - "Auktorisationsmodul"
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict, field
from enum import Enum
from uuid import uuid4


class AuthorizationAction(Enum):
    """Typer av handlingar som kräver auktorisation"""
    PUBLISH_KNOWLEDGE = "publish_knowledge"
    UPDATE_RULE_PROFILE = "update_rule_profile"
    APPROVE_DECISION = "approve_decision"
    EXPORT_EVIDENCE = "export_evidence"
    CHANGE_SCOPE = "change_scope"
    ADD_USER = "add_user"
    MODIFY_AGENT = "modify_agent"


class AuthorizationStatus(Enum):
    """Status för auktorisationsförfrågan"""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Role(Enum):
    """Roller med olika mandatnivåer"""
    VIEWER = "viewer"
    ANALYST = "analyst"
    COMPLIANCE_OFFICER = "compliance_officer"
    DATA_PROTECTION_OFFICER = "data_protection_officer"
    ADMIN = "admin"
    SUPER_ADMIN = "super_admin"


@dataclass
class User:
    """Identifierad användare"""
    user_id: str
    name: str
    email: str
    role: Role
    org_id: str
    active: bool = True
    mfa_enabled: bool = False


@dataclass
class AuthorizationRequest:
    """Förfrågan om auktorisation"""
    request_id: str
    action: AuthorizationAction
    requester: User
    target_resource: str
    reason: str
    created_at: str
    expires_at: str
    status: AuthorizationStatus = AuthorizationStatus.PENDING
    approvers: List[str] = field(default_factory=list)
    approval_chain: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['action'] = self.action.value
        result['status'] = self.status.value
        result['requester']['role'] = self.requester.role.value
        return result


@dataclass
class AuthorizationDecision:
    """Beslut om auktorisation"""
    decision_id: str
    request_id: str
    approver: User
    decision: AuthorizationStatus
    reason: str
    timestamp: str
    signature_hash: str
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['decision'] = self.decision.value
        result['approver']['role'] = self.approver.role.value
        return result


class AuthorizationModule:
    """
    EVE Core Authorization Module
    
    Kärnprinciper:
    1. Ingen automatisk auktorisation - alla ändringar kräver mänskligt godkännande
    2. Identifierad användare - ingen anonym åtgärd
    3. Loggning - varje auktorisation loggas permanent
    4. Auktorisation kan inte delegeras till AI-komponenten
    
    Flöde:
    1. Request skapas med requester och target
    2. System identifierar required approvers baserat på action och org policy
    3. Approvers godkänner/avslår
    4. Vid godkännande: action utförs och loggas
    5. Vid avslag: action blockeras och loggas
    """
    
    # Minimikrav på godkännare per action
    APPROVAL_REQUIREMENTS = {
        AuthorizationAction.PUBLISH_KNOWLEDGE: {
            "min_approvers": 1,
            "required_roles": [Role.COMPLIANCE_OFFICER, Role.ADMIN]
        },
        AuthorizationAction.UPDATE_RULE_PROFILE: {
            "min_approvers": 2,
            "required_roles": [Role.COMPLIANCE_OFFICER, Role.DATA_PROTECTION_OFFICER]
        },
        AuthorizationAction.APPROVE_DECISION: {
            "min_approvers": 1,
            "required_roles": [Role.COMPLIANCE_OFFICER, Role.ADMIN]
        },
        AuthorizationAction.EXPORT_EVIDENCE: {
            "min_approvers": 1,
            "required_roles": [Role.ANALYST, Role.COMPLIANCE_OFFICER, Role.ADMIN]
        },
        AuthorizationAction.CHANGE_SCOPE: {
            "min_approvers": 2,
            "required_roles": [Role.ADMIN, Role.SUPER_ADMIN]
        },
        AuthorizationAction.ADD_USER: {
            "min_approvers": 1,
            "required_roles": [Role.ADMIN, Role.SUPER_ADMIN]
        },
        AuthorizationAction.MODIFY_AGENT: {
            "min_approvers": 2,
            "required_roles": [Role.SUPER_ADMIN]
        }
    }
    
    def __init__(self, org_id: str):
        self.org_id = org_id
        self.pending_requests: Dict[str, AuthorizationRequest] = {}
        self.completed_requests: List[AuthorizationRequest] = []
        self.decision_log: List[AuthorizationDecision] = []
        
    def create_request(
        self,
        action: AuthorizationAction,
        requester: User,
        target_resource: str,
        reason: str,
        expires_hours: int = 48,
        metadata: Optional[Dict] = None
    ) -> AuthorizationRequest:
        """
        Skapa en auktorisationsförfrågan.
        
        Args:
            action: Typ av handling som kräver auktorisation
            requester: Användare som begär auktorisation
            target_resource: Resurs som påverkas
            reason: Anledning till förfrågan
            expires_hours: Giltighetstid i timmar
            metadata: Extra data
            
        Returns:
            AuthorizationRequest
        """
        # Validera requester
        if not requester.active:
            raise ValueError("Requester is not active")
        if requester.org_id != self.org_id:
            raise ValueError("Requester not in organization")
            
        now = datetime.now(timezone.utc)
        expires = datetime.fromtimestamp(
            now.timestamp() + (expires_hours * 3600),
            tz=timezone.utc
        )
        
        request = AuthorizationRequest(
            request_id=str(uuid4()),
            action=action,
            requester=requester,
            target_resource=target_resource,
            reason=reason,
            created_at=now.isoformat(),
            expires_at=expires.isoformat(),
            metadata=metadata or {}
        )
        
        self.pending_requests[request.request_id] = request
        return request
    
    def approve(
        self,
        request_id: str,
        approver: User,
        reason: str = ""
    ) -> AuthorizationDecision:
        """
        Godkänn en auktorisationsförfrågan.
        
        Args:
            request_id: ID för förfrågan
            approver: Användare som godkänner
            reason: Anledning/kommentar
            
        Returns:
            AuthorizationDecision
        """
        return self._make_decision(
            request_id=request_id,
            approver=approver,
            decision=AuthorizationStatus.APPROVED,
            reason=reason
        )
    
    def reject(
        self,
        request_id: str,
        approver: User,
        reason: str
    ) -> AuthorizationDecision:
        """
        Avslå en auktorisationsförfrågan.
        
        Args:
            request_id: ID för förfrågan
            approver: Användare som avslår
            reason: Anledning (obligatorisk)
            
        Returns:
            AuthorizationDecision
        """
        if not reason:
            raise ValueError("Reason is required for rejection")
            
        return self._make_decision(
            request_id=request_id,
            approver=approver,
            decision=AuthorizationStatus.REJECTED,
            reason=reason
        )
    
    def _make_decision(
        self,
        request_id: str,
        approver: User,
        decision: AuthorizationStatus,
        reason: str
    ) -> AuthorizationDecision:
        """Intern metod för att fatta beslut"""
        
        # Hämta request
        request = self.pending_requests.get(request_id)
        if not request:
            raise ValueError(f"Request {request_id} not found")
            
        # Validera approver
        if not approver.active:
            raise ValueError("Approver is not active")
        if approver.org_id != self.org_id:
            raise ValueError("Approver not in organization")
        if approver.user_id == request.requester.user_id:
            raise ValueError("Cannot approve own request")
            
        # Kontrollera roll-behörighet
        requirements = self.APPROVAL_REQUIREMENTS.get(request.action, {})
        required_roles = requirements.get("required_roles", [])
        if required_roles and approver.role not in required_roles:
            raise ValueError(f"Approver role {approver.role} not authorized for {request.action}")
            
        # Kontrollera expiry
        now = datetime.now(timezone.utc)
        expires = datetime.fromisoformat(request.expires_at)
        if now > expires:
            request.status = AuthorizationStatus.EXPIRED
            raise ValueError("Request has expired")
        
        # Skapa beslut
        timestamp = now.isoformat()
        auth_decision = AuthorizationDecision(
            decision_id=str(uuid4()),
            request_id=request_id,
            approver=approver,
            decision=decision,
            reason=reason,
            timestamp=timestamp,
            signature_hash=self._sign_decision(request_id, approver.user_id, decision, timestamp)
        )
        
        # Uppdatera request
        request.approval_chain.append({
            "approver_id": approver.user_id,
            "decision": decision.value,
            "timestamp": timestamp
        })
        request.approvers.append(approver.user_id)
        
        # Kontrollera om tillräckligt många har godkänt
        min_approvers = requirements.get("min_approvers", 1)
        approved_count = len([
            a for a in request.approval_chain 
            if a["decision"] == AuthorizationStatus.APPROVED.value
        ])
        
        if decision == AuthorizationStatus.APPROVED and approved_count >= min_approvers:
            request.status = AuthorizationStatus.APPROVED
            del self.pending_requests[request_id]
            self.completed_requests.append(request)
        elif decision == AuthorizationStatus.REJECTED:
            request.status = AuthorizationStatus.REJECTED
            del self.pending_requests[request_id]
            self.completed_requests.append(request)
            
        self.decision_log.append(auth_decision)
        return auth_decision
    
    def _sign_decision(
        self,
        request_id: str,
        approver_id: str,
        decision: AuthorizationStatus,
        timestamp: str
    ) -> str:
        """Generera signatur-hash för beslut"""
        data = {
            "request_id": request_id,
            "approver_id": approver_id,
            "decision": decision.value,
            "timestamp": timestamp,
            "org_id": self.org_id
        }
        content = json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_pending(self) -> List[AuthorizationRequest]:
        """Hämta alla väntande förfrågningar"""
        return list(self.pending_requests.values())
    
    def get_audit_trail(self) -> List[Dict]:
        """Hämta fullständig audit trail"""
        return [d.to_dict() for d in self.decision_log]
    
    def is_authorized(self, request_id: str) -> bool:
        """Kontrollera om en request är godkänd"""
        for req in self.completed_requests:
            if req.request_id == request_id:
                return req.status == AuthorizationStatus.APPROVED
        return False


# =============================================================================
# EXEMPEL PÅ ANVÄNDNING
# =============================================================================
if __name__ == "__main__":
    # Skapa authorization module
    auth = AuthorizationModule(org_id="org_acme")
    
    # Skapa användare
    requester = User(
        user_id="user_123",
        name="Anna Andersson",
        email="anna@acme.se",
        role=Role.ANALYST,
        org_id="org_acme",
        active=True
    )
    
    approver1 = User(
        user_id="user_456",
        name="Björn Björnsson",
        email="bjorn@acme.se",
        role=Role.COMPLIANCE_OFFICER,
        org_id="org_acme",
        active=True
    )
    
    approver2 = User(
        user_id="user_789",
        name="Cecilia Carlsson",
        email="cecilia@acme.se",
        role=Role.DATA_PROTECTION_OFFICER,
        org_id="org_acme",
        active=True
    )
    
    # Skapa förfrågan
    request = auth.create_request(
        action=AuthorizationAction.UPDATE_RULE_PROFILE,
        requester=requester,
        target_resource="rule_profiles/ai_governance/acme/ai_policy.json",
        reason="Uppdatering av AI-policy enligt nya riktlinjer"
    )
    
    print(f"Request created: {request.request_id}")
    print(f"Status: {request.status.value}")
    print(f"Pending requests: {len(auth.get_pending())}")
    
    # Första godkännandet
    decision1 = auth.approve(
        request_id=request.request_id,
        approver=approver1,
        reason="Godkänt efter granskning"
    )
    print(f"\nFirst approval: {decision1.decision.value}")
    
    # Andra godkännandet (krävs för UPDATE_RULE_PROFILE)
    decision2 = auth.approve(
        request_id=request.request_id,
        approver=approver2,
        reason="Godkänt, inga invändningar"
    )
    print(f"Second approval: {decision2.decision.value}")
    
    # Kontrollera status
    print(f"\nIs authorized: {auth.is_authorized(request.request_id)}")
    print(f"Audit trail entries: {len(auth.get_audit_trail())}")
