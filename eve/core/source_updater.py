"""
EVE Source Updater Engine
=========================

Automatisk hämtning av juridiskt material från betrodda källor.
Följer Masterplan Flöde A: Publish (Compliedocs -> Knowledge)

PRINCIPER:
- Endast AUTHORITATIVE källor (EUR-Lex, Riksdagen, ISO)
- ALLTID human approval innan publicering
- Versionering av allt
- X-Vault seal på godkänt material

Patent-referens: EVE Witness Mode Architecture
"""

import json
import hashlib
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET


# ============================================================
# CONFIGURATION
# ============================================================

BASE_PATH = Path(__file__).parent.parent
CONFIG_PATH = BASE_PATH / "config" / "trusted_sources.json"
KNOWLEDGE_PATH = BASE_PATH / "knowledge" / "documents"
PENDING_PATH = BASE_PATH / "knowledge" / "pending"
ARCHIVE_PATH = BASE_PATH / "knowledge" / "archive"


class TrustLevel(Enum):
    AUTHORITATIVE = "AUTHORITATIVE"  # EUR-Lex, ISO, Government
    VERIFIED = "VERIFIED"            # Reviewed secondary sources
    UNVERIFIED = "UNVERIFIED"        # Not allowed


class UpdateStatus(Enum):
    NEW = "NEW"                      # Article doesn't exist
    UPDATED = "UPDATED"              # Content changed
    UNCHANGED = "UNCHANGED"          # No changes
    ERROR = "ERROR"                  # Fetch failed
    PENDING_APPROVAL = "PENDING_APPROVAL"  # Awaiting human review


@dataclass
class Article:
    """Knowledge article with full provenance."""
    id: str
    regulation: str
    article_number: str
    title: str
    content: str
    paragraphs: List[Dict]
    source_url: str
    source_celex: str
    fetched_date: str
    version: str
    source_hash: str
    content_hash: str
    approved_by: Optional[str] = None
    approved_date: Optional[str] = None
    x_vault_hash: Optional[str] = None
    cross_references: List[str] = None
    effective_date: Optional[str] = None
    language: str = "en"
    
    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)
    
    @classmethod
    def from_json(cls, data: dict) -> 'Article':
        return cls(**data)


@dataclass
class UpdateResult:
    """Result of an update operation."""
    regulation: str
    article_number: str
    status: UpdateStatus
    message: str
    diff: Optional[str] = None
    new_hash: Optional[str] = None
    previous_hash: Optional[str] = None


# ============================================================
# SOURCE UPDATER ENGINE
# ============================================================

class SourceUpdater:
    """
    Hämtar och uppdaterar juridiskt material från betrodda källor.
    
    Flöde:
    1. Läs trusted_sources.json
    2. Fetch från källa (EUR-Lex API etc)
    3. Parse och strukturera
    4. Jämför med existerande version
    5. Om ändrad → Spara till pending/
    6. Human approval → Flytta till documents/ + X-Vault seal
    """
    
    def __init__(self):
        self.config = self._load_config()
        self._ensure_directories()
    
    def _load_config(self) -> dict:
        """Load trusted sources configuration."""
        if CONFIG_PATH.exists():
            return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
        raise FileNotFoundError(f"Config not found: {CONFIG_PATH}")
    
    def _ensure_directories(self):
        """Create necessary directories."""
        KNOWLEDGE_PATH.mkdir(parents=True, exist_ok=True)
        PENDING_PATH.mkdir(parents=True, exist_ok=True)
        ARCHIVE_PATH.mkdir(parents=True, exist_ok=True)
    
    def _compute_hash(self, content: str) -> str:
        """SHA-256 hash of content."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    def _get_timestamp(self) -> str:
        """ISO timestamp."""
        return datetime.now(timezone.utc).isoformat()
    
    # ============================================================
    # EUR-LEX FETCHER
    # ============================================================
    
    def fetch_eurlex_article(self, regulation: str, article_num: int, language: str = "EN") -> Optional[Article]:
        """
        Fetch a single article from EUR-Lex.
        
        EUR-Lex REST API: https://eur-lex.europa.eu/eurlex-ws/
        """
        reg_config = self.config["sources"]["eur_lex"]["regulations"].get(regulation)
        if not reg_config:
            raise ValueError(f"Unknown regulation: {regulation}")
        
        celex = reg_config["celex"]
        
        # EUR-Lex HTML URL (for scraping - API requires authentication)
        html_url = f"https://eur-lex.europa.eu/legal-content/{language}/TXT/HTML/?uri=CELEX:{celex}"
        
        try:
            # Note: In production, use proper EUR-Lex API with authentication
            # This is a simplified version that would need to be enhanced
            
            article = Article(
                id=f"{regulation}_article_{article_num}",
                regulation=regulation.upper(),
                article_number=str(article_num),
                title=f"Article {article_num}",  # Would be parsed from source
                content="",  # Would be fetched
                paragraphs=[],
                source_url=html_url,
                source_celex=celex,
                fetched_date=self._get_timestamp(),
                version="1.0.0",
                source_hash="",
                content_hash="",
                language=language.lower()
            )
            
            return article
            
        except Exception as e:
            print(f"Error fetching {regulation} Article {article_num}: {e}")
            return None
    
    # ============================================================
    # BATCH OPERATIONS
    # ============================================================
    
    def fetch_regulation(self, regulation: str, articles: List[int] = None) -> List[UpdateResult]:
        """
        Fetch all articles for a regulation.
        
        Args:
            regulation: e.g., 'gdpr', 'ai_act', 'dora'
            articles: Specific articles to fetch, or None for all
        """
        reg_config = self.config["sources"]["eur_lex"]["regulations"].get(regulation)
        if not reg_config:
            raise ValueError(f"Unknown regulation: {regulation}")
        
        total_articles = reg_config["articles"]
        articles_to_fetch = articles or list(range(1, total_articles + 1))
        
        results = []
        for art_num in articles_to_fetch:
            result = self._fetch_and_compare(regulation, art_num)
            results.append(result)
        
        return results
    
    def _fetch_and_compare(self, regulation: str, article_num: int) -> UpdateResult:
        """Fetch article and compare with existing version."""
        
        # Check existing
        existing_path = self._get_article_path(regulation, article_num)
        existing = None
        if existing_path.exists():
            existing = json.loads(existing_path.read_text(encoding='utf-8'))
        
        # Fetch new
        new_article = self.fetch_eurlex_article(regulation, article_num)
        if not new_article:
            return UpdateResult(
                regulation=regulation,
                article_number=str(article_num),
                status=UpdateStatus.ERROR,
                message="Failed to fetch from source"
            )
        
        # Compare
        if not existing:
            return UpdateResult(
                regulation=regulation,
                article_number=str(article_num),
                status=UpdateStatus.NEW,
                message="New article",
                new_hash=new_article.content_hash
            )
        
        if existing.get('content_hash') == new_article.content_hash:
            return UpdateResult(
                regulation=regulation,
                article_number=str(article_num),
                status=UpdateStatus.UNCHANGED,
                message="No changes detected"
            )
        
        # Changed - save to pending
        self._save_to_pending(new_article)
        
        return UpdateResult(
            regulation=regulation,
            article_number=str(article_num),
            status=UpdateStatus.UPDATED,
            message="Content changed - pending approval",
            new_hash=new_article.content_hash,
            previous_hash=existing.get('content_hash')
        )
    
    def _get_article_path(self, regulation: str, article_num: int) -> Path:
        """Get path for an article."""
        return KNOWLEDGE_PATH / "eu" / regulation / "articles" / f"article_{article_num}.json"
    
    def _save_to_pending(self, article: Article):
        """Save article to pending directory for approval."""
        pending_dir = PENDING_PATH / article.regulation.lower()
        pending_dir.mkdir(parents=True, exist_ok=True)
        
        path = pending_dir / f"article_{article.article_number}_{self._get_timestamp()[:10]}.json"
        path.write_text(article.to_json(), encoding='utf-8')
    
    # ============================================================
    # APPROVAL WORKFLOW
    # ============================================================
    
    def list_pending(self) -> List[Dict]:
        """List all articles pending approval."""
        pending = []
        
        for reg_dir in PENDING_PATH.iterdir():
            if reg_dir.is_dir():
                for article_file in reg_dir.glob("*.json"):
                    data = json.loads(article_file.read_text(encoding='utf-8'))
                    pending.append({
                        "file": str(article_file),
                        "regulation": data.get("regulation"),
                        "article": data.get("article_number"),
                        "fetched": data.get("fetched_date")
                    })
        
        return pending
    
    def approve_article(self, pending_file: str, approved_by: str) -> Dict:
        """
        Approve a pending article and publish to knowledge base.
        
        This:
        1. Adds approval metadata
        2. Computes final hashes
        3. Moves to knowledge/documents/
        4. Archives previous version
        5. Returns X-Vault evidence
        """
        pending_path = Path(pending_file)
        if not pending_path.exists():
            raise FileNotFoundError(f"Pending file not found: {pending_file}")
        
        # Load article
        data = json.loads(pending_path.read_text(encoding='utf-8'))
        
        # Add approval
        timestamp = self._get_timestamp()
        data["approved_by"] = approved_by
        data["approved_date"] = timestamp
        data["content_hash"] = self._compute_hash(data.get("content", ""))
        
        # Determine target path
        target_dir = KNOWLEDGE_PATH / "eu" / data["regulation"].lower() / "articles"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / f"article_{data['article_number']}.json"
        
        # Archive existing if present
        if target_path.exists():
            self._archive_article(target_path)
        
        # Write approved version
        target_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        
        # Remove from pending
        pending_path.unlink()
        
        # Create evidence
        evidence = {
            "type": "ARTICLE_APPROVED",
            "regulation": data["regulation"],
            "article": data["article_number"],
            "approved_by": approved_by,
            "approved_date": timestamp,
            "content_hash": data["content_hash"],
            "source_url": data.get("source_url"),
            "target_path": str(target_path)
        }
        
        return evidence
    
    def _archive_article(self, article_path: Path):
        """Archive previous version of article."""
        data = json.loads(article_path.read_text(encoding='utf-8'))
        
        archive_dir = ARCHIVE_PATH / data["regulation"].lower()
        archive_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = self._get_timestamp()[:10]
        archive_path = archive_dir / f"article_{data['article_number']}_{timestamp}.json"
        
        article_path.rename(archive_path)
    
    def reject_article(self, pending_file: str, rejected_by: str, reason: str) -> Dict:
        """Reject a pending article."""
        pending_path = Path(pending_file)
        if not pending_path.exists():
            raise FileNotFoundError(f"Pending file not found: {pending_file}")
        
        data = json.loads(pending_path.read_text(encoding='utf-8'))
        
        # Move to rejected archive
        rejected_dir = ARCHIVE_PATH / "rejected" / data["regulation"].lower()
        rejected_dir.mkdir(parents=True, exist_ok=True)
        
        data["rejected_by"] = rejected_by
        data["rejected_date"] = self._get_timestamp()
        data["rejection_reason"] = reason
        
        rejected_path = rejected_dir / f"article_{data['article_number']}_{self._get_timestamp()[:10]}.json"
        rejected_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        
        pending_path.unlink()
        
        return {
            "type": "ARTICLE_REJECTED",
            "regulation": data["regulation"],
            "article": data["article_number"],
            "rejected_by": rejected_by,
            "reason": reason
        }
    
    # ============================================================
    # STATUS & REPORTING
    # ============================================================
    
    def get_coverage_report(self) -> Dict:
        """Get coverage report for all regulations."""
        report = {}
        
        for reg_key, reg_config in self.config["sources"]["eur_lex"]["regulations"].items():
            total = reg_config["articles"]
            
            # Count existing
            reg_path = KNOWLEDGE_PATH / "eu" / reg_key / "articles"
            existing = len(list(reg_path.glob("article_*.json"))) if reg_path.exists() else 0
            
            # Count pending
            pending_path = PENDING_PATH / reg_key
            pending = len(list(pending_path.glob("*.json"))) if pending_path.exists() else 0
            
            report[reg_key] = {
                "name": reg_config["short_name"],
                "total_articles": total,
                "existing": existing,
                "pending": pending,
                "coverage_percent": round((existing / total) * 100, 1) if total > 0 else 0,
                "missing": total - existing - pending
            }
        
        return report


# ============================================================
# CLI INTERFACE
# ============================================================

def main():
    """CLI for source updater."""
    import sys
    
    updater = SourceUpdater()
    
    if len(sys.argv) < 2:
        print("EVE Source Updater")
        print("=" * 40)
        print("\nUsage:")
        print("  python source_updater.py coverage     - Show coverage report")
        print("  python source_updater.py pending      - List pending approvals")
        print("  python source_updater.py fetch <reg>  - Fetch regulation (gdpr/ai_act/dora)")
        print("  python source_updater.py approve <file> <name> - Approve pending article")
        return
    
    cmd = sys.argv[1]
    
    if cmd == "coverage":
        report = updater.get_coverage_report()
        print("\n📊 Knowledge Base Coverage Report")
        print("=" * 50)
        for reg, data in report.items():
            bar = "█" * int(data["coverage_percent"] / 5) + "░" * (20 - int(data["coverage_percent"] / 5))
            print(f"\n{data['name']:20} {bar} {data['coverage_percent']:5.1f}%")
            print(f"  Existing: {data['existing']}/{data['total_articles']} | Pending: {data['pending']} | Missing: {data['missing']}")
    
    elif cmd == "pending":
        pending = updater.list_pending()
        if not pending:
            print("✅ No articles pending approval")
        else:
            print(f"\n⏳ {len(pending)} articles pending approval:")
            for p in pending:
                print(f"  - {p['regulation']} Art. {p['article']} ({p['fetched'][:10]})")
    
    elif cmd == "fetch" and len(sys.argv) > 2:
        reg = sys.argv[2]
        print(f"Fetching {reg}...")
        # Note: Would need actual EUR-Lex API implementation
        print("⚠️  EUR-Lex API integration not yet implemented")
        print("    Use manual article creation for now")
    
    elif cmd == "approve" and len(sys.argv) > 3:
        file_path = sys.argv[2]
        approved_by = sys.argv[3]
        evidence = updater.approve_article(file_path, approved_by)
        print(f"✅ Approved: {evidence['regulation']} Article {evidence['article']}")
        print(f"   Hash: {evidence['content_hash'][:16]}...")
    
    else:
        print("Unknown command. Run without arguments for help.")


if __name__ == "__main__":
    main()
