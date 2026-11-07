"""
Test script to diagnose heading detection in Docling 2.71.0
"""

import asyncio
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from rag_processor.utils.token_utils import create_google_tokenizer


async def test_heading_detection(pdf_path: str) -> None:
    """Test what headings Docling detects in a PDF."""
    print(f"\n🔍 Testing heading detection for: {pdf_path}\n")

    # Step 1: Create DocumentConverter (same config as production)
    pipeline_options = PdfPipelineOptions(
        do_ocr=False,
        do_table_structure=False,
        do_code_enrichment=False,
        do_formula_enrichment=False,
        do_picture_classification=False,
        do_picture_description=False,
    )

    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )

    # Step 2: Convert document
    print("📄 Converting document...")
    result = converter.convert(pdf_path)
    dl_document = result.document

    # Step 3: Check document structure for headings
    print("\n📋 Document Structure Analysis:")
    print(f"  Total elements: {len(list(dl_document.iterate_items()))}")

    # Look for heading elements in document
    heading_elements = []
    for item in dl_document.iterate_items():
        item_type = type(item).__name__
        if "heading" in item_type.lower() or "title" in item_type.lower():
            heading_elements.append((item_type, getattr(item, 'text', str(item))[:100]))

    if heading_elements:
        print(f"\n  ✅ Found {len(heading_elements)} heading elements:")
        for item_type, text in heading_elements:
            print(f"    - {item_type}: {text}")
    else:
        print("\n  ⚠️  No heading elements found in document structure")

    # Step 4: Export to markdown to see structure
    print("\n📝 Markdown Export (first 500 chars):")
    try:
        markdown_text = dl_document.export_to_markdown()
        print(markdown_text[:500])

        # Count markdown headings
        md_headings = [line for line in markdown_text.split('\n') if line.strip().startswith('#')]
        print(f"\n  Markdown headings found: {len(md_headings)}")
        for heading in md_headings[:5]:
            print(f"    {heading}")
    except Exception as e:
        print(f"  ❌ Markdown export failed: {e}")

    # Step 5: Test chunking and check chunk.meta.headings
    print("\n🔪 Chunking Analysis:")

    # Create tokenizer (using the same one as production)
    try:
        from rag_processor.utils.token_utils import create_google_tokenizer
        from google import genai

        # This will fail locally without Google credentials, so skip chunking analysis
        print("  ⚠️  Skipping chunking (requires Google credentials)")
        print("\n" + "="*60)
        print("✅ Diagnostic complete (partial)")
        return
    except Exception:
        pass

    chunker = HybridChunker(
        max_tokens=2047,
        merge_peers=True,
    )

    chunk_objects = list(chunker.chunk(dl_doc=dl_document))
    print(f"  Total chunks: {len(chunk_objects)}")

    # Analyze first few chunks
    for i, chunk_obj in enumerate(chunk_objects[:5]):
        print(f"\n  Chunk {i}:")
        print(f"    Text preview: {chunk_obj.text[:100]}...")
        print(f"    Has meta: {chunk_obj.meta is not None}")

        if chunk_obj.meta:
            print(f"    Has headings attr: {hasattr(chunk_obj.meta, 'headings')}")
            if hasattr(chunk_obj.meta, 'headings'):
                headings = chunk_obj.meta.headings
                print(f"    Headings value: {headings}")
                print(f"    Headings type: {type(headings)}")
            else:
                print(f"    ⚠️  No 'headings' attribute on meta")
                print(f"    Available meta attrs: {dir(chunk_obj.meta)}")
        else:
            print(f"    ⚠️  No meta object")

    print("\n" + "="*60)
    print("✅ Diagnostic complete")


if __name__ == "__main__":
    # Test with a sample PDF - replace with actual path
    test_pdf = "/tmp/test_document.pdf"

    import sys
    if len(sys.argv) > 1:
        test_pdf = sys.argv[1]

    if not Path(test_pdf).exists():
        print(f"❌ PDF not found: {test_pdf}")
        print("\nUsage: python test_heading_detection.py /path/to/document.pdf")
        sys.exit(1)

    asyncio.run(test_heading_detection(test_pdf))
