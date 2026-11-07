#!/usr/bin/env python3
"""
Test script for TextNormalizer functionality.

Tests the normalize_text function that fixes common PDF/DOCX extraction issues
where text gets extracted with word-per-line formatting.

Usage:
    cd apps/rag-processor
    uv run python -m llamaindex_test.test_text_normalizer

    # Or with a specific file:
    uv run python -m llamaindex_test.test_text_normalizer --file path/to/document.pdf
"""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from rag_processor.services.llamaindex_document_service import normalize_text


def test_basic_normalization() -> None:
    """Test basic text normalization cases."""
    print("\n" + "=" * 60)
    print("TEST 1: Basic Word-Per-Line Fix")
    print("=" * 60)

    # Simulate the problematic word-per-line extraction
    problematic_text = """The
pipeline
reads
a
document
and
stores
its
chunks."""

    expected = "The pipeline reads a document and stores its chunks."

    result = normalize_text(problematic_text)

    print("\n📥 INPUT (problematic):")
    print("-" * 40)
    print(repr(problematic_text))

    print("\n📤 OUTPUT (normalized):")
    print("-" * 40)
    print(repr(result))

    print("\n✅ EXPECTED:")
    print("-" * 40)
    print(repr(expected))

    if result == expected:
        print("\n✅ PASS: Basic normalization works correctly!")
    else:
        print("\n❌ FAIL: Result doesn't match expected")
        print(f"   Diff: {set(result) - set(expected)}")


def test_paragraph_preservation() -> None:
    """Test that paragraph breaks are preserved."""
    print("\n" + "=" * 60)
    print("TEST 2: Paragraph Preservation")
    print("=" * 60)

    text_with_paragraphs = """This is the first paragraph with
some word wrapping that should
be joined together.

This is the second paragraph
that should remain separate
from the first one.

And a third paragraph here."""

    result = normalize_text(text_with_paragraphs)

    print("\n📥 INPUT:")
    print("-" * 40)
    print(text_with_paragraphs)

    print("\n📤 OUTPUT:")
    print("-" * 40)
    print(result)

    # Check that we have exactly 2 paragraph breaks (3 paragraphs)
    paragraph_count = result.count("\n\n") + 1
    print(f"\n📊 Paragraph count: {paragraph_count}")

    if paragraph_count == 3 and "\n\n" in result:
        print("✅ PASS: Paragraphs preserved correctly!")
    else:
        print("❌ FAIL: Paragraph structure not preserved")


def test_list_preservation() -> None:
    """Test that bullet points and lists are preserved."""
    print("\n" + "=" * 60)
    print("TEST 3: List Item Preservation")
    print("=" * 60)

    text_with_lists = """Here are the features:
• Weekly maintenance window
• Document storage access
• Processing status reports

And numbered items:
1. First step in the process
2. Second step follows
3. Third step completes it"""

    result = normalize_text(text_with_lists)

    print("\n📥 INPUT:")
    print("-" * 40)
    print(text_with_lists)

    print("\n📤 OUTPUT:")
    print("-" * 40)
    print(result)

    # Check that bullet points are on separate lines
    has_bullets = "• Weekly maintenance" in result and "• Document storage" in result
    has_numbers = "1." in result and "2." in result

    if has_bullets and has_numbers:
        print("✅ PASS: List items preserved correctly!")
    else:
        print("❌ FAIL: List structure not preserved")


def test_multiline_document_example() -> None:
    """Check a synthetic document with wrapped text and a feature list."""
    problematic_content = """Operations Handbook
The
pipeline
reads
a
document
and
stores
its
chunks.
• Upload documents
• Validate ownership
• Download source files
• Extract content
• Generate embeddings
• Store document chunks
• Report processing status"""

    result = normalize_text(problematic_content)
    sentence_fixed = "The pipeline reads a document and stores its chunks." in result
    bullets_preserved = result.count("•") == 7
    assert sentence_fixed, "Wrapped sentence was not reconstructed"
    assert bullets_preserved, "Bullet points were not preserved"


def test_edge_cases() -> None:
    """Test edge cases."""
    print("\n" + "=" * 60)
    print("TEST 5: Edge Cases")
    print("=" * 60)

    test_cases = [
        ("Empty string", "", ""),
        ("Single word", "Hello", "Hello"),
        ("Already clean", "This is a normal sentence.", "This is a normal sentence."),
        ("Multiple spaces", "Too   many    spaces", "Too many spaces"),
        ("Tabs and spaces", "Mixed\t  whitespace", "Mixed whitespace"),
    ]

    all_passed = True
    for name, input_text, expected in test_cases:
        result = normalize_text(input_text)
        passed = result == expected
        status = "✅" if passed else "❌"
        print(f"   {status} {name}: '{input_text}' → '{result}'")
        if not passed:
            print(f"      Expected: '{expected}'")
            all_passed = False

    if all_passed:
        print("\n✅ PASS: All edge cases handled correctly!")
    else:
        print("\n❌ FAIL: Some edge cases failed")


async def test_with_document(file_path: str) -> None:
    """Test normalization with an actual document file."""
    print("\n" + "=" * 60)
    print(f"TEST 6: Document Processing - {Path(file_path).name}")
    print("=" * 60)

    from rag_processor.services.llamaindex_document_service import (
        LlamaIndexDocumentService,
    )

    service = LlamaIndexDocumentService(
        chunk_size=1000,
        chunk_overlap=200,
    )

    try:
        chunks = await service.process_document_file(
            document_path=file_path,
            user_id="test-user",
            document_id="test-doc",
        )

        print(f"\n📄 Document: {file_path}")
        print(f"📦 Chunks generated: {len(chunks)}")

        if chunks:
            print("\n📝 First chunk preview:")
            print("-" * 40)
            preview = chunks[0].text[:500]
            print(preview)
            if len(chunks[0].text) > 500:
                print("... [truncated]")

            # Check for word-per-line issues in output
            lines = chunks[0].text.split("\n")
            short_lines = [l for l in lines if 0 < len(l.strip()) < 15]
            short_line_ratio = len(short_lines) / len(lines) if lines else 0

            print(f"\n📊 Quality check:")
            print(f"   - Total lines in first chunk: {len(lines)}")
            print(f"   - Short lines (<15 chars): {len(short_lines)}")
            print(f"   - Short line ratio: {short_line_ratio:.1%}")

            if short_line_ratio < 0.3:
                print("   ✅ Text appears well-formed (low short-line ratio)")
            else:
                print("   ⚠️ Text may still have formatting issues (high short-line ratio)")

    except Exception as e:
        print(f"\n❌ Error processing document: {e}")


def main() -> None:
    """Run all tests."""
    parser = argparse.ArgumentParser(
        description="Test TextNormalizer functionality"
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Optional: Path to a document file to test with",
    )
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("🧪 TEXT NORMALIZER TEST SUITE")
    print("=" * 60)

    # Run unit tests
    test_basic_normalization()
    test_paragraph_preservation()
    test_list_preservation()
    test_multiline_document_example()
    test_edge_cases()

    # Optionally test with a real document
    if args.file:
        import asyncio

        asyncio.run(test_with_document(args.file))

    print("\n" + "=" * 60)
    print("🏁 TEST SUITE COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()
