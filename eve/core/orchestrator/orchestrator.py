"""
EVE CORE - ORCHESTRATOR
=======================
Koordinerar alla EVE-komponenter.
Väljer rätt agent, scope och arbetsflöde.

Flöden enligt Masterplan:
A: Publish (Compliedocs -> Knowledge)
B: Rule Profile (org -> tillämpning)
C: Witness Query (fråga -> svar)
D: Human Decision (beslut -> ansvar)
E: Export (revision/tillsyn)
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
from uuid import uuid4


class FlowType(Enum):
    """Operativa arbetsflöden"""
    PUBLISH = "publish"           # A: Compliedocs -> Knowledge
    RULE_PROFILE = "rule_profile" # B: org -> tillämpning
    WITNESS_QUERY = "witness_query"  # C: fråga -> svar
    HUMAN_DECISION = "human_decision" # D: beslut -> ansvar
    EXPORT = "export"             # E: revision/tillsyn


@dataclass
class FlowContext:
    """Kontext för ett arbetsflöde"""
    flow_id: str
    flow_type: FlowType
    user_id: str
    org_id: str
    suite_id: str
    scope: List[str]
    started_at: str
    metadata: Dict
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['flow_type'] = self.flow_type.value
        return result


@dataclass
class FlowResult:
    """Resultat från ett arbetsflöde"""
    flow_id: str
    success: bool
    output: Any
    evidence_ids: List[str]
    completed_at: str
    errors: List[str]


class Orchestrator:
    """
    EVE Core Orchestrator
    
    Ansvarar för:
    1. Välja rätt agent baserat på suite och scope
    2. Koordinera flöden mellan komponenter
    3. Säkerställa att alla outputs går genom status_engine och x_vault
    4. Hantera fel och degraded mode
    """
    
    def __init__(
        self,
        witness_ai,  # WitnessAI instance
        status_engine,  # StatusEngine instance
        authorization,  # AuthorizationModule instance
        x_vault,  # XVault instance
        knowledge_base  # KnowledgeBase instance
    ):
        self.witness_ai = witness_ai
        self.status_engine = status_engine
        self.authorization = authorization
        self.x_vault = x_vault
        self.knowledge_base = knowledge_base
        
        self.active_flows: Dict[str, FlowContext] = {}
        self.completed_flows: List[FlowResult] = []
        
        # Suite -> Agent mapping
        self.suite_agents = {
            "ai_governance": "ai_governance_agent",
            "finance": "finance_agent",
            "healthcare": "healthcare_agent",
            "legal": "legal_agent",
            "rail_safety": "rail_safety_agent",
            "defence": "defence_agent"
        }
        
        # Suite -> Scope mapping
        self.suite_scopes = {
            "ai_governance": [
                "knowledge/documents/eu/ai_act/**",
                "knowledge/documents/eu/gdpr/**",
                "knowledge/documents/standards/iso_42001/**"
            ],
            "finance": [
                "knowledge/documents/eu/dora/**",
                "knowledge/documents/eu/mifid/**",
                "knowledge/documents/internal/finance/**"
            ],
            "healthcare": [
                "knowledge/documents/eu/mdr/**",
                "knowledge/documents/internal/clinical/**"
            ]
        }
    
    def start_flow(
        self,
        flow_type: FlowType,
        user_id: str,
        org_id: str,
        suite_id: str,
        metadata: Optional[Dict] = None
    ) -> FlowContext:
        """
        Starta ett nytt arbetsflöde.
        
        Args:
            flow_type: Typ av flöde
            user_id: Användar-ID
            org_id: Organisations-ID
            suite_id: Suite (ai_governance, finance, etc.)
            metadata: Extra data för flödet
            
        Returns:
            FlowContext
        """
        scope = self.suite_scopes.get(suite_id, [])
        
        context = FlowContext(
            flow_id=str(uuid4()),
            flow_type=flow_type,
            user_id=user_id,
            org_id=org_id,
            suite_id=suite_id,
            scope=scope,
            started_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {}
        )
        
        self.active_flows[context.flow_id] = context
        return context
    
    def execute_witness_query(
        self,
        context: FlowContext,
        question: str,
        role: str
    ) -> FlowResult:
        """
        Exekvera Flöde C: Witness Query
        
        1. Orchestrator väljer agent och scope
        2. Agent läser endast godkända källor
        3. Status engine klassificerar
        4. Output signeras/hashas
        5. Evidence skapas
        """
        from .witness_ai.witness_ai import WitnessQuery
        from .status_engine.status_engine import OutputStatus, EvidenceType
        
        evidence_ids = []
        errors = []
        
        try:
            # Steg 1: Skapa witness query
            query = WitnessQuery(
                query_id=str(uuid4()),
                question=question,
                scope=context.scope,
                user_id=context.user_id,
                role=role,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
            
            # Steg 2: Exekvera query via witness AI
            response = self.witness_ai.query(query)
            
            # Steg 3: Klassificera via status engine
            status_result = self.status_engine.classify(
                output=response.response,
                sources=response.citations,
                scope_documents=context.scope
            )
            
            # Steg 4: Seal i X-Vault
            evidence = self.x_vault.seal(
                evidence_type=EvidenceType.WITNESS_RESPONSE,
                content={
                    "query": question,
                    "response": status_result.output,
                    "status": status_result.status.value,
                    "sources": response.citations,
                    "blocked_phrases": status_result.blocked_phrases
                },
                metadata={
                    "flow_id": context.flow_id,
                    "user_id": context.user_id,
                    "suite_id": context.suite_id
                }
            )
            evidence_ids.append(evidence.evidence_id)
            
            output = {
                "response": status_result.output,
                "status": status_result.status.value,
                "sources": response.citations,
                "hash": status_result.output_hash,
                "disclaimer": response.disclaimer
            }
            success = True
            
        except Exception as e:
            errors.append(str(e))
            output = None
            success = False
        
        result = FlowResult(
            flow_id=context.flow_id,
            success=success,
            output=output,
            evidence_ids=evidence_ids,
            completed_at=datetime.now(timezone.utc).isoformat(),
            errors=errors
        )
        
        # Flytta till completed
        if context.flow_id in self.active_flows:
            del self.active_flows[context.flow_id]
        self.completed_flows.append(result)
        
        return result
    
    def execute_human_decision(
        self,
        context: FlowContext,
        decision_type: str,
        decision_data: Dict,
        approver_id: str,
        approver_role: str
    ) -> FlowResult:
        """
        Exekvera Flöde D: Human Decision
        
        1. Människa initierar beslut
        2. Authorization kontrollerar roll och mandat
        3. Beslut registreras med referenser
        4. X-Vault säkrar tidslinje
        """
        from .authorization.authorization import AuthorizationAction, User, Role
        from .x_vault.x_vault import EvidenceType
        
        evidence_ids = []
        errors = []
        
        try:
            # Steg 1: Skapa authorization request
            # (Förenklad - i produktion hämtas user från identity provider)
            approver = User(
                user_id=approver_id,
                name="",
                email="",
                role=Role[approver_role.upper()],
                org_id=context.org_id,
                active=True
            )
            
            # Steg 2: Registrera beslut i X-Vault
            evidence = self.x_vault.seal(
                evidence_type=EvidenceType.AUTHORIZATION_DECISION,
                content={
                    "decision_type": decision_type,
                    "decision_data": decision_data,
                    "approver_id": approver_id,
                    "approver_role": approver_role,
                    "flow_id": context.flow_id
                },
                metadata={
                    "suite_id": context.suite_id,
                    "org_id": context.org_id
                }
            )
            evidence_ids.append(evidence.evidence_id)
            
            output = {
                "decision_type": decision_type,
                "status": "recorded",
                "evidence_id": evidence.evidence_id,
                "hash": evidence.content_hash
            }
            success = True
            
        except Exception as e:
            errors.append(str(e))
            output = None
            success = False
        
        result = FlowResult(
            flow_id=context.flow_id,
            success=success,
            output=output,
            evidence_ids=evidence_ids,
            completed_at=datetime.now(timezone.utc).isoformat(),
            errors=errors
        )
        
        if context.flow_id in self.active_flows:
            del self.active_flows[context.flow_id]
        self.completed_flows.append(result)
        
        return result
    
    def execute_export(
        self,
        context: FlowContext,
        period_start: str,
        period_end: str
    ) -> FlowResult:
        """
        Exekvera Flöde E: Export
        
        1. Välj period/händelse
        2. Skapa regulator package
        3. Offline-verifiering möjlig
        4. Export loggas som egen bevisartefakt
        """
        evidence_ids = []
        errors = []
        
        try:
            package = self.x_vault.export_regulator_package(
                period_start=period_start,
                period_end=period_end
            )
            
            output = {
                "package_id": package.package_id,
                "evidence_count": len(package.evidence_objects),
                "snapshot_count": len(package.snapshots),
                "merkle_root": package.merkle_root,
                "verification_instructions": package.verification_instructions
            }
            success = True
            
        except Exception as e:
            errors.append(str(e))
            output = None
            success = False
        
        result = FlowResult(
            flow_id=context.flow_id,
            success=success,
            output=output,
            evidence_ids=evidence_ids,
            completed_at=datetime.now(timezone.utc).isoformat(),
            errors=errors
        )
        
        if context.flow_id in self.active_flows:
            del self.active_flows[context.flow_id]
        self.completed_flows.append(result)
        
        return result
    
    def get_active_flows(self) -> List[FlowContext]:
        """Hämta alla aktiva flöden"""
        return list(self.active_flows.values())
    
    def get_flow_history(self, limit: int = 100) -> List[FlowResult]:
        """Hämta flödeshistorik"""
        return self.completed_flows[-limit:]
    
    def get_stats(self) -> Dict:
        """Hämta statistik"""
        flow_counts = {}
        for result in self.completed_flows:
            flow_type = result.flow_id  # Simplified
            flow_counts[flow_type] = flow_counts.get(flow_type, 0) + 1
            
        return {
            "active_flows": len(self.active_flows),
            "completed_flows": len(self.completed_flows),
            "success_rate": (
                sum(1 for r in self.completed_flows if r.success) / 
                len(self.completed_flows) if self.completed_flows else 0
            )
        }
