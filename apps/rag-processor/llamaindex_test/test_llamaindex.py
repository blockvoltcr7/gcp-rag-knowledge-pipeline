#!/usr/bin/env python3
"""
LlamaIndex Document Processing Test Script

A simple standalone script to test LlamaIndex document processing
before full integration into the RAG processor.

Usage:
    python test_llamaindex.py                    # Test all files in test_files/
    python test_llamaindex.py --file sample.md   # Test specific file
    python test_llamaindex.py --file sample.pdf --use-llamaparse  # Use LlamaParse for PDF
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

# =============================================================================
# Configuration
# =============================================================================

# Load environment variables from .env.local
env_path = Path(__file__).parent.parent / ".env.local"
load_dotenv(env_path)

# LlamaParse API Key (from environment)
LLAMAPARSE_API_KEY = os.getenv("LLAMAPARSE_API_KEY", "")

if not LLAMAPARSE_API_KEY:
    print("⚠️  Warning: LLAMAPARSE_API_KEY not found in environment.")
    print(f"   Expected in: {env_path}")

# Paths
SCRIPT_DIR = Path(__file__).parent
TEST_FILES_DIR = SCRIPT_DIR / "test_files"
OUTPUT_DIR = SCRIPT_DIR / "output"


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


def print_chunk(idx: int, chunk: dict, max_text_length: int = 200) -> None:
    """Print a formatted chunk."""
    text = chunk.get("text", "")
    text_preview = text[:max_text_length] + "..." if len(text) > max_text_length else text

    print(f"\n[Chunk {idx + 1}]")
    print(f"  Length: {len(text)} characters")
    print(f"  Preview: {text_preview}")

    if chunk.get("metadata"):
        print(f"  Metadata: {json.dumps(chunk['metadata'], indent=4, default=str)}")


def save_results(filename: str, results: dict) -> Path:
    """Save processing results to JSON file."""
    OUTPUT_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = OUTPUT_DIR / f"{Path(filename).stem}_{timestamp}_results.json"

    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)

    return output_file


# =============================================================================
# LlamaIndex Processing Functions
# =============================================================================

def process_with_simple_reader(file_path: Path, chunk_size: int, chunk_overlap: int) -> list[dict]:
    """
    Process a file using LlamaIndex SimpleDirectoryReader with file-specific readers.
    """
    from llama_index.core import SimpleDirectoryReader
    from llama_index.core.node_parser import SentenceSplitter

    print_section("Loading document with SimpleDirectoryReader")

    # Determine file type and select appropriate reader
    extension = file_path.suffix.lower()
    file_extractor = {}

    if extension in [".docx", ".doc"]:
        from llama_index.readers.file import DocxReader
        file_extractor[extension] = DocxReader()
        print(f"  Using: DocxReader for {extension}")

    elif extension in [".md", ".markdown"]:
        from llama_index.readers.file import MarkdownReader
        file_extractor[extension] = MarkdownReader()
        print(f"  Using: MarkdownReader for {extension}")

    elif extension == ".pdf":
        from llama_index.readers.file import PDFReader
        file_extractor[extension] = PDFReader()
        print(f"  Using: PDFReader for {extension}")

    elif extension in [".html", ".htm"]:
        from llama_index.readers.file import HTMLTagReader
        file_extractor[extension] = HTMLTagReader()
        print(f"  Using: HTMLTagReader for {extension}")

    else:
        print(f"  Using: Default reader for {extension}")

    # Load document
    reader = SimpleDirectoryReader(
        input_files=[str(file_path)],
        file_extractor=file_extractor if file_extractor else None,
    )

    documents = reader.load_data()
    print(f"  Loaded {len(documents)} document(s)")

    # Show raw document content
    if documents:
        total_chars = sum(len(doc.text) for doc in documents)
        print(f"  Total characters in documents: {total_chars:,}")

    # Parse into chunks
    print_section("Chunking with SentenceSplitter")
    print(f"  Chunk size: {chunk_size}")
    print(f"  Chunk overlap: {chunk_overlap}")

    splitter = SentenceSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    nodes = splitter.get_nodes_from_documents(documents)
    print(f"  Generated {len(nodes)} chunks")

    # Convert to simple dict format
    chunks = []
    for idx, node in enumerate(nodes):
        chunks.append({
            "index": idx,
            "text": node.text,
            "length": len(node.text),
            "metadata": dict(node.metadata) if node.metadata else {},
        })

    return chunks


def process_with_llamaparse(file_path: Path, chunk_size: int, chunk_overlap: int) -> list[dict]:
    """
    Process a PDF file using LlamaParse (cloud-based, high-quality parsing).
    """
    from llama_parse import LlamaParse
    from llama_index.core.node_parser import SentenceSplitter

    print_section("Loading document with LlamaParse")
    print(f"  API Key: {LLAMAPARSE_API_KEY[:15]}...")

    # Initialize LlamaParse
    parser = LlamaParse(
        api_key=LLAMAPARSE_API_KEY,
        result_type="markdown",
        verbose=True,
    )

    # Parse the document
    print("  Parsing document (this may take a moment)...")
    documents = parser.load_data(str(file_path))
    print(f"  Loaded {len(documents)} document(s)")

    # Show raw content preview
    if documents:
        content_preview = documents[0].text[:500]
        print(f"\n  Raw content preview:\n  {content_preview}...")

    # Parse into chunks
    print_section("Chunking with SentenceSplitter")
    print(f"  Chunk size: {chunk_size}")
    print(f"  Chunk overlap: {chunk_overlap}")

    splitter = SentenceSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    nodes = splitter.get_nodes_from_documents(documents)
    print(f"  Generated {len(nodes)} chunks")

    # Convert to simple dict format
    chunks = []
    for idx, node in enumerate(nodes):
        chunks.append({
            "index": idx,
            "text": node.text,
            "length": len(node.text),
            "metadata": dict(node.metadata) if node.metadata else {},
        })

    return chunks


def process_file(file_path: Path, use_llamaparse: bool, chunk_size: int, chunk_overlap: int) -> dict:
    """
    Process a single file and return results.
    """
    print_header(f"Processing: {file_path.name}")
    print(f"  Path: {file_path}")
    print(f"  Size: {file_path.stat().st_size:,} bytes")
    print(f"  Extension: {file_path.suffix}")

    start_time = datetime.now()

    try:
        # Choose processing method
        if use_llamaparse and file_path.suffix.lower() == ".pdf":
            chunks = process_with_llamaparse(file_path, chunk_size, chunk_overlap)
            processor = "LlamaParse"
        else:
            chunks = process_with_simple_reader(file_path, chunk_size, chunk_overlap)
            processor = "SimpleDirectoryReader"

        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()

        # Build results
        results = {
            "status": "success",
            "file": str(file_path),
            "filename": file_path.name,
            "extension": file_path.suffix,
            "file_size_bytes": file_path.stat().st_size,
            "processor": processor,
            "chunk_settings": {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
            },
            "processing_time_seconds": processing_time,
            "total_chunks": len(chunks),
            "total_characters": sum(c["length"] for c in chunks),
            "avg_chunk_length": sum(c["length"] for c in chunks) // len(chunks) if chunks else 0,
            "chunks": chunks,
        }

        # Print summary
        print_section("Results Summary")
        print(f"  Status: ✅ SUCCESS")
        print(f"  Processor: {processor}")
        print(f"  Processing time: {processing_time:.2f} seconds")
        print(f"  Total chunks: {len(chunks)}")
        print(f"  Total characters: {results['total_characters']:,}")
        print(f"  Average chunk length: {results['avg_chunk_length']} chars")

        # Print first few chunks
        print_section("Chunk Previews (first 3)")
        for i, chunk in enumerate(chunks[:3]):
            print_chunk(i, chunk)

        if len(chunks) > 3:
            print(f"\n  ... and {len(chunks) - 3} more chunks")

        return results

    except Exception as e:
        import traceback
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()

        error_results = {
            "status": "error",
            "file": str(file_path),
            "filename": file_path.name,
            "error": str(e),
            "error_type": type(e).__name__,
            "processing_time_seconds": processing_time,
            "traceback": traceback.format_exc(),
        }

        print_section("Results Summary")
        print(f"  Status: ❌ ERROR")
        print(f"  Error Type: {type(e).__name__}")
        print(f"  Error Message: {e}")
        print(f"\n  Traceback:\n{traceback.format_exc()}")

        return error_results


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main entry point for the test script."""
    parser = argparse.ArgumentParser(
        description="Test LlamaIndex document processing"
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        help="Specific file to process (relative to test_files/)",
    )
    parser.add_argument(
        "--use-llamaparse", "-l",
        action="store_true",
        help="Use LlamaParse for PDF files (requires API key)",
    )
    parser.add_argument(
        "--chunk-size", "-c",
        type=int,
        default=1000,
        help="Chunk size (default: 1000)",
    )
    parser.add_argument(
        "--chunk-overlap", "-o",
        type=int,
        default=200,
        help="Chunk overlap (default: 200)",
    )
    parser.add_argument(
        "--save", "-s",
        action="store_true",
        help="Save results to JSON file",
    )

    args = parser.parse_args()

    print_header("LlamaIndex Document Processing Test")
    print(f"  Test Files Directory: {TEST_FILES_DIR}")
    print(f"  Output Directory: {OUTPUT_DIR}")
    print(f"  Chunk Size: {args.chunk_size}")
    print(f"  Chunk Overlap: {args.chunk_overlap}")
    print(f"  Use LlamaParse: {args.use_llamaparse}")

    # Determine files to process
    if args.file:
        file_path = TEST_FILES_DIR / args.file
        if not file_path.exists():
            print(f"\n❌ Error: File not found: {file_path}")
            print(f"\nAvailable files in {TEST_FILES_DIR}:")
            if TEST_FILES_DIR.exists():
                for f in TEST_FILES_DIR.iterdir():
                    print(f"  - {f.name}")
            sys.exit(1)

        files_to_process = [file_path]
    else:
        if not TEST_FILES_DIR.exists():
            print(f"\n❌ Error: Test files directory not found: {TEST_FILES_DIR}")
            sys.exit(1)

        files_to_process = [
            f for f in TEST_FILES_DIR.iterdir()
            if f.is_file() and f.suffix.lower() in [".pdf", ".docx", ".md", ".txt", ".html"]
        ]

        if not files_to_process:
            print(f"\n⚠️  No supported files found in {TEST_FILES_DIR}")
            print("  Supported extensions: .pdf, .docx, .md, .txt, .html")
            sys.exit(0)

    print(f"\n  Files to process: {len(files_to_process)}")
    for f in files_to_process:
        print(f"    - {f.name}")

    # Process each file
    all_results = []

    for file_path in files_to_process:
        results = process_file(
            file_path,
            use_llamaparse=args.use_llamaparse,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
        all_results.append(results)

        if args.save:
            output_file = save_results(file_path.name, results)
            print(f"\n  📄 Results saved to: {output_file}")

    # Print final summary
    print_header("Final Summary")

    success_count = sum(1 for r in all_results if r["status"] == "success")
    error_count = sum(1 for r in all_results if r["status"] == "error")

    print(f"  Total files processed: {len(all_results)}")
    print(f"  Successful: {success_count}")
    print(f"  Errors: {error_count}")

    if success_count > 0:
        total_chunks = sum(r.get("total_chunks", 0) for r in all_results if r["status"] == "success")
        total_chars = sum(r.get("total_characters", 0) for r in all_results if r["status"] == "success")
        print(f"  Total chunks generated: {total_chunks}")
        print(f"  Total characters processed: {total_chars:,}")

    print("\n✅ Test complete!")

    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
