"""
Test script to diagnose Docling DOCX parsing and heading extraction.
"""

from docling.document_converter import DocumentConverter
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from pathlib import Path
import sys


def test_docling_extraction(file_path: str):
    """Test what Docling extracts from a DOCX file."""

    print(f"\n{'='*80}")
    print(f"Testing Docling extraction for: {file_path}")
    print(f"{'='*80}\n")

    # Create converter
    converter = DocumentConverter()

    # Convert document
    print("Step 1: Converting document...")
    result = converter.convert(file_path)
    doc = result.document

    print(f"✅ Document converted successfully")
    print(f"   Type: {type(doc).__name__}")
    print(f"   Attributes: {[a for a in dir(doc) if not a.startswith('_')][:20]}")

    # Check if document has headings/titles
    print("\nStep 2: Checking document structure...")

    # Export to markdown to see structure
    markdown = doc.export_to_markdown()
    print(f"\n📄 Full Markdown Export ({len(markdown)} chars):")
    print("-" * 80)
    print(markdown[:1000])  # First 1000 chars
    print("-" * 80)

    # Check for headings in markdown
    heading_lines = [line for line in markdown.split('\n') if line.startswith('#')]
    print(f"\n📋 Found {len(heading_lines)} heading lines in markdown:")
    for heading in heading_lines[:10]:
        print(f"   {heading}")

    # Try exporting to text
    print("\nStep 3: Plain text export...")
    text = doc.export_to_text()
    print(f"   Text length: {len(text)} chars")
    print(f"   First 500 chars:")
    print("-" * 80)
    print(text[:500])
    print("-" * 80)

    # Now test chunking
    print("\nStep 4: Testing HybridChunker...")
    from rag_processor.utils.token_utils import create_google_tokenizer
    from rag_processor.services.embedding_service import get_embedding_service

    embedding_service = get_embedding_service()
    tokenizer = create_google_tokenizer(embedding_service.genai_client)

    chunker = HybridChunker(tokenizer=tokenizer, merge_peers=True)
    chunks = list(chunker.chunk(dl_doc=doc))

    print(f"\n✅ Generated {len(chunks)} chunks")

    for i, chunk in enumerate(chunks):
        print(f"\n📦 Chunk {i}:")
        print(f"   Length: {len(chunk.text)} chars")
        print(f"   Text preview:")
        print("-" * 80)
        print(chunk.text[:200])
        print("-" * 80)

        # Check metadata
        if hasattr(chunk, 'meta'):
            print(f"   Meta attributes: {[a for a in dir(chunk.meta) if not a.startswith('_')][:10]}")
            if hasattr(chunk.meta, 'doc_items'):
                print(f"   Doc items count: {len(chunk.meta.doc_items)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_docling_docx.py <path-to-docx-file>")
        sys.exit(1)

    test_docling_extraction(sys.argv[1])
