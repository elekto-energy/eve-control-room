"""
EVE Knowledge Pipeline
======================

Implementerar den kompletta kunskapskedjan:

ROLLFÖRDELNING:
- EVE: Sanning & bevis (passiv men absolut)
- LLM: Verktyg & assistenter (aldrig källa)
- Människa: Beslut & ansvar

STEG:
A) Placeholders (Qwen + EVE) - struktur utan innehåll
B) EUR-Lex Fetch (EVE + Claude) - hämta + strukturera
C) Approval (EVE + Människa) - godkänn + seal

Patent-referens: EVE Witness Mode Architecture
"""

import json
import hashlib
import re
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from enum import Enum
import sys


# ============================================================
# PATHS (Cross-platform: Windows & Linux/Pi)
# ============================================================
import platform
import os

if platform.system() == "Windows":
    EVE_BASE = Path("D:/EVE11")
    PROJECT_BASE = EVE_BASE / "Projects/002_EVE_Control_Room/eve"
else:
    # Linux / Pi / server - supports EVE_BASE env override
    EVE_BASE = Path(os.getenv("EVE_BASE", "/home/organiq"))
    PROJECT_BASE = EVE_BASE / "002_EVE_Control_Room/eve"

KNOWLEDGE_PATH = PROJECT_BASE / "knowledge"
CONFIG_PATH = PROJECT_BASE / "config/trusted_sources.json"
PENDING_PATH = KNOWLEDGE_PATH / "pending"
ARCHIVE_PATH = KNOWLEDGE_PATH / "archive"
RAW_PATH = KNOWLEDGE_PATH / "raw"  # Original fetched content


# ============================================================
# STATUS & LEVELS
# ============================================================

class ArticleStatus(Enum):
    PLACEHOLDER = "PLACEHOLDER"      # Structure only, no content
    RAW_FETCHED = "RAW_FETCHED"      # Fetched but not processed
    PENDING_REVIEW = "PENDING_REVIEW" # Processed, awaiting approval
    APPROVED = "APPROVED"             # Human approved
    SEALED = "SEALED"                 # X-Vault sealed
    REJECTED = "REJECTED"             # Human rejected


class KnowledgeLevel(Enum):
    LEVEL_1_LAW = "LEVEL_1_LAW"
    LEVEL_2_GUIDANCE = "LEVEL_2_GUIDANCE"
    LEVEL_3_STANDARDS = "LEVEL_3_STANDARDS"
    LEVEL_4_PRACTICE = "LEVEL_4_PRACTICE"
    LEVEL_5_CONTEXT = "LEVEL_5_CONTEXT"


# ============================================================
# DATA MODELS
# ============================================================

@dataclass
class Paragraph:
    number: str
    text: str
    sub_points: List[Dict] = field(default_factory=list)


@dataclass
class AIMetadata:
    """Metadata for any AI-derived content - ALWAYS marked clearly."""
    generated_by: str  # "claude", "qwen", "code_factory"
    generated_date: str
    status: str = "NON_AUTHORITATIVE"
    visible_label: str = "AI-generated - not legally binding"
    prompt_hash: Optional[str] = None  # Hash of prompt used


@dataclass
class EVEMetadata:
    """EVE system metadata - source of truth."""
    created_date: str
    created_by: str  # "article_generator", "eurlex_fetcher", etc.
    status: ArticleStatus
    knowledge_level: KnowledgeLevel
    schema_version: str = "2.0.0"
    
    # Approval chain
    approved: bool = False
    approved_by: Optional[str] = None
    approved_date: Optional[str] = None
    approval_signature: Optional[str] = None
    
    # Seal
    sealed: bool = False
    x_vault_hash: Optional[str] = None
    sealed_date: Optional[str] = None


@dataclass
class Article:
    """Complete article with full provenance."""
    # Identity
    id: str
    regulation: str
    regulation_full: str
    article_number: str
    title: str
    
    # Content (from EUR-Lex)
    content: str
    paragraphs: List[Paragraph]
    
    # Source (AUTHORITATIVE)
    source_url: str
    source_celex: str
    source_eli: str
    source_language: str
    source_fetched_date: Optional[str]
    
    # Hashes (EVE computes these)
    content_hash: str
    source_hash: Optional[str]
    
    # EVE metadata (system truth)
    eve_metadata: EVEMetadata
    
    # AI-derived content (clearly marked)
    ai_summary: Optional[AIMetadata] = None
    ai_cross_references: Optional[AIMetadata] = None
    
    # Optional
    cross_references: List[str] = field(default_factory=list)
    recitals: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    effective_date: Optional[str] = None
    version: str = "1.0.0"
    
    def compute_hash(self) -> str:
        """Compute SHA-256 of authoritative content only."""
        # Only hash the legal content, not AI-derived parts
        authoritative = {
            "content": self.content,
            "paragraphs": [asdict(p) for p in self.paragraphs],
            "source_celex": self.source_celex,
            "article_number": self.article_number
        }
        content_str = json.dumps(authoritative, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(content_str.encode()).hexdigest()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        d = asdict(self)
        d['eve_metadata']['status'] = self.eve_metadata.status.value
        d['eve_metadata']['knowledge_level'] = self.eve_metadata.knowledge_level.value
        return d
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


# ============================================================
# REGULATION METADATA
# ============================================================

def load_config() -> Dict:
    """Load trusted sources configuration."""
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    raise FileNotFoundError(f"Config not found: {CONFIG_PATH}")


def get_regulation_meta(regulation: str) -> Dict:
    """Get metadata for a regulation from config."""
    config = load_config()
    return config["sources"]["eur_lex"]["regulations"].get(regulation, {})


# ============================================================
# STEG A: PLACEHOLDER GENERATION (Qwen + EVE)
# ============================================================

class PlaceholderGenerator:
    """
    Generates placeholder articles - structure without content.
    
    Role: Qwen (deterministic, batch)
    EVE: Validates schema, sets status=PLACEHOLDER
    """
    
    def __init__(self):
        self.config = load_config()
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        KNOWLEDGE_PATH.mkdir(parents=True, exist_ok=True)
        PENDING_PATH.mkdir(parents=True, exist_ok=True)
    
    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()
    
    def generate_placeholder(self, regulation: str, article_num: int, title: str = None) -> Article:
        """Generate a single placeholder article."""
        
        meta = get_regulation_meta(regulation)
        if not meta:
            raise ValueError(f"Unknown regulation: {regulation}")
        
        if title is None:
            title = f"Article {article_num}"
        
        timestamp = self._timestamp()
        
        # Placeholder content - clearly marked
        placeholder_text = (
            f"[PLACEHOLDER: {meta['short_name']} Article {article_num}]\n\n"
            f"This article requires content from EUR-Lex.\n"
            f"Source: {meta['celex']}\n"
            f"Status: Awaiting fetch"
        )
        
        article = Article(
            id=f"{regulation}_article_{article_num}",
            regulation=meta["short_name"],
            regulation_full=meta["full_name"],
            article_number=str(article_num),
            title=title,
            content=placeholder_text,
            paragraphs=[],
            source_url=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{meta['celex']}",
            source_celex=meta["celex"],
            source_eli=meta["eli"],
            source_language="en",
            source_fetched_date=None,
            content_hash="",  # Will be computed
            source_hash=None,
            eve_metadata=EVEMetadata(
                created_date=timestamp,
                created_by="placeholder_generator",
                status=ArticleStatus.PLACEHOLDER,
                knowledge_level=KnowledgeLevel.LEVEL_1_LAW
            ),
            effective_date=meta.get("effective_date"),
            version="0.1.0"
        )
        
        # EVE computes hash
        article.content_hash = article.compute_hash()
        
        return article
    
    def generate_batch(self, regulation: str, article_range: str = None) -> List[Path]:
        """Generate placeholder articles for a regulation."""
        
        meta = get_regulation_meta(regulation)
        if not meta:
            raise ValueError(f"Unknown regulation: {regulation}")
        
        total = meta["articles"]
        
        # Parse range
        if article_range is None:
            articles = list(range(1, total + 1))
        elif "-" in article_range:
            start, end = map(int, article_range.split("-"))
            articles = list(range(start, min(end + 1, total + 1)))
        elif "," in article_range:
            articles = [int(x.strip()) for x in article_range.split(",")]
        else:
            articles = [int(article_range)]
        
        # Output directory
        output_dir = KNOWLEDGE_PATH / "documents/eu" / regulation / "articles"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        created = []
        skipped = 0
        
        for num in articles:
            path = output_dir / f"article_{num}.json"
            
            # Don't overwrite approved content
            if path.exists():
                existing = json.loads(path.read_text(encoding='utf-8'))
                status = existing.get("eve_metadata", {}).get("status", "")
                if status in ["APPROVED", "SEALED", "PENDING_REVIEW"]:
                    skipped += 1
                    continue
            
            article = self.generate_placeholder(regulation, num)
            path.write_text(article.to_json(), encoding='utf-8')
            created.append(path)
        
        print(f"✅ Created {len(created)} placeholders for {regulation.upper()}")
        if skipped:
            print(f"⏭️  Skipped {skipped} (already have content)")
        
        return created
    
    def generate_index(self, regulation: str) -> Path:
        """Generate index file for a regulation."""
        
        meta = get_regulation_meta(regulation)
        articles_dir = KNOWLEDGE_PATH / "documents/eu" / regulation / "articles"
        
        articles = []
        status_counts = {s.value: 0 for s in ArticleStatus}
        
        for f in sorted(articles_dir.glob("article_*.json")):
            data = json.loads(f.read_text(encoding='utf-8'))
            status = data.get("eve_metadata", {}).get("status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
            
            articles.append({
                "article_number": data["article_number"],
                "title": data["title"],
                "file": f.name,
                "status": status,
                "approved": data.get("eve_metadata", {}).get("approved", False)
            })
        
        index = {
            "regulation": meta["short_name"],
            "regulation_full": meta["full_name"],
            "celex": meta["celex"],
            "total_articles": meta["articles"],
            "indexed_count": len(articles),
            "coverage_percent": round((len(articles) / meta["articles"]) * 100, 1),
            "status_counts": status_counts,
            "updated": self._timestamp(),
            "articles": articles
        }
        
        index_path = KNOWLEDGE_PATH / "documents/eu" / regulation / "index.json"
        index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding='utf-8')
        
        return index_path


# ============================================================
# STEG B: EUR-LEX FETCH (EVE + Claude)
# ============================================================

class EURLexFetcher:
    """
    Fetches legal text from EUR-Lex.
    
    Role: EVE fetches, Claude structures (but never changes legal text)
    """
    
    def __init__(self):
        self.config = load_config()
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        RAW_PATH.mkdir(parents=True, exist_ok=True)
        PENDING_PATH.mkdir(parents=True, exist_ok=True)
    
    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()
    
    def _compute_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()
    
    def fetch_html(self, regulation: str, language: str = "EN") -> Tuple[str, str]:
        """
        Fetch HTML from EUR-Lex.
        Returns (html_content, source_hash)
        """
        meta = get_regulation_meta(regulation)
        if not meta:
            raise ValueError(f"Unknown regulation: {regulation}")
        
        url = f"https://eur-lex.europa.eu/legal-content/{language}/TXT/HTML/?uri=CELEX:{meta['celex']}"
        
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'EVE-KnowledgeFetcher/1.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                html = response.read().decode('utf-8')
                
            # Save raw content
            raw_file = RAW_PATH / f"{regulation}_{language}_{self._timestamp()[:10]}.html"
            raw_file.write_text(html, encoding='utf-8')
            
            return html, self._compute_hash(html)
            
        except Exception as e:
            raise RuntimeError(f"Failed to fetch {regulation}: {e}")
    
    def extract_article_text(self, html: str, article_num: int) -> Optional[str]:
        """
        Extract article text from EUR-Lex HTML.
        
        This is deterministic extraction - no interpretation.
        """
        # EUR-Lex uses specific HTML structure
        # Look for Article N pattern
        patterns = [
            rf'Article\s+{article_num}\s*</p>(.*?)(?=Article\s+\d+\s*</p>|</body>)',
            rf'<p[^>]*>Article\s+{article_num}[^<]*</p>(.*?)(?=<p[^>]*>Article\s+\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if match:
                raw_text = match.group(1)
                # Clean HTML tags
                text = re.sub(r'<[^>]+>', ' ', raw_text)
                text = re.sub(r'\s+', ' ', text).strip()
                return text
        
        return None
    
    def create_pending_article(self, regulation: str, article_num: int, 
                                content: str, source_hash: str) -> Path:
        """
        Create article in pending state.
        
        EVE: Sets status=PENDING_REVIEW
        Human: Must approve before it becomes active
        """
        meta = get_regulation_meta(regulation)
        timestamp = self._timestamp()
        
        article = Article(
            id=f"{regulation}_article_{article_num}",
            regulation=meta["short_name"],
            regulation_full=meta["full_name"],
            article_number=str(article_num),
            title=f"Article {article_num}",  # Will be enhanced by Claude
            content=content,
            paragraphs=[],  # Will be structured by Claude
            source_url=f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{meta['celex']}",
            source_celex=meta["celex"],
            source_eli=meta["eli"],
            source_language="en",
            source_fetched_date=timestamp,
            content_hash="",
            source_hash=source_hash,
            eve_metadata=EVEMetadata(
                created_date=timestamp,
                created_by="eurlex_fetcher",
                status=ArticleStatus.PENDING_REVIEW,
                knowledge_level=KnowledgeLevel.LEVEL_1_LAW
            ),
            effective_date=meta.get("effective_date"),
            version="1.0.0"
        )
        
        article.content_hash = article.compute_hash()
        
        # Save to pending
        pending_dir = PENDING_PATH / regulation
        pending_dir.mkdir(parents=True, exist_ok=True)
        
        path = pending_dir / f"article_{article_num}.json"
        path.write_text(article.to_json(), encoding='utf-8')
        
        return path


# ============================================================
# STEG C: APPROVAL (EVE + Människa)
# ============================================================

class ApprovalManager:
    """
    Manages human approval workflow.
    
    Role: EVE presents, blocks without approval, seals on approval
    Human: Reviews, decides, signs
    """
    
    def __init__(self):
        self._ensure_dirs()
    
    def _ensure_dirs(self):
        PENDING_PATH.mkdir(parents=True, exist_ok=True)
        ARCHIVE_PATH.mkdir(parents=True, exist_ok=True)
    
    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()
    
    def _compute_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()
    
    def list_pending(self) -> List[Dict]:
        """List all articles awaiting approval."""
        pending = []
        
        for reg_dir in PENDING_PATH.iterdir():
            if reg_dir.is_dir():
                for f in reg_dir.glob("article_*.json"):
                    data = json.loads(f.read_text(encoding='utf-8'))
                    pending.append({
                        "file": str(f),
                        "regulation": data.get("regulation"),
                        "article": data.get("article_number"),
                        "title": data.get("title"),
                        "status": data.get("eve_metadata", {}).get("status"),
                        "fetched": data.get("source_fetched_date", "")[:10]
                    })
        
        return pending
    
    def approve(self, pending_file: str, approved_by: str, observation: str = None) -> Dict:
        """
        Approve an article, optionally with observation.
        
        EVE: Seals with X-Vault, moves to active knowledge
        Human: Takes responsibility via signature
        Observation: Documents discrepancies while still approving
        """
        path = Path(pending_file)
        if not path.exists():
            raise FileNotFoundError(f"Not found: {pending_file}")
        
        data = json.loads(path.read_text(encoding='utf-8'))
        timestamp = self._timestamp()
        
        # Update EVE metadata
        data["eve_metadata"]["approved"] = True
        data["eve_metadata"]["approved_by"] = approved_by
        data["eve_metadata"]["approved_date"] = timestamp
        
        # Set status based on observation
        if observation:
            data["eve_metadata"]["status"] = "APPROVED_WITH_OBSERVATION"
            data["eve_metadata"]["observation"] = observation
        else:
            data["eve_metadata"]["status"] = ArticleStatus.APPROVED.value
        
        # Compute approval signature
        sig_content = f"{data['content_hash']}:{approved_by}:{timestamp}"
        data["eve_metadata"]["approval_signature"] = self._compute_hash(sig_content)
        
        # Move to active knowledge
        reg = data.get("regulation", "unknown").lower().replace(" ", "_")
        target_dir = KNOWLEDGE_PATH / "documents/eu" / reg / "articles"
        target_dir.mkdir(parents=True, exist_ok=True)
        
        target_path = target_dir / f"article_{data['article_number']}.json"
        
        # Archive existing if present
        if target_path.exists():
            archive_dir = ARCHIVE_PATH / reg
            archive_dir.mkdir(parents=True, exist_ok=True)
            # Use timestamp with time to avoid collisions
            archive_name = f"article_{data['article_number']}_{timestamp[:19].replace(':', '-')}.json"
            archive_path = archive_dir / archive_name
            # If still exists (unlikely), add counter
            counter = 1
            while archive_path.exists():
                archive_name = f"article_{data['article_number']}_{timestamp[:10]}_{counter}.json"
                archive_path = archive_dir / archive_name
                counter += 1
            target_path.rename(archive_path)
        
        # Write approved version
        target_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        
        # Remove from pending
        path.unlink()
        
        return {
            "action": "APPROVED",
            "article": f"{data['regulation']} Article {data['article_number']}",
            "approved_by": approved_by,
            "timestamp": timestamp,
            "content_hash": data["content_hash"],
            "approval_signature": data["eve_metadata"]["approval_signature"],
            "target_path": str(target_path)
        }
    
    def reject(self, pending_file: str, rejected_by: str, reason: str) -> Dict:
        """Reject an article with reason."""
        path = Path(pending_file)
        if not path.exists():
            raise FileNotFoundError(f"Not found: {pending_file}")
        
        data = json.loads(path.read_text(encoding='utf-8'))
        timestamp = self._timestamp()
        
        # Update metadata
        data["eve_metadata"]["status"] = ArticleStatus.REJECTED.value
        data["eve_metadata"]["rejected_by"] = rejected_by
        data["eve_metadata"]["rejected_date"] = timestamp
        data["eve_metadata"]["rejection_reason"] = reason
        
        # Move to rejected archive
        reg = data.get("regulation", "unknown").lower().replace(" ", "_")
        rejected_dir = ARCHIVE_PATH / "rejected" / reg
        rejected_dir.mkdir(parents=True, exist_ok=True)
        
        rejected_path = rejected_dir / f"article_{data['article_number']}_{timestamp[:10]}.json"
        rejected_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        
        # Remove from pending
        path.unlink()
        
        return {
            "action": "REJECTED",
            "article": f"{data['regulation']} Article {data['article_number']}",
            "rejected_by": rejected_by,
            "reason": reason,
            "timestamp": timestamp
        }


# ============================================================
# COVERAGE REPORT
# ============================================================

def print_coverage_report():
    """Print knowledge base coverage."""
    config = load_config()
    
    print("\n" + "=" * 70)
    print("📊 EVE KNOWLEDGE BASE COVERAGE REPORT")
    print("=" * 70)
    
    total_articles = 0
    total_existing = 0
    total_approved = 0
    total_pending = 0
    
    for reg, meta in config["sources"]["eur_lex"]["regulations"].items():
        articles_dir = KNOWLEDGE_PATH / "documents/eu" / reg / "articles"
        pending_dir = PENDING_PATH / reg
        
        count = len(list(articles_dir.glob("article_*.json"))) if articles_dir.exists() else 0
        pending = len(list(pending_dir.glob("article_*.json"))) if pending_dir.exists() else 0
        approved = 0
        placeholder = 0
        
        if articles_dir.exists():
            for f in articles_dir.glob("article_*.json"):
                data = json.loads(f.read_text(encoding='utf-8'))
                status = data.get("eve_metadata", {}).get("status", "")
                if status == "APPROVED":
                    approved += 1
                elif status == "PLACEHOLDER":
                    placeholder += 1
        
        coverage = (count / meta["articles"]) * 100 if meta["articles"] > 0 else 0
        bar = "█" * int(coverage / 5) + "░" * (20 - int(coverage / 5))
        
        print(f"\n{meta['short_name']:12} {bar} {coverage:5.1f}%")
        print(f"             Total: {count:3}/{meta['articles']} | Approved: {approved} | Placeholder: {placeholder} | Pending: {pending}")
        
        total_articles += meta["articles"]
        total_existing += count
        total_approved += approved
        total_pending += pending
    
    print("\n" + "-" * 70)
    overall = (total_existing / total_articles) * 100 if total_articles > 0 else 0
    print(f"TOTAL:       {total_existing}/{total_articles} articles ({overall:.1f}%)")
    print(f"             Approved: {total_approved} | Pending: {total_pending}")
    print("=" * 70 + "\n")


# ============================================================
# CLI
# ============================================================

def main():
    if len(sys.argv) < 2:
        print("""
EVE Knowledge Pipeline
======================

Commands:
  coverage                          - Show coverage report
  generate <reg> [range]            - Generate placeholders
  index <reg>                       - Generate index
  pending                           - List pending approvals
  approve <file> <name>             - Approve article
  reject <file> <name> <reason>     - Reject article

Regulations: gdpr, ai_act, dora, nis2, cra

Examples:
  python knowledge_pipeline.py coverage
  python knowledge_pipeline.py generate gdpr
  python knowledge_pipeline.py generate ai_act 1-50
  python knowledge_pipeline.py pending
  python knowledge_pipeline.py approve /path/to/file.json joakim
        """)
        return
    
    cmd = sys.argv[1]
    
    if cmd == "coverage":
        print_coverage_report()
    
    elif cmd == "generate" and len(sys.argv) > 2:
        reg = sys.argv[2]
        range_arg = sys.argv[3] if len(sys.argv) > 3 else None
        
        gen = PlaceholderGenerator()
        gen.generate_batch(reg, range_arg)
        gen.generate_index(reg)
    
    elif cmd == "index" and len(sys.argv) > 2:
        reg = sys.argv[2]
        gen = PlaceholderGenerator()
        path = gen.generate_index(reg)
        print(f"📋 Index: {path}")
    
    elif cmd == "pending":
        mgr = ApprovalManager()
        pending = mgr.list_pending()
        
        if not pending:
            print("✅ No articles pending approval")
        else:
            print(f"\n⏳ {len(pending)} articles pending:\n")
            for p in pending:
                print(f"  {p['regulation']:10} Art. {p['article']:3} - {p['title'][:40]}")
    
    elif cmd == "approve" and len(sys.argv) > 3:
        mgr = ApprovalManager()
        result = mgr.approve(sys.argv[2], sys.argv[3])
        print(f"✅ {result['action']}: {result['article']}")
        print(f"   Signature: {result['approval_signature'][:16]}...")
    
    elif cmd == "reject" and len(sys.argv) > 4:
        mgr = ApprovalManager()
        result = mgr.reject(sys.argv[2], sys.argv[3], sys.argv[4])
        print(f"❌ {result['action']}: {result['article']}")
        print(f"   Reason: {result['reason']}")
    
    else:
        print("Unknown command. Run without arguments for help.")


if __name__ == "__main__":
    main()
