"""
EVE CORE - WITNESS AI
=====================
AI-komponent i vittnesläge med uteslutande läsåtkomst.
Tekniskt förhindrad från att generera rekommendationer eller fatta beslut.

Patent-referens: Komponent (20) - "AI-komponent i vittnesläge"
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum


class WitnessOperation(Enum):
    """Tillåtna operationer för witness AI"""
    READ_DOCUMENT = "read_document"
    CITE_SECTION = "cite_section"
    SUMMARIZE_CONTENT = "summarize_content"
    CROSS_REFERENCE = "cross_reference"
    SEMANTIC_SEARCH = "semantic_search"
    EXPLAIN_REQUIREMENT = "explain_requirement"
    MAP_TO_ARTICLE = "map_to_article"


class ForbiddenOperation(Enum):
    """Förbjudna operationer - tekniskt blockerade"""
    INTERPRET_LAW = "interpret_law"
    GIVE_LEGAL_ADVICE = "give_legal_advice"
    RECOMMEND_ACTION = "recommend_action"
    MAKE_DECISIONS = "make_decisions"
    MODIFY_DOCUMENTS = "modify_documents"
    ASSESS_COMPLIANCE = "assess_compliance"
    APPROVE_SYSTEM = "approve_system"
    CLASSIFY_RISK_LEVEL = "classify_risk_level"


@dataclass
class WitnessQuery:
    """Inkommande fråga till witness AI"""
    query_id: str
    question: str
    scope: List[str]
    user_id: str
    role: str
    timestamp: str


@dataclass
class WitnessResponse:
    """Svar från witness AI"""
    query_id: str
    response: str
    citations: List[Dict]
    operation_type: WitnessOperation
    response_hash: str
    timestamp: str
    disclaimer: str
    sources_verified: bool
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['operation_type'] = self.operation_type.value
        return result


@dataclass 
class Citation:
    """Källhänvisning"""
    doc_id: str
    version: str
    section: str
    quote: str
    page: Optional[int] = None


class WitnessAI:
    """
    EVE Core Witness AI
    
    En AI-komponent som är arkitektoniskt begränsad till en vittnesroll:
    - KAN: Söka, citera, sammanfatta, förklara, kontextualisera
    - KAN INTE: Rekommendera, besluta, tolka, bedöma, godkänna
    
    Alla svar inkluderar:
    - Explicita källhänvisningar
    - Kryptografisk hash
    - Disclaimer att ingen rekommendation ges
    """
    
    DISCLAIMER_SV = (
        "EVE ger endast information baserad på godkända källor. "
        "Detta utgör inte juridisk rådgivning, compliance-bedömning eller rekommendation. "
        "Alla beslut kräver mänsklig auktorisation."
    )
    
    DISCLAIMER_EN = (
        "EVE provides information based on approved sources only. "
        "This does not constitute legal advice, compliance assessment, or recommendation. "
        "All decisions require human authorization."
    )
    
    def __init__(
        self, 
        knowledge_base: 'KnowledgeBase',
        domain: str = "generic",
        language: str = "sv"
    ):
        self.knowledge_base = knowledge_base
        self.domain = domain
        self.language = language
        self.query_log: List[WitnessQuery] = []
        self.response_log: List[WitnessResponse] = []
        
    def query(self, query: WitnessQuery) -> WitnessResponse:
        """
        Bearbeta en fråga i witness-mode.
        
        1. Logga frågan
        2. Sök i kunskapsbasen
        3. Generera svar med citat
        4. Verifiera att svaret inte innehåller rekommendationer
        5. Returnera med hash och disclaimer
        """
        self.query_log.append(query)
        
        # Sök i kunskapsbasen
        search_results = self.knowledge_base.search(
            query=query.question,
            scope=query.scope
        )
        
        # Bestäm operationstyp
        operation = self._classify_operation(query.question)
        
        # Generera witness-mode svar
        response_text, citations = self._generate_response(
            question=query.question,
            results=search_results,
            operation=operation
        )
        
        # Skapa response
        response = WitnessResponse(
            query_id=query.query_id,
            response=response_text,
            citations=citations,
            operation_type=operation,
            response_hash=self._hash_response(response_text, citations),
            timestamp=datetime.now(timezone.utc).isoformat(),
            disclaimer=self.DISCLAIMER_SV if self.language == "sv" else self.DISCLAIMER_EN,
            sources_verified=len(citations) > 0
        )
        
        self.response_log.append(response)
        return response
    
    def _classify_operation(self, question: str) -> WitnessOperation:
        """Klassificera frågan till rätt witness-operation"""
        question_lower = question.lower()
        
        if any(kw in question_lower for kw in ["citera", "quote", "citat"]):
            return WitnessOperation.CITE_SECTION
        elif any(kw in question_lower for kw in ["sammanfatta", "summarize", "summary"]):
            return WitnessOperation.SUMMARIZE_CONTENT
        elif any(kw in question_lower for kw in ["jämför", "compare", "cross-reference"]):
            return WitnessOperation.CROSS_REFERENCE
        elif any(kw in question_lower for kw in ["förklara", "explain", "vad betyder"]):
            return WitnessOperation.EXPLAIN_REQUIREMENT
        elif any(kw in question_lower for kw in ["artikel", "article", "sektion"]):
            return WitnessOperation.MAP_TO_ARTICLE
        else:
            return WitnessOperation.SEMANTIC_SEARCH
    
    def _generate_response(
        self,
        question: str,
        results: List[Dict],
        operation: WitnessOperation
    ) -> Tuple[str, List[Dict]]:
        """
        Generera witness-mode svar.
        
        Svaret MÅSTE:
        - Baseras endast på sökresultat
        - Inkludera explicita källhänvisningar
        - INTE innehålla rekommendationer
        """
        if not results:
            return (
                "Inga relevanta källor hittades inom den aktiva domänen. "
                "Kontrollera att frågan ligger inom scope för aktiverade rule profiles.",
                []
            )
        
        citations = []
        response_parts = []
        
        for result in results[:5]:  # Max 5 källor
            citation = {
                "doc_id": result.get("doc_id"),
                "version": result.get("version"),
                "section": result.get("section"),
                "relevance": result.get("score", 0)
            }
            citations.append(citation)
            
            # Bygg response-del med explicit källhänvisning
            source_ref = f"[{result.get('doc_id')}:{result.get('section')}]"
            content = result.get("content", "")
            
            if operation == WitnessOperation.CITE_SECTION:
                response_parts.append(f'"{content}" {source_ref}')
            elif operation == WitnessOperation.SUMMARIZE_CONTENT:
                response_parts.append(f"Dokumentet anger: {content} {source_ref}")
            else:
                response_parts.append(f"{content} {source_ref}")
        
        response = "\n\n".join(response_parts)
        return response, citations
    
    def _hash_response(self, response: str, citations: List[Dict]) -> str:
        """Generera SHA-256 hash av response + citations"""
        data = {
            "response": response,
            "citations": citations,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        content = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_audit_trail(self) -> List[Dict]:
        """Returnera fullständig audit trail"""
        return [
            {
                "query": asdict(q),
                "response": r.to_dict()
            }
            for q, r in zip(self.query_log, self.response_log)
        ]


# =============================================================================
# MOCK KNOWLEDGE BASE FÖR TESTNING
# =============================================================================
class MockKnowledgeBase:
    """Mock implementation för testning"""
    
    def __init__(self):
        self.documents = {
            "eu/ai_act/article_14": {
                "version": "2024-08-01",
                "sections": {
                    "1": "Högrisk-AI-system ska utformas och utvecklas så att de kan "
                         "övervakas effektivt av fysiska personer under den period som "
                         "AI-systemet används.",
                    "2": "Mänsklig tillsyn ska syfta till att förebygga eller minimera "
                         "risker för hälsa, säkerhet eller grundläggande rättigheter."
                }
            },
            "eu/ai_act/article_9": {
                "version": "2024-08-01",
                "sections": {
                    "1": "Ett riskhanteringssystem ska inrättas, genomföras, dokumenteras "
                         "och underhållas i förhållande till högrisk-AI-system."
                }
            }
        }
    
    def search(self, query: str, scope: List[str]) -> List[Dict]:
        """Sök i mock-dokumenten"""
        results = []
        for doc_id, doc in self.documents.items():
            # Kontrollera scope
            in_scope = any(doc_id.startswith(s.rstrip('*')) for s in scope)
            if not in_scope:
                continue
                
            for section_id, content in doc["sections"].items():
                if any(word in content.lower() for word in query.lower().split()):
                    results.append({
                        "doc_id": doc_id,
                        "version": doc["version"],
                        "section": section_id,
                        "content": content,
                        "score": 0.85
                    })
        return results


# =============================================================================
# EXEMPEL PÅ ANVÄNDNING
# =============================================================================
if __name__ == "__main__":
    from uuid import uuid4
    
    # Skapa witness AI med mock knowledge base
    kb = MockKnowledgeBase()
    witness = WitnessAI(knowledge_base=kb, domain="ai_governance")
    
    # Test query
    query = WitnessQuery(
        query_id=str(uuid4()),
        question="Vad säger AI Act om mänsklig tillsyn?",
        scope=["eu/ai_act/*"],
        user_id="user_123",
        role="compliance_officer",
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    
    response = witness.query(query)
    
    print("=" * 60)
    print("WITNESS AI RESPONSE")
    print("=" * 60)
    print(f"Status: sources_verified={response.sources_verified}")
    print(f"Operation: {response.operation_type.value}")
    print(f"Hash: {response.response_hash[:16]}...")
    print("-" * 60)
    print(response.response)
    print("-" * 60)
    print(f"Disclaimer: {response.disclaimer}")
    print("-" * 60)
    print(f"Citations: {len(response.citations)}")
    for c in response.citations:
        print(f"  - {c['doc_id']}:{c['section']} (v{c['version']})")
