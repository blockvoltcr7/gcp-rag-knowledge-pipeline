# LlamaIndex Research Report: Document Processing for RAG Processor

## Executive Summary

**Verdict: YES, it is feasible to integrate LlamaIndex** as an alternative or complement to Docling for processing Word documents, Markdown files, and PDFs in your RAG processor.

LlamaIndex offers multiple document parsing strategies that can address Docling's limitations while maintaining compatibility with your existing Vertex AI/Gemini embedding pipeline.

---

## 1. Known Docling Limitations (Validating Your Concerns)

Based on research, Docling has documented issues that align with your experience:

| Issue | Description |
|-------|-------------|
| **Large PDF Hangs** | 3000+ page PDFs can hang indefinitely (8+ hours) even with timeout configs |
| **OCR Limitations** | Scanned documents and image-based PDFs produce poor results |
| **DOCX Image Support** | Image description option not available for DOCX/PPTX files |
| **Azure Crashes** | PDF parsing can crash the function host in Azure deployments |
| **Memory Intensive** | Requires GPU for reasonable performance on complex documents |
| **Complex Layouts** | Multi-column layouts, sidebars, and non-standard formatting cause issues |

---

## 2. LlamaIndex Document Parsing Options

### Option A: SimpleDirectoryReader + File Readers (Recommended for Your Case)

**Package:** `llama-index-readers-file`

```python
pip install llama-index-readers-file
```

**Available Readers:**
- `DocxReader` - Word documents (.docx)
- `MarkdownReader` - Markdown files (.md)
- `PDFReader` - Basic PDF parsing
- `PyMuPDFReader` - Alternative PDF reader with better text extraction
- `UnstructuredReader` - Leverages Unstructured.io for complex documents

**Usage Example:**
```python
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import DocxReader, PDFReader, MarkdownReader

# Create file extractors for multiple types
file_extractor = {
    ".pdf": PDFReader(),
    ".docx": DocxReader(),
    ".md": MarkdownReader(),
}

# Load documents (sync)
documents = SimpleDirectoryReader(
    input_dir="./data",
    file_extractor=file_extractor
).load_data()

# Or async loading
documents = await reader.aload_data()
```

**Pros:**
- Lightweight, no external API calls
- Works offline
- Simple integration
- Supports async via `aload_data()`

**Cons:**
- Less sophisticated than LlamaParse for complex documents
- Basic table extraction

---

### Option B: LlamaParse (Best Quality, Cloud-Based)

**Package:** `llama-parse`

```python
pip install llama-parse
```

**Features:**
- GenAI-native document parsing using VLMs
- Excellent table recognition
- Handles complex layouts, charts, images
- Supports: PDF, DOCX, PPTX, XLSX, HTML, JPEG, XML, EPUB

**Pricing:**
- Free tier: 1,000 pages/day
- Paid: 7,000 pages/week free + $0.003/additional page

**Parsing Tiers:**
| Tier | Best For |
|------|----------|
| `fast` | Simple text-heavy documents |
| `cost_effective` | Balanced speed/cost |
| `agentic` | Documents with images/diagrams |
| `agentic_plus` | Complex layouts, tables, visual structure |

**Usage Example:**
```python
from llama_parse import LlamaParse
from llama_index.core import SimpleDirectoryReader

parser = LlamaParse(
    api_key="llx-...",
    result_type="markdown",
    parsing_instruction="Extract all text and tables accurately"
)

file_extractor = {".pdf": parser, ".docx": parser}
documents = SimpleDirectoryReader(
    "./data", file_extractor=file_extractor
).load_data()
```

**Pros:**
- Highest accuracy for complex documents
- Excellent table extraction (benchmark: 97.9% accuracy)
- Consistent ~6 second processing regardless of document size

**Cons:**
- Requires API calls (cloud dependency)
- Cost for high-volume usage
- Not suitable for sensitive/private documents

---

### Option C: Hybrid Approach (Recommended)

Combine multiple parsers based on file complexity:

```python
from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import DocxReader, MarkdownReader, PDFReader
from llama_parse import LlamaParse

# Use LlamaParse for PDFs (complex), simple readers for others
llama_parser = LlamaParse(api_key="...", result_type="markdown")

file_extractor = {
    ".pdf": llama_parser,      # Best for complex PDFs
    ".docx": DocxReader(),     # Simple DOCX handling
    ".md": MarkdownReader(),   # Native markdown support
}

reader = SimpleDirectoryReader("./data", file_extractor=file_extractor)
documents = await reader.aload_data()
```

---

## 3. Integration with Your RAG Processor

### Compatibility Assessment

| Requirement | LlamaIndex Support |
|-------------|-------------------|
| Python 3.10-3.12 | ✅ Supports `<4.0, >=3.9` |
| Async operations | ✅ `aload_data()`, `aload_file()` |
| Vertex AI embeddings | ✅ `llama-index-embeddings-vertex` |
| Gemini embeddings | ✅ `llama-index-embeddings-gemini` |
| Custom chunking | ✅ Multiple node parsers available |
| PostgreSQL/pgvector | ✅ Vector store integrations |

### Proposed Architecture Change

```
Current Flow:
┌─────────┐    ┌─────────┐    ┌──────────┐    ┌──────────┐
│  GCS    │───▶│ Docling │───▶│ Chunker  │───▶│ Embedder │
└─────────┘    └─────────┘    └──────────┘    └──────────┘

Proposed Flow:
┌─────────┐    ┌─────────────────────────┐    ┌──────────┐
│  GCS    │───▶│  Content Router         │───▶│ Embedder │
└─────────┘    │  ├─ PDF → LlamaParse    │    │ (Gemini) │
               │  ├─ DOCX → DocxReader   │    └──────────┘
               │  ├─ MD → MarkdownReader │
               │  └─ Video/Audio/Image   │
               │      → (existing flow)  │
               └─────────────────────────┘
```

### Sample Integration Code

```python
# rag_processor/services/llamaindex_document_service.py

from llama_index.core import SimpleDirectoryReader
from llama_index.readers.file import DocxReader, MarkdownReader
from llama_index.core.node_parser import SentenceSplitter
import structlog

logger = structlog.get_logger(__name__)

class LlamaIndexDocumentService:
    """Alternative document processing using LlamaIndex."""

    def __init__(self, use_llamaparse: bool = False, llamaparse_api_key: str = None):
        self.file_extractor = {}

        if use_llamaparse and llamaparse_api_key:
            from llama_parse import LlamaParse
            self.file_extractor[".pdf"] = LlamaParse(
                api_key=llamaparse_api_key,
                result_type="markdown"
            )
        else:
            from llama_index.readers.file import PDFReader
            self.file_extractor[".pdf"] = PDFReader()

        self.file_extractor[".docx"] = DocxReader()
        self.file_extractor[".md"] = MarkdownReader()

        # Chunker with same settings as your current config
        self.splitter = SentenceSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )

    async def process_document(self, file_path: str) -> list[dict]:
        """Process a document and return chunks."""
        reader = SimpleDirectoryReader(
            input_files=[file_path],
            file_extractor=self.file_extractor
        )

        # Async document loading
        documents = await reader.aload_data()

        # Chunk the documents
        nodes = self.splitter.get_nodes_from_documents(documents)

        chunks = []
        for idx, node in enumerate(nodes):
            chunks.append({
                "text": node.text,
                "metadata": {
                    "chunk_index": idx,
                    "content_type": "document",
                    "doc_type": file_path.split(".")[-1],
                    **node.metadata
                }
            })

        logger.info(
            "Document processed with LlamaIndex",
            file_path=file_path,
            chunk_count=len(chunks)
        )

        return chunks
```

---

## 4. Chunking Strategies Available

LlamaIndex provides sophisticated chunking options:

| Splitter | Description | Best For |
|----------|-------------|----------|
| `SentenceSplitter` | Respects sentence boundaries | General documents |
| `TokenTextSplitter` | Consistent token counts | LLM context limits |
| `SemanticSplitter` | Uses embedding similarity | Topic-coherent chunks |
| `MarkdownNodeParser` | Header-based splitting | Markdown files |
| `HTMLNodeParser` | HTML-aware splitting | Web content |
| `CodeSplitter` | Respects code structure | Source files |

**Example with Semantic Chunking:**
```python
from llama_index.core.node_parser import SemanticSplitterNodeParser
from llama_index.embeddings.gemini import GeminiEmbedding

embed_model = GeminiEmbedding(model_name="models/embedding-001")
splitter = SemanticSplitterNodeParser(
    buffer_size=1,
    breakpoint_percentile_threshold=95,
    embed_model=embed_model
)
```

---

## 5. Vertex AI / Gemini Embedding Integration

LlamaIndex has native support for your existing embedding infrastructure:

```python
# Option 1: Vertex AI Text Embeddings
from llama_index.embeddings.vertex import VertexTextEmbedding

embed_model = VertexTextEmbedding(
    model_name="text-embedding-005",
    project="your-project-id"
)

# Option 2: Gemini Embeddings
from llama_index.embeddings.gemini import GeminiEmbedding

embed_model = GeminiEmbedding(
    model_name="models/text-embedding-004",
    api_key="your-api-key"
)
```

---

## 6. Recommendations

### Short-term (Quick Win)
1. **Replace Docling for DOCX and MD files** with LlamaIndex's `DocxReader` and `MarkdownReader`
2. Keep existing Docling for PDFs initially
3. Test on your problematic documents

### Medium-term (Better Quality)
1. **Add LlamaParse for complex PDFs** that fail with Docling
2. Implement fallback logic: try Docling first, fallback to LlamaParse
3. Add monitoring to track which parser succeeds

### Long-term (Full Migration)
1. **Replace Docling entirely** with LlamaIndex ecosystem
2. Use hybrid approach: LlamaParse for PDFs, simple readers for others
3. Consider semantic chunking for better retrieval quality

---

## 7. Installation Requirements

Add to `pyproject.toml`:

```toml
[project]
dependencies = [
    # ... existing dependencies ...

    # LlamaIndex core
    "llama-index-core>=0.14.0",

    # File readers
    "llama-index-readers-file>=0.4.0",

    # Optional: LlamaParse for complex PDFs
    "llama-parse>=0.6.0",

    # Optional: Vertex AI embeddings integration
    "llama-index-embeddings-vertex>=0.3.0",
]
```

---

## 8. Benchmark Comparison (2025 Data)

| Parser | Simple Tables | Complex Tables | Processing Speed | Cost |
|--------|--------------|----------------|------------------|------|
| **Docling** | 100% | 97.9% | Varies (GPU needed) | Free |
| **LlamaParse** | 98% | 95%+ | ~6 sec consistent | $0.003/page |
| **Unstructured** | 100% | 75% | Moderate | Free/Paid |
| **PDFReader** | Basic | Poor | Fast | Free |

---

## Sources

- [LlamaIndex Loading Data Documentation](https://developers.llamaindex.ai/python/framework/module_guides/loading/)
- [SimpleDirectoryReader Documentation](https://developers.llamaindex.ai/python/framework/module_guides/loading/simpledirectoryreader/)
- [LlamaParse Getting Started](https://developers.llamaindex.ai/python/cloud/llamaparse/getting_started/)
- [llama-index-readers-file on PyPI](https://pypi.org/project/llama-index-readers-file/)
- [LlamaIndex Node Parsers](https://developers.llamaindex.ai/python/framework/module_guides/loading/node_parsers/modules/)
- [Docling GitHub Issues](https://github.com/docling-project/docling/issues)
- [PDF Data Extraction Benchmark 2025](https://procycons.com/en/blogs/pdf-data-extraction-benchmark/)
- [LlamaIndex Vertex AI Integration](https://docs.llamaindex.ai/en/stable/examples/llm/vertex/)
