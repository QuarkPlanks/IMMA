"""
build_knowledge_base.py
────────────────────────
One-time script to populate the RAG vector store.

Steps:
  1. Search Semantic Scholar + arXiv for injection molding papers
  2. Download open-access PDFs (via Unpaywall)
  3. Embed and store in ChromaDB
  4. Also index raw_text from all existing grade JSON files
  5. Index the PolyNC paper (articles/) if present

Usage:
  python build_knowledge_base.py
  python build_knowledge_base.py --skip-papers     # only index TDS data
  python build_knowledge_base.py --add-pdf path.pdf
"""

import sys
import argparse
import logging
import json
import time
from pathlib import Path

ROOT_DIR = Path(__file__).parent
sys.path.insert(0, str(ROOT_DIR))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def index_grade_tds(data_dir: Path) -> int:
    """Index raw_text from all grade JSON files (TDS scraped data)."""
    from src.knowledge.literature.downloader import index_text_snippet
    total = 0
    for p in sorted(data_dir.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        raw = d.get("raw_text", "").strip()
        if len(raw) < 200:
            continue
        grade = d.get("grade_name", p.stem)
        source = f"TDS: {grade} ({d.get('supplier','')})"
        n = index_text_snippet(raw, source=source, doc_id=p.stem, doc_type="tds")
        if n:
            log.info("  Indexed TDS: %s (%d chunks)", grade, n)
            total += n
    return total


def index_local_pdfs(pdf_dir: Path) -> int:
    """Index any PDFs in the literature/pdfs directory."""
    from src.knowledge.literature.downloader import index_local_pdf
    total = 0
    for p in sorted(pdf_dir.glob("*.pdf")):
        log.info("Indexing local PDF: %s", p.name)
        n = index_local_pdf(p, doc_type="paper")
        total += n
        log.info("  → %d chunks", n)
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-papers",    action="store_true")
    parser.add_argument("--skip-tds",       action="store_true")
    parser.add_argument("--add-pdf",        type=str, default=None)
    parser.add_argument("--papers-per-query", type=int, default=8)
    args = parser.parse_args()

    from src.knowledge.rag.document_store import stats

    print("\n" + "="*60)
    print("  注塑成型 AI — 知识库构建工具")
    print("="*60)

    # ── 0. Add single PDF if requested ───────────────────────────
    if args.add_pdf:
        from src.knowledge.literature.downloader import index_local_pdf
        p = Path(args.add_pdf)
        if not p.exists():
            print(f"[ERROR] 文件不存在: {p}")
            sys.exit(1)
        n = index_local_pdf(p)
        print(f"✅ 已添加 {n} 个知识片段: {p.name}")
        print(f"   当前知识库状态: {stats()}")
        return

    total_added = 0

    # ── 1. Index grade TDS data (already scraped) ────────────────
    if not args.skip_tds:
        data_dir = ROOT_DIR / "data" / "grades"
        if data_dir.exists():
            print(f"\n[1/3] 正在索引牌号 TDS 数据 ({data_dir}) …")
            n = index_grade_tds(data_dir)
            print(f"      完成，新增 {n} 个知识片段")
            total_added += n
        else:
            print("[1/3] 数据目录不存在，跳过 TDS 索引（请先运行 scraper.py --seed）")

    # ── 2. Index PolyNC article ───────────────────────────────────
    articles_dir = ROOT_DIR / "articles"
    for pdf in articles_dir.glob("*.pdf"):
        print(f"\n[2/3] 正在索引本地文献: {pdf.name} …")
        from src.knowledge.literature.downloader import index_local_pdf
        n = index_local_pdf(pdf, doc_type="paper")
        print(f"      完成，新增 {n} 个知识片段")
        total_added += n

    # Also check articles/*.md (PolyNC.md etc.)
    for md in articles_dir.glob("*.md"):
        from src.knowledge.literature.downloader import index_text_snippet
        text = md.read_text(encoding="utf-8", errors="ignore")
        if len(text) > 200:
            n = index_text_snippet(text, source=md.name, doc_id=md.stem, doc_type="paper")
            print(f"  索引文档: {md.name} → {n} 个片段")
            total_added += n

    # ── 3. Search and download papers ────────────────────────────
    if not args.skip_papers:
        print(f"\n[3/3] 正在从 Semantic Scholar + arXiv 搜索并下载文献 …")
        print("      这可能需要 5-15 分钟，取决于网络速度")
        from src.knowledge.literature.searcher import collect_papers
        from src.knowledge.literature.downloader import index_paper

        papers = collect_papers(papers_per_query=args.papers_per_query)
        print(f"      找到 {len(papers)} 篇有可用 PDF 的论文")

        for i, paper in enumerate(papers, 1):
            print(f"  [{i}/{len(papers)}] {paper['title'][:60]} ({paper['year']})")
            n = index_paper(paper)
            total_added += n
            time.sleep(1.0)   # polite to servers

    # ── Summary ──────────────────────────────────────────────────
    s = stats()
    print("\n" + "="*60)
    print(f"✅ 知识库构建完成！")
    print(f"   本次新增: {total_added} 个知识片段")
    print(f"   知识库总量: {s.get('total_chunks', '?')} 个片段")
    print(f"   存储路径: {s.get('db_path', '')}")
    print("="*60)
    print("\n现在可以运行: streamlit run app.py")


if __name__ == "__main__":
    main()
