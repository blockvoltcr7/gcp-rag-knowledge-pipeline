# Sample Document for LlamaIndex Testing

## Introduction

This is a sample markdown document designed to test the LlamaIndex document processing capabilities. It contains multiple sections with different types of content to verify proper parsing and chunking.

## Section 1: Basic Text

Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.

Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum.

## Section 2: Technical Content

### 2.1 Code Examples

Here's a Python code example:

```python
def process_document(file_path: str) -> list[dict]:
    """Process a document and return chunks."""
    with open(file_path, 'r') as f:
        content = f.read()
    return split_into_chunks(content)
```

### 2.2 Configuration

The system supports the following configuration options:

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| chunk_size | int | 1000 | Maximum chunk size in characters |
| chunk_overlap | int | 200 | Overlap between consecutive chunks |
| model | str | "gpt-4" | LLM model to use for processing |

## Section 3: Lists and Formatting

### Key Features

- **Document Parsing**: Supports PDF, DOCX, MD, TXT, and HTML files
- **Intelligent Chunking**: Respects sentence and paragraph boundaries
- **Metadata Extraction**: Preserves document structure information
- **Async Processing**: Handles large documents efficiently

### Processing Steps

1. Load the document from the file system
2. Parse the content based on file type
3. Split into semantic chunks
4. Generate embeddings for each chunk
5. Store in vector database

## Section 4: Conclusion

This document demonstrates the various content types that need to be properly parsed and chunked by the LlamaIndex integration. The goal is to verify that:

1. Headers are recognized and preserved
2. Code blocks remain intact
3. Tables are properly extracted
4. Lists maintain their structure
5. Paragraphs are split at appropriate boundaries

For more information, contact the development team.

---

*Last updated: February 2026*
