"""
EVE Approval Helper
===================

Simplified approval commands for knowledge pipeline.
"""

import os
import sys
from pathlib import Path

# Paths
PENDING_PATH = Path(os.environ.get(
    "EVE_PENDING_PATH",
    str(Path(__file__).parent.parent / "knowledge" / "pending")
))

# Import knowledge pipeline
sys.path.insert(0, str(Path(__file__).parent))
from knowledge_pipeline import ApprovalManager, print_coverage_report


def main():
    if len(sys.argv) < 2:
        print("""
EVE Approval Helper
===================

Commands:
  pending                       - List pending articles
  approve <reg> <article> <n> - Approve single article
  approve-all <reg> <n>       - Approve all for regulation
  coverage                      - Show coverage report

Examples:
  python approve.py pending
  python approve.py approve gdpr 35 joakim
  python approve.py approve ai_act 5 joakim
  python approve.py approve-all gdpr joakim
        """)
        return
    
    cmd = sys.argv[1]
    mgr = ApprovalManager()
    
    if cmd == "pending":
        pending = mgr.list_pending()
        if not pending:
            print("✅ No articles pending approval")
        else:
            print(f"\n⏳ {len(pending)} articles pending:\n")
            for p in pending:
                print(f"  {p['regulation']:10} Art. {p['article']:3} - {p['title'][:40]}")
            print(f"\nTo approve: python approve.py approve <reg> <article> <your_name>")
    
    elif cmd == "approve" and len(sys.argv) >= 4:
        reg = sys.argv[2].lower()
        art_num = sys.argv[3]
        approved_by = sys.argv[4] if len(sys.argv) > 4 else "system"
        
        # Find pending file
        pending_file = PENDING_PATH / reg / f"article_{art_num}.json"
        
        if not pending_file.exists():
            print(f"❌ Not found: {pending_file}")
            print(f"\nAvailable pending directories:")
            for d in PENDING_PATH.iterdir():
                if d.is_dir():
                    files = list(d.glob("article_*.json"))
                    print(f"  {d.name}: {len(files)} articles")
            return
        
        result = mgr.approve(str(pending_file), approved_by)
        print(f"✅ {result['action']}: {result['article']}")
        print(f"   Approved by: {result['approved_by']}")
        print(f"   Signature: {result['approval_signature'][:16]}...")
        print(f"   Saved to: {result['target_path']}")
    
    elif cmd == "approve-all" and len(sys.argv) >= 3:
        reg = sys.argv[2].lower()
        approved_by = sys.argv[3] if len(sys.argv) > 3 else "system"
        
        pending_dir = PENDING_PATH / reg
        
        if not pending_dir.exists():
            print(f"❌ No pending directory for {reg}")
            print(f"\nAvailable: {[d.name for d in PENDING_PATH.iterdir() if d.is_dir()]}")
            return
        
        files = list(pending_dir.glob("article_*.json"))
        if not files:
            print(f"✅ No pending articles for {reg}")
            return
        
        print(f"\n🔄 Approving {len(files)} articles for {reg.upper()}...\n")
        
        for f in sorted(files):
            try:
                result = mgr.approve(str(f), approved_by)
                print(f"  ✅ {result['article']} - {result['approval_signature'][:8]}...")
            except Exception as e:
                print(f"  ❌ {f.name}: {e}")
        
        print(f"\n✅ Done!")
    
    elif cmd == "coverage":
        print_coverage_report()
    
    else:
        print("Unknown command. Run without arguments for help.")


if __name__ == "__main__":
    main()
