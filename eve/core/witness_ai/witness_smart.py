"""
EVE WITNESS SMART — Claude-powered question interpretation & synthesis
======================================================================
Integrates with existing WitnessAI architecture.

Uses Claude API as:
  1. Question Interpreter - extracts search terms from natural language
  2. Witness Synthesizer - creates answers ONLY from approved citations

EVE Principle: Claude interprets, EVE provides knowledge, Claude synthesizes.
               Claude NEVER adds external knowledge or advice.
"""

import os
import json
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass

# Try httpx for async, fallback to requests
try:
    import httpx
    ASYNC_AVAILABLE = True
except ImportError:
    import requests
    ASYNC_AVAILABLE = False

# Anthropic API config
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-20250514"


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass
class SmartWitnessRequest:
    question: str
    language: str = "en"
    jurisdiction: str = "EU"
    regulations: Optional[List[str]] = None


@dataclass  
class SmartWitnessCitation:
    regulation: str
    article: str
    quote: str
    source_id: str
    
    def to_dict(self) -> Dict:
        return {
            "regulation": self.regulation,
            "article": self.article,
            "quote": self.quote,
            "source_id": self.source_id
        }


@dataclass
class SmartWitnessResponse:
    answer: str
    citations: List[SmartWitnessCitation]
    witness_mode: bool = True
    llm_trace: Dict = None
    search_terms: List[str] = None
    response_hash: str = None
    disclaimer: str = None
    
    def to_dict(self) -> Dict:
        return {
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "witness_mode": self.witness_mode,
            "llm_trace": self.llm_trace or {},
            "search_terms": self.search_terms or [],
            "response_hash": self.response_hash,
            "disclaimer": self.disclaimer
        }


# ============================================================
# CLAUDE API HELPER
# ============================================================

def call_claude_sync(system_prompt: str, user_message: str) -> str:
    """Call Claude API synchronously."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01"
    }
    
    payload = {
        "model": MODEL,
        "max_tokens": 2000,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_message}
        ]
    }
    
    if ASYNC_AVAILABLE:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    else:
        response = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
    
    return data["content"][0]["text"]


async def call_claude_async(system_prompt: str, user_message: str) -> str:
    """Call Claude API asynchronously."""
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY environment variable not set")
    
    if not ASYNC_AVAILABLE:
        # Fallback to sync
        return call_claude_sync(system_prompt, user_message)
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01"
    }
    
    payload = {
        "model": MODEL,
        "max_tokens": 2000,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": user_message}
        ]
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(ANTHROPIC_API_URL, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
    
    return data["content"][0]["text"]


# ============================================================
# STEP 1: QUESTION INTERPRETER
# ============================================================

INTERPRETER_SYSTEM_PROMPT = """You are a Question Interpreter for EU regulatory compliance.

Your job is to extract regulatory concepts and search terms from user questions.
You do NOT answer questions. You only analyze them.

Output JSON only, no markdown, no explanation:
{
  "regulations": ["GDPR", "AI Act", "NIS2", "DORA", "CRA"],
  "search_terms": ["term1", "term2", "term3"],
  "article_hints": ["35", "9"],
  "confidence": "high"
}

Rules:
- regulations: Which EU regulations are relevant (GDPR, AI Act, NIS2, DORA, CRA)
- search_terms: 3-8 specific keywords to search for
- article_hints: If specific articles are mentioned, include just the number
- confidence: high/medium/low based on how clear the question is
- Be specific: "data protection impact assessment" not just "assessment"
- Include synonyms when helpful: "DPIA", "impact assessment"
"""

def interpret_question(question: str) -> Dict:
    """Extract search terms and relevant regulations from question."""
    try:
        response = call_claude_sync(INTERPRETER_SYSTEM_PROMPT, question)
        
        # Clean response - remove markdown if present
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()
        
        return json.loads(response)
    except Exception as e:
        print(f"[WARN] Interpreter failed: {e}")
        # Fallback: simple keyword extraction
        words = question.lower().split()
        keywords = [w for w in words if len(w) > 4 and w not in ['about', 'which', 'where', 'there', 'their', 'under']]
        return {
            "regulations": ["GDPR", "AI Act", "NIS2"],
            "search_terms": keywords[:5],
            "article_hints": [],
            "confidence": "low"
        }


async def interpret_question_async(question: str) -> Dict:
    """Async version of interpret_question."""
    try:
        response = await call_claude_async(INTERPRETER_SYSTEM_PROMPT, question)
        
        response = response.strip()
        if response.startswith("```"):
            response = response.split("```")[1]
            if response.startswith("json"):
                response = response[4:]
        response = response.strip()
        
        return json.loads(response)
    except Exception as e:
        print(f"[WARN] Interpreter failed: {e}")
        words = question.lower().split()
        keywords = [w for w in words if len(w) > 4]
        return {
            "regulations": ["GDPR", "AI Act", "NIS2"],
            "search_terms": keywords[:5],
            "article_hints": [],
            "confidence": "low"
        }


# ============================================================
# STEP 2: EVE KNOWLEDGE SEARCH
# ============================================================

def search_eve_knowledge(
    search_terms: List[str], 
    regulations: List[str],
    knowledge_path,
    article_hints: List[str] = None
) -> List[Dict]:
    """
    Search EVE Knowledge Base for approved articles matching search terms.
    
    Args:
        search_terms: Keywords to search for
        regulations: Filter to these regulations
        knowledge_path: Path to knowledge base
        article_hints: Specific article numbers to prioritize
    
    Returns:
        List of citation dicts with quotes
    """
    from pathlib import Path
    
    citations = []
    seen = set()
    
    # Map regulation names to folder names
    reg_map = {
        "GDPR": "gdpr",
        "AI Act": "ai_act", 
        "AI_Act": "ai_act",
        "NIS2": "nis2",
        "DORA": "dora",
        "CRA": "cra"
    }
    
    # Convert regulations to folder names
    reg_folders = []
    for reg in regulations:
        folder = reg_map.get(reg, reg.lower().replace(" ", "_"))
        reg_folders.append(folder)
    
    knowledge_base = Path(knowledge_path) / "documents" / "eu"
    
    for reg_folder in reg_folders:
        articles_dir = knowledge_base / reg_folder / "articles"
        if not articles_dir.exists():
            continue
        
        for article_file in articles_dir.glob("article_*.json"):
            try:
                data = json.loads(article_file.read_text(encoding='utf-8'))
                
                # Only APPROVED articles
                status = data.get("eve_metadata", {}).get("status", "")
                if status not in ["APPROVED", "APPROVED_WITH_OBSERVATION"]:
                    continue
                
                art_num = str(data.get("article_number", ""))
                content = data.get("content", "").lower()
                title = data.get("title", "").lower()
                
                # Check if any search term matches
                matches = False
                
                # Prioritize article hints
                if article_hints and art_num in article_hints:
                    matches = True
                else:
                    for term in search_terms:
                        if term.lower() in content or term.lower() in title:
                            matches = True
                            break
                
                if not matches:
                    continue
                
                # Avoid duplicates
                key = f"{reg_folder}_{art_num}"
                if key in seen:
                    continue
                seen.add(key)
                
                # Get regulation display name
                reg_names = {
                    "gdpr": "GDPR",
                    "ai_act": "EU AI Act",
                    "nis2": "NIS2",
                    "dora": "DORA",
                    "cra": "CRA"
                }
                
                # Extract relevant quote (first 500 chars or matching section)
                quote = data.get("content", "")[:500]
                if len(quote) == 500:
                    quote += "..."
                
                citations.append({
                    "regulation": reg_names.get(reg_folder, reg_folder.upper()),
                    "article": f"Art. {art_num}",
                    "quote": quote,
                    "source_id": key,
                    "title": data.get("title", f"Article {art_num}"),
                    "source_url": data.get("source_url", "")
                })
                
            except Exception as e:
                print(f"[WARN] Error reading {article_file}: {e}")
                continue
    
    return citations[:10]  # Max 10 citations


# ============================================================
# STEP 3: WITNESS SYNTHESIZER
# ============================================================

SYNTHESIZER_SYSTEM_PROMPT = """You are a Witness Synthesizer for EU regulatory compliance.

CRITICAL RULES - YOU MUST FOLLOW THESE:
1. Use ONLY the provided citations to answer
2. Do NOT add advice, opinions, or interpretations
3. Do NOT use any external knowledge beyond the citations
4. If citations are insufficient, say "Based on the approved knowledge base, I cannot fully answer this question."
5. Cite specific articles when making statements: "According to GDPR Art. 35..."
6. Be factual and precise - you are a witness, not an advisor

FORBIDDEN PHRASES (never use these):
- "I recommend..."
- "You should..."
- "It would be advisable..."
- "In my opinion..."
- "I suggest..."

REQUIRED STRUCTURE:
1. Direct answer based on citations
2. Reference to specific articles
3. If multiple regulations apply, organize by regulation

You are summarizing what the law SAYS, not what someone should DO.
"""

def synthesize_answer(question: str, citations: List[Dict], language: str) -> str:
    """Generate answer using ONLY the provided citations."""
    if not citations:
        return (
            "Based on the approved EVE knowledge base, no relevant approved articles were found for this question. "
            "Please ensure the relevant regulatory articles have been approved in EVE Control Room."
        )
    
    # Build citation context
    citation_text = "APPROVED CITATIONS (use ONLY these to answer):\n\n"
    for i, c in enumerate(citations, 1):
        citation_text += f"[{i}] {c['regulation']} {c['article']}\n"
        citation_text += f"    Title: {c.get('title', 'N/A')}\n"
        citation_text += f"    Content: {c['quote']}\n\n"
    
    user_message = f"""Question: {question}

{citation_text}

Provide a factual answer based ONLY on the citations above.
Do not add any information not found in the citations.
Do not give advice or recommendations.
Respond in: {language}"""

    try:
        return call_claude_sync(SYNTHESIZER_SYSTEM_PROMPT, user_message)
    except Exception as e:
        print(f"[ERROR] Synthesizer failed: {e}")
        return "An error occurred while generating the answer. Please try again."


async def synthesize_answer_async(question: str, citations: List[Dict], language: str) -> str:
    """Async version of synthesize_answer."""
    if not citations:
        return (
            "Based on the approved EVE knowledge base, no relevant approved articles were found for this question. "
            "Please ensure the relevant regulatory articles have been approved in EVE Control Room."
        )
    
    citation_text = "APPROVED CITATIONS (use ONLY these to answer):\n\n"
    for i, c in enumerate(citations, 1):
        citation_text += f"[{i}] {c['regulation']} {c['article']}\n"
        citation_text += f"    Title: {c.get('title', 'N/A')}\n"
        citation_text += f"    Content: {c['quote']}\n\n"
    
    user_message = f"""Question: {question}

{citation_text}

Provide a factual answer based ONLY on the citations above.
Do not add any information not found in the citations.
Do not give advice or recommendations.
Respond in: {language}"""

    try:
        return await call_claude_async(SYNTHESIZER_SYSTEM_PROMPT, user_message)
    except Exception as e:
        print(f"[ERROR] Synthesizer failed: {e}")
        return "An error occurred while generating the answer. Please try again."


# ============================================================
# MAIN FUNCTION
# ============================================================

def witness_smart_query(
    question: str,
    knowledge_path: str,
    language: str = "en",
    regulations: List[str] = None
) -> SmartWitnessResponse:
    """
    Full witness smart pipeline (synchronous).
    
    1. Interpret question (Claude)
    2. Search EVE Knowledge Base (approved only)
    3. Synthesize answer (Claude)
    """
    trace = {}
    
    # Step 1: Interpret
    interpretation = interpret_question(question)
    trace["interpreter"] = MODEL
    
    search_terms = interpretation.get("search_terms", [])
    article_hints = interpretation.get("article_hints", [])
    
    # Use provided regulations or interpreted ones
    regs = regulations or interpretation.get("regulations", ["GDPR", "AI Act", "NIS2"])
    
    # Step 2: Search EVE Knowledge
    citations = search_eve_knowledge(
        search_terms=search_terms,
        regulations=regs,
        knowledge_path=knowledge_path,
        article_hints=article_hints
    )
    
    # Step 3: Synthesize
    answer = synthesize_answer(question, citations, language)
    trace["synthesizer"] = MODEL
    
    # Create hash
    hash_content = json.dumps({"answer": answer, "citations": [c["source_id"] for c in citations]})
    response_hash = hashlib.sha256(hash_content.encode()).hexdigest()[:16]
    
    # Build response
    return SmartWitnessResponse(
        answer=answer,
        citations=[
            SmartWitnessCitation(
                regulation=c["regulation"],
                article=c["article"],
                quote=c["quote"][:200] + "..." if len(c["quote"]) > 200 else c["quote"],
                source_id=c["source_id"]
            )
            for c in citations
        ],
        witness_mode=True,
        llm_trace=trace,
        search_terms=search_terms,
        response_hash=response_hash,
        disclaimer=(
            "EVE provides information based on approved sources only. "
            "This does not constitute legal advice, compliance assessment, or recommendation. "
            "All decisions require human authorization."
        )
    )


async def witness_smart_query_async(
    question: str,
    knowledge_path: str,
    language: str = "en",
    regulations: List[str] = None
) -> SmartWitnessResponse:
    """
    Full witness smart pipeline (asynchronous).
    """
    trace = {}
    
    # Step 1: Interpret
    interpretation = await interpret_question_async(question)
    trace["interpreter"] = MODEL
    
    search_terms = interpretation.get("search_terms", [])
    article_hints = interpretation.get("article_hints", [])
    regs = regulations or interpretation.get("regulations", ["GDPR", "AI Act", "NIS2"])
    
    # Step 2: Search (sync - file I/O)
    citations = search_eve_knowledge(
        search_terms=search_terms,
        regulations=regs,
        knowledge_path=knowledge_path,
        article_hints=article_hints
    )
    
    # Step 3: Synthesize
    answer = await synthesize_answer_async(question, citations, language)
    trace["synthesizer"] = MODEL
    
    # Create hash
    hash_content = json.dumps({"answer": answer, "citations": [c["source_id"] for c in citations]})
    response_hash = hashlib.sha256(hash_content.encode()).hexdigest()[:16]
    
    return SmartWitnessResponse(
        answer=answer,
        citations=[
            SmartWitnessCitation(
                regulation=c["regulation"],
                article=c["article"],
                quote=c["quote"][:200] + "..." if len(c["quote"]) > 200 else c["quote"],
                source_id=c["source_id"]
            )
            for c in citations
        ],
        witness_mode=True,
        llm_trace=trace,
        search_terms=search_terms,
        response_hash=response_hash,
        disclaimer=(
            "EVE provides information based on approved sources only. "
            "This does not constitute legal advice, compliance assessment, or recommendation. "
            "All decisions require human authorization."
        )
    )
