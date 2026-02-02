"""
EVE CORE - STATUS ENGINE
=========================
Klassificerar alla AI-outputs enligt status contracts.
Garanterar att witness-mode alltid följs.

Patent-referens: Krav 6 - "blockera output som innehåller rekommendationsfraser"
"""

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict


class OutputStatus(Enum):
    """Status contracts enligt EVE Control Room Masterplan"""
    WITNESS_VERIFIED = "WITNESS_VERIFIED"
    PARTIAL_SOURCES = "PARTIAL_SOURCES"
    BLOCKED_RECOMMENDATION = "BLOCKED_RECOMMENDATION"
    DOMAIN_BOUNDARY = "DOMAIN_BOUNDARY"


@dataclass
class StatusResult:
    """Resultat från status-klassificering"""
    status: OutputStatus
    output: str
    original_output: str
    sources: List[Dict]
    blocked_phrases: List[str]
    blocked_intent: Optional[str]
    output_hash: str
    timestamp: str
    domain: str
    confidence: float
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        result['status'] = self.status.value
        return result


class StatusEngine:
    """
    EVE Core Status Engine
    
    Ansvarar för:
    1. Klassificera INPUT-intent (blockera rekommendationsfrågor)
    2. Klassificera OUTPUT enligt status contracts
    3. Blockera rekommendationer och beslut
    4. Verifiera källhänvisningar
    5. Generera output-hash för beviskedja
    """
    
    # ==========================================================================
    # FÖRBJUDNA INPUT-PATTERNS (frågor som begär rekommendation)
    # Alla patterns körs med re.IGNORECASE så case spelar ingen roll
    # ==========================================================================
    FORBIDDEN_QUESTION_PATTERNS = [
        # Engelska - frågor som begär råd (börjar med)
        r"^should\s+i\b",
        r"^should\s+we\b",
        r"^do\s+i\s+need\s+to\b",
        r"^do\s+we\s+need\s+to\b",
        r"^must\s+i\b",
        r"^must\s+we\b",
        r"^what\s+should\s+i\b",
        r"^what\s+should\s+we\b",
        r"^how\s+should\s+i\b",
        r"^how\s+should\s+we\b",
        r"^is\s+it\s+enough\b",
        r"^is\s+this\s+sufficient\b",
        r"^is\s+this\s+compliant\b",
        r"^are\s+we\s+compliant\b",
        r"^am\s+i\s+compliant\b",
        
        # Engelska - nyckelord var som helst i frågan
        r"\bshould\s+i\b",
        r"\bshould\s+we\b",
        r"\brecommend\b",
        r"\badvise\s+me\b",
        r"\bsuggest\b",
        r"\bdo\s+i\s+need\b",
        r"\bdo\s+we\s+need\b",
        r"\bis\s+it\s+ok\s+to\b",
        r"\bis\s+it\s+okay\s+to\b",
        r"\bcan\s+i\s+skip\b",
        r"\bcan\s+we\s+skip\b",
        
        # Svenska - frågor som begär råd
        r"^bör\s+jag\b",
        r"^bör\s+vi\b",
        r"^ska\s+jag\b",
        r"^ska\s+vi\b",
        r"^måste\s+jag\b",
        r"^måste\s+vi\b",
        r"^vad\s+bör\s+jag\b",
        r"^vad\s+bör\s+vi\b",
        r"^hur\s+bör\s+jag\b",
        r"^hur\s+bör\s+vi\b",
        r"^räcker\s+det\b",
        r"^är\s+det\s+tillräckligt\b",
        r"^är\s+vi\s+compliant\b",
        r"^följer\s+vi\b",
        
        # Svenska - nyckelord var som helst
        r"\bbör\s+jag\b",
        r"\bbör\s+vi\b",
        r"\brekommendera\b",
        r"\bföreslå\b",
        r"\bråda\b",
    ]
    
    # ==========================================================================
    # FÖRBJUDNA OUTPUT-FRASER
    # ==========================================================================
    FORBIDDEN_PHRASES = [
        # Svenska
        "du bör", "du ska", "du måste",
        "jag rekommenderar", "jag föreslår", "jag råder",
        "mitt råd är", "min rekommendation",
        "bästa tillvägagångssättet", "det bästa är",
        "ni bör", "ni ska", "ni måste",
        "ta åtgärd", "vidta åtgärder",
        "enligt min bedömning", "min bedömning är",
        "risken är", "riskklassificering:",
        "systemet klassificeras som",
        
        # Engelska
        "you should", "you must", "you need to",
        "i recommend", "i suggest", "i advise",
        "my recommendation", "my advice",
        "the best approach", "best practice is to",
        "take action", "you are required",
        "in my opinion", "my assessment is",
        "risk level:", "classified as",
        "compliance status:",
    ]
    
    # ==========================================================================
    # WITNESS-MODE REDIRECT RESPONSES
    # ==========================================================================
    REDIRECT_RESPONSE_EN = """EVE cannot answer questions that request recommendations, advice, or compliance assessments.

EVE can only:
• Cite what the regulation states
• Summarize requirements
• Show which articles apply

Please rephrase your question to ask WHAT the regulation says, not WHETHER you should do something.

Example:
❌ "Should I implement a DPIA?"
✅ "What does GDPR Article 35 say about DPIA requirements?"
"""

    REDIRECT_RESPONSE_SV = """EVE kan inte svara på frågor som begär rekommendationer, råd eller compliance-bedömningar.

EVE kan endast:
• Citera vad regelverket säger
• Sammanfatta krav
• Visa vilka artiklar som gäller

Omformulera din fråga för att fråga VAD regelverket säger, inte OM du bör göra något.

Exempel:
❌ "Bör jag genomföra en DPIA?"
✅ "Vad säger GDPR artikel 35 om krav på DPIA?"
"""

    def __init__(self, domain: str = "generic", language: str = "en"):
        self.domain = domain
        self.language = language
        self.blocked_count = 0
        self.verified_count = 0
        self.intent_blocked_count = 0
        
    def classify(
        self,
        output: str,
        sources: List[Dict],
        scope_documents: List[str],
        question: Optional[str] = None
    ) -> StatusResult:
        """
        Klassificera en AI-output enligt status contracts.
        """
        original_output = output
        blocked_phrases = []
        blocked_intent = None
        
        # =======================================================
        # STEG 0: KLASSIFICERA INPUT-INTENT
        # =======================================================
        if question:
            intent_blocked, matched_pattern = self._classify_intent(question)
            if intent_blocked:
                self.intent_blocked_count += 1
                self.blocked_count += 1
                blocked_intent = matched_pattern
                
                redirect = (
                    self.REDIRECT_RESPONSE_SV 
                    if self._is_swedish(question) 
                    else self.REDIRECT_RESPONSE_EN
                )
                
                return StatusResult(
                    status=OutputStatus.BLOCKED_RECOMMENDATION,
                    output=redirect,
                    original_output=original_output,
                    sources=[],
                    blocked_phrases=[],
                    blocked_intent=blocked_intent,
                    output_hash=self._generate_hash(redirect, []),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    domain=self.domain,
                    confidence=1.0
                )
        
        # =======================================================
        # STEG 1: KONTROLLERA FÖRBJUDNA FRASER I OUTPUT
        # =======================================================
        output, blocked = self._block_recommendations(output)
        blocked_phrases.extend(blocked)
        
        # =======================================================
        # STEG 2: VERIFIERA KÄLLOR
        # =======================================================
        sources_valid, source_issues = self._verify_sources(sources, scope_documents)
        
        # =======================================================
        # STEG 3: KLASSIFICERA STATUS
        # =======================================================
        if blocked_phrases:
            status = OutputStatus.BLOCKED_RECOMMENDATION
            self.blocked_count += 1
            confidence = 1.0
        elif not sources:
            status = OutputStatus.DOMAIN_BOUNDARY
            confidence = 0.5
        elif not sources_valid:
            status = OutputStatus.PARTIAL_SOURCES
            confidence = 0.7
        else:
            status = OutputStatus.WITNESS_VERIFIED
            self.verified_count += 1
            confidence = 1.0
            
        # =======================================================
        # STEG 4: GENERERA HASH
        # =======================================================
        output_hash = self._generate_hash(output, sources)
        
        return StatusResult(
            status=status,
            output=output,
            original_output=original_output,
            sources=sources,
            blocked_phrases=blocked_phrases,
            blocked_intent=blocked_intent,
            output_hash=output_hash,
            timestamp=datetime.now(timezone.utc).isoformat(),
            domain=self.domain,
            confidence=confidence
        )
    
    def _classify_intent(self, question: str) -> Tuple[bool, Optional[str]]:
        """
        Klassificera fråge-intent.
        
        Returnerar (blocked, matched_pattern) om frågan begär rekommendation.
        """
        question_clean = question.strip()
        
        for pattern in self.FORBIDDEN_QUESTION_PATTERNS:
            # Använd IGNORECASE för att matcha oavsett case
            match = re.search(pattern, question_clean, re.IGNORECASE)
            if match:
                return True, pattern
                
        return False, None
    
    def _is_swedish(self, text: str) -> bool:
        """Enkel språkdetektering"""
        swedish_indicators = ['jag', 'vi', 'vad', 'hur', 'bör', 'ska', 'måste', 'är', 'det']
        text_lower = text.lower()
        swedish_count = sum(1 for word in swedish_indicators if word in text_lower)
        return swedish_count >= 2
    
    def _block_recommendations(self, text: str) -> Tuple[str, List[str]]:
        """Blockera och ersätt rekommendationsfraser"""
        blocked = []
        modified_text = text.lower()
        
        for phrase in self.FORBIDDEN_PHRASES:
            if phrase.lower() in modified_text:
                blocked.append(phrase)
                
        if blocked:
            replacement = (
                "\n\n[BLOCKED: Recommendation/decision blocked by EVE Status Engine. "
                "Only facts and citations from approved sources are shown.]\n\n"
            )
            
            sentences = text.split('.')
            filtered = []
            for sentence in sentences:
                contains_forbidden = any(
                    phrase.lower() in sentence.lower() 
                    for phrase in self.FORBIDDEN_PHRASES
                )
                if not contains_forbidden:
                    filtered.append(sentence)
                    
            text = '.'.join(filtered)
            if blocked:
                text += replacement
                
        return text, blocked
    
    def _verify_sources(
        self, 
        sources: List[Dict], 
        scope_documents: List[str]
    ) -> Tuple[bool, List[str]]:
        """Verifiera att alla källor är inom scope"""
        issues = []
        
        for source in sources:
            doc_id = source.get('doc_id', '')
            
            in_scope = any(
                self._match_scope(doc_id, scope_pattern)
                for scope_pattern in scope_documents
            )
            
            if not in_scope:
                issues.append(f"Source {doc_id} not in scope")
                
            if 'version' not in source:
                issues.append(f"Source {doc_id} missing version")
                
        return len(issues) == 0, issues
    
    def _match_scope(self, doc_id: str, pattern: str) -> bool:
        """Matcha dokument-ID mot scope-pattern (stödjer **)"""
        if pattern.endswith('**'):
            prefix = pattern[:-2]
            return doc_id.startswith(prefix)
        return doc_id == pattern
    
    def _generate_hash(self, output: str, sources: List[Dict]) -> str:
        """Generera SHA-256 hash av output + källor"""
        data = {
            'output': output,
            'sources': sources,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        content = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content.encode()).hexdigest()
    
    def get_stats(self) -> Dict:
        """Returnera statistik"""
        total_blocked = self.blocked_count
        total_processed = self.verified_count + self.blocked_count
        
        return {
            'domain': self.domain,
            'verified_count': self.verified_count,
            'blocked_count': total_blocked,
            'intent_blocked_count': self.intent_blocked_count,
            'block_rate': (
                total_blocked / total_processed
                if total_processed > 0 else 0
            )
        }


# =============================================================================
# QUICK TEST
# =============================================================================
if __name__ == "__main__":
    engine = StatusEngine(domain="ai_governance")
    
    # Test intent blocking
    test_questions = [
        "Should I implement a DPIA?",
        "should i implement a DPIA?",
        "Do I need to do a risk assessment?",
        "What does GDPR Article 35 say?",
        "Bör jag genomföra en DPIA?",
    ]
    
    print("INTENT CLASSIFICATION TEST")
    print("=" * 50)
    
    for q in test_questions:
        result = engine.classify(
            output="test",
            sources=[],
            scope_documents=["knowledge/documents/eu/**"],
            question=q
        )
        blocked = "🚫 BLOCKED" if result.blocked_intent else "✅ ALLOWED"
        print(f"{blocked}: {q}")
        if result.blocked_intent:
            print(f"         Pattern: {result.blocked_intent}")
    
    print()
    print(f"Stats: {engine.get_stats()}")
