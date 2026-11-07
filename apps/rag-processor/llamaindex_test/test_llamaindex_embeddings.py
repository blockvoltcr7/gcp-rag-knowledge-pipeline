#!/usr/bin/env python3
"""
LlamaIndex + Gemini Embeddings Test Script

Tests the full RAG pipeline: document loading → chunking → embedding generation.
A standalone script (not pytest) for inspecting the complete processing flow.

Usage:
    cd apps/rag-processor

    # Test with default sample file
    uv run python llamaindex_test/test_llamaindex_embeddings.py

    # Test with specific file
    uv run python llamaindex_test/test_llamaindex_embeddings.py --file sample_document.md

    # Use LlamaParse for PDF (requires LLAMAPARSE_API_KEY)
    uv run python llamaindex_test/test_llamaindex_embeddings.py --file document.pdf --use-llamaparse

    # Save results to JSON
    uv run python llamaindex_test/test_llamaindex_embeddings.py --save

Environment:
    GOOGLE_CLOUD_PROJECT_ID - Required for Gemini embeddings
    LLAMAPARSE_API_KEY      - Optional, for enhanced PDF processing
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

# =============================================================================
# Configuration
# =============================================================================

# Load environment variables from .env.local
ENV_PATH = Path(__file__).parent.parent / ".env.local"
load_dotenv(ENV_PATH)

# Paths
SCRIPT_DIR = Path(__file__).parent
TEST_FILES_DIR = SCRIPT_DIR / "test_files"
OUTPUT_DIR = SCRIPT_DIR / "output"

# Default test file
DEFAULT_TEST_FILE = "sample_document.md"


# =============================================================================
# Helper Functions
# =============================================================================


def print_header(title: str) -> None:
    """Print a formatted header."""
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def print_section(title: str) -> None:
    """Print a section header."""
    print(f"\n--- {title} ---")


def print_chunk_with_embedding(
    idx: int,
    text: str,
    embedding: list[float] | None,
    max_preview_length: int = 150,
) -> None:
    """Print chunk information including embedding statistics."""
    # Text preview
    text_preview = text[:max_preview_length]
    if len(text) > max_preview_length:
        text_preview += "..."

    print(f"\n[Chunk {idx}]")
    print(f"  Length: {len(text)} chars")
    print(f'  Preview: "{text_preview}"')

    # Embedding stats
    if embedding:
        min_val = min(embedding)
        max_val = max(embedding)
        print(f"  Embedding: {len(embedding)} dimensions")
        print(f"  Range: [{min_val:.4f}, {max_val:.4f}]")
    else:
        print("  Embedding: None (generation failed)")


def save_results(results: dict, filename: str) -> Path:
    """Save processing results to JSON file."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"{Path(filename).stem}_embeddings_{timestamp}.json"

    # Convert embeddings to a summary (full embeddings would be very large)
    results_to_save = {**results}
    if "chunks" in results_to_save:
        for chunk in results_to_save["chunks"]:
            if chunk.get("embedding"):
                emb = chunk["embedding"]
                chunk["embedding_summary"] = {
                    "dimensions": len(emb),
                    "min": min(emb),
                    "max": max(emb),
                    "first_5": emb[:5],
                    "last_5": emb[-5:],
                }
                # Remove full embedding to keep file size manageable
                del chunk["embedding"]

    with open(output_file, "w") as f:
        json.dump(results_to_save, f, indent=2, default=str)

    return output_file


# =============================================================================
# Main Processing Function
# =============================================================================


async def process_document_with_embeddings(
    file_path: Path,
    use_llamaparse: bool,
    chunk_size: int,
    chunk_overlap: int,
) -> dict:
    """
    Process a document and generate embeddings for all chunks.

    Args:
        file_path: Path to the document
        use_llamaparse: Whether to use LlamaParse for PDFs
        chunk_size: Size of text chunks
        chunk_overlap: Overlap between chunks

    Returns:
        Dictionary containing processing results and chunk data
    """
    # Import services (avoid import at module level for cleaner error messages)
    from rag_processor.services.embedding_service import get_embedding_service
    from rag_processor.services.llamaindex_document_service import (
        LlamaIndexDocumentService,
    )

    print_header(f"Processing: {file_path.name}")
    print(f"  Path: {file_path}")
    print(f"  Size: {file_path.stat().st_size:,} bytes")
    print(f"  Extension: {file_path.suffix}")

    start_time = datetime.now()

    # Get project ID from environment
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT_ID")
    if not project_id:
        print("\n  ERROR: GOOGLE_CLOUD_PROJECT_ID environment variable not set")
        return {"status": "error", "error": "Missing GOOGLE_CLOUD_PROJECT_ID"}

    try:
        # Initialize services
        print_section("Initializing services")

        doc_service = LlamaIndexDocumentService(
            project_id=project_id,
            use_llamaparse=use_llamaparse,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        print(f"  LlamaIndex service: chunk_size={chunk_size}, overlap={chunk_overlap}")
        print(f"  LlamaParse: {'enabled' if use_llamaparse else 'disabled'}")

        embedding_service = get_embedding_service(project_id)
        print(f"  Embedding model: {embedding_service.text_model}")
        print(f"  Embedding dimensions: {embedding_service.text_dimensions}")

        # Process document (load + chunk)
        print_section("Loading and chunking document")

        chunks = await doc_service.process_document_file(
            document_path=str(file_path),
            user_id="test-user",
            document_id="test-document",
        )

        print(f"  Loaded and chunked successfully")
        print(f"  Total chunks: {len(chunks)}")

        if not chunks:
            return {
                "status": "error",
                "error": "No chunks generated from document",
                "file": str(file_path),
            }

        total_chars = sum(len(c.text) for c in chunks)
        print(f"  Total characters: {total_chars:,}")
        print(f"  Average chunk size: {total_chars // len(chunks)} chars")

        # Generate embeddings
        print_section("Generating embeddings with gemini-embedding-001")

        chunk_results = []
        embeddings_generated = 0
        embeddings_failed = 0

        for idx, chunk in enumerate(chunks):
            try:
                embedding = await embedding_service.generate_text_embedding(chunk.text)
                chunk.text_embedding = embedding
                embeddings_generated += 1

                chunk_results.append(
                    {
                        "index": idx,
                        "text": chunk.text,
                        "length": len(chunk.text),
                        "embedding": embedding,
                    }
                )
            except Exception as e:
                embeddings_failed += 1
                print(f"  WARNING: Failed to generate embedding for chunk {idx}: {e}")
                chunk_results.append(
                    {
                        "index": idx,
                        "text": chunk.text,
                        "length": len(chunk.text),
                        "embedding": None,
                        "error": str(e),
                    }
                )

        print(f"\n  Embeddings generated: {embeddings_generated}/{len(chunks)}")
        if embeddings_failed > 0:
            print(f"  Embeddings failed: {embeddings_failed}")

        # Calculate processing time
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()

        # Print chunk previews
        print_section("Chunk Previews")

        for chunk_data in chunk_results[:5]:  # Show first 5 chunks
            print_chunk_with_embedding(
                idx=chunk_data["index"],
                text=chunk_data["text"],
                embedding=chunk_data.get("embedding"),
            )

        if len(chunk_results) > 5:
            print(f"\n  ... and {len(chunk_results) - 5} more chunks")

        # Build results summary
        results = {
            "status": "success",
            "file": str(file_path),
            "filename": file_path.name,
            "extension": file_path.suffix,
            "file_size_bytes": file_path.stat().st_size,
            "processing_time_seconds": processing_time,
            "chunk_settings": {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            },
            "embedding_settings": {
                "model": embedding_service.text_model,
                "dimensions": embedding_service.text_dimensions,
            },
            "total_chunks": len(chunks),
            "total_characters": total_chars,
            "embeddings_generated": embeddings_generated,
            "embeddings_failed": embeddings_failed,
            "chunks": chunk_results,
        }

        # Print summary
        print_section("Summary")
        print(f"  Status: SUCCESS")
        print(f"  Processing time: {processing_time:.2f} seconds")
        print(f"  Total chunks: {len(chunks)}")
        print(f"  All embeddings generated: {'Yes' if embeddings_failed == 0 else 'No'}")
        print(f"  Embedding dimensions: {embedding_service.text_dimensions}")

        return results

    except Exception as e:
        import traceback

        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()

        print_section("Error")
        print(f"  Status: FAILED")
        print(f"  Error type: {type(e).__name__}")
        print(f"  Error message: {e}")
        print(f"\n  Traceback:\n{traceback.format_exc()}")

        return {
            "status": "error",
            "file": str(file_path),
            "error": str(e),
            "error_type": type(e).__name__,
            "processing_time_seconds": processing_time,
            "traceback": traceback.format_exc(),
        }


# =============================================================================
# Main Entry Point
# =============================================================================


async def async_main(
    file_arg: str | None,
    use_llamaparse: bool,
    chunk_size: int,
    chunk_overlap: int,
    save: bool,
) -> int:
    """Async main function."""
    print_header("LlamaIndex + Gemini Embeddings Test")
    print(f"  Environment file: {ENV_PATH}")
    print(f"  Test files directory: {TEST_FILES_DIR}")
    print(f"  Chunk size: {chunk_size}")
    print(f"  Chunk overlap: {chunk_overlap}")
    print(f"  Use LlamaParse: {use_llamaparse}")

    # Check environment
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT_ID")
    if not project_id:
        print("\n  ERROR: GOOGLE_CLOUD_PROJECT_ID not set")
        print(f"  Please set it in: {ENV_PATH}")
        return 1

    print(f"  Project ID: {project_id}")

    # Determine file to process
    if file_arg:
        # Check if it's an absolute path or relative to test_files
        file_path = Path(file_arg)
        if not file_path.is_absolute():
            file_path = TEST_FILES_DIR / file_arg

        if not file_path.exists():
            print(f"\n  ERROR: File not found: {file_path}")
            print(f"\n  Available files in {TEST_FILES_DIR}:")
            if TEST_FILES_DIR.exists():
                for f in sorted(TEST_FILES_DIR.iterdir()):
                    if f.is_file():
                        print(f"    - {f.name}")
            return 1
    else:
        file_path = TEST_FILES_DIR / DEFAULT_TEST_FILE
        if not file_path.exists():
            # Try to find any available file
            available_files = [
                f
                for f in TEST_FILES_DIR.iterdir()
                if f.is_file()
                and f.suffix.lower() in [".md", ".txt", ".pdf", ".docx"]
            ]
            if available_files:
                file_path = available_files[0]
                print(f"\n  Note: Default file not found, using: {file_path.name}")
            else:
                print(f"\n  ERROR: No test files found in {TEST_FILES_DIR}")
                return 1

    print(f"\n  File to process: {file_path.name}")

    # Process the document
    results = await process_document_with_embeddings(
        file_path=file_path,
        use_llamaparse=use_llamaparse,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    # Save results if requested
    if save and results.get("status") == "success":
        output_file = save_results(results, file_path.name)
        print(f"\n  Results saved to: {output_file}")

    # Final status
    print_header("Test Complete")

    if results.get("status") == "success":
        print("  Result: SUCCESS")
        return 0
    else:
        print(f"  Result: FAILED - {results.get('error', 'Unknown error')}")
        return 1


def main() -> int:
    """Main entry point for the test script."""
    parser = argparse.ArgumentParser(
        description="Test LlamaIndex document processing with Gemini embeddings"
    )
    parser.add_argument(
        "--file",
        "-f",
        type=str,
        help="File to process (relative to test_files/ or absolute path)",
    )
    parser.add_argument(
        "--use-llamaparse",
        "-l",
        action="store_true",
        help="Use LlamaParse for PDF files (requires LLAMAPARSE_API_KEY)",
    )
    parser.add_argument(
        "--chunk-size",
        "-c",
        type=int,
        default=1000,
        help="Chunk size (default: 1000)",
    )
    parser.add_argument(
        "--chunk-overlap",
        "-o",
        type=int,
        default=200,
        help="Chunk overlap (default: 200)",
    )
    parser.add_argument(
        "--save",
        "-s",
        action="store_true",
        help="Save results to JSON file",
    )

    args = parser.parse_args()

    return asyncio.run(
        async_main(
            file_arg=args.file,
            use_llamaparse=args.use_llamaparse,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            save=args.save,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
