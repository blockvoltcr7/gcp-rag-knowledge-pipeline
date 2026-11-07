import React, { useState } from 'react';
import { FileText, Video, Music, Image, Database, Cloud, Cpu, ArrowRight, ArrowDown, Zap, Box, Layers, GitBranch, CheckCircle, AlertCircle, Clock, ChevronDown, ChevronRight } from 'lucide-react';

const RAGProcessorVisualization = () => {
  const [activeStage, setActiveStage] = useState(null);
  const [expandedSection, setExpandedSection] = useState('architecture');

  const stages = [
    { id: 'upload', name: 'File Upload', icon: Cloud, color: 'bg-blue-500', description: 'Files uploaded to Google Cloud Storage' },
    { id: 'route', name: 'Content Router', icon: GitBranch, color: 'bg-purple-500', description: 'Detects file type and routes to appropriate processor' },
    { id: 'process', name: 'Content Processing', icon: Cpu, color: 'bg-orange-500', description: 'Type-specific processing (transcription, chunking, analysis)' },
    { id: 'embed', name: 'Embedding Generation', icon: Zap, color: 'bg-yellow-500', description: 'Generates text & multimodal embeddings via Gemini' },
    { id: 'store', name: 'Vector Storage', icon: Database, color: 'bg-green-500', description: 'Stores chunks with embeddings in PostgreSQL + pgvector' },
  ];

  const contentTypes = [
    { type: 'Document', icon: FileText, extensions: ['.pdf', '.docx', '.xlsx', '.pptx', '.txt', '.md', '.html'], color: 'text-blue-600', bgColor: 'bg-blue-50' },
    { type: 'Video', icon: Video, extensions: ['.mp4', '.avi', '.mov', '.mkv', '.webm'], color: 'text-red-600', bgColor: 'bg-red-50' },
    { type: 'Audio', icon: Music, extensions: ['.mp3', '.wav', '.m4a', '.flac', '.ogg'], color: 'text-green-600', bgColor: 'bg-green-50' },
    { type: 'Image', icon: Image, extensions: ['.jpg', '.png', '.webp', '.svg', '.heic'], color: 'text-purple-600', bgColor: 'bg-purple-50' },
  ];

  const techStack = [
    { name: 'FastAPI', desc: 'Web Framework' },
    { name: 'Google Cloud Run', desc: 'Serverless Container' },
    { name: 'Google Cloud Storage', desc: 'File Storage' },
    { name: 'Gemini AI', desc: 'Text Embeddings' },
    { name: 'Vertex AI', desc: 'Multimodal Embeddings' },
    { name: 'PostgreSQL + pgvector', desc: 'Vector Database' },
    { name: 'Docling', desc: 'Document Processing' },
    { name: 'Pydantic', desc: 'Data Validation' },
  ];

  const processingStages = [
    { stage: 'pending', icon: Clock, color: 'text-gray-500' },
    { stage: 'downloading', icon: Cloud, color: 'text-blue-500' },
    { stage: 'processing', icon: Cpu, color: 'text-orange-500' },
    { stage: 'embedding', icon: Zap, color: 'text-yellow-500' },
    { stage: 'storing', icon: Database, color: 'text-green-500' },
    { stage: 'completed', icon: CheckCircle, color: 'text-emerald-500' },
    { stage: 'error', icon: AlertCircle, color: 'text-red-500' },
  ];

  const Section = ({ title, id, children }) => (
    <div className="mb-6 bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
      <button
        onClick={() => setExpandedSection(expandedSection === id ? null : id)}
        className="w-full px-6 py-4 flex items-center justify-between bg-gray-50 hover:bg-gray-100 transition-colors"
      >
        <h2 className="text-lg font-semibold text-gray-800">{title}</h2>
        {expandedSection === id ? (
          <ChevronDown className="w-5 h-5 text-gray-500" />
        ) : (
          <ChevronRight className="w-5 h-5 text-gray-500" />
        )}
      </button>
      {expandedSection === id && <div className="p-6">{children}</div>}
    </div>
  );

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-3 mb-4">
            <div className="p-3 bg-gradient-to-br from-blue-500 to-purple-600 rounded-xl shadow-lg">
              <Layers className="w-8 h-8 text-white" />
            </div>
            <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
              RAG Processor
            </h1>
          </div>
          <p className="text-gray-600 max-w-2xl mx-auto">
            A document processing and embedding service that transforms various file types into searchable vector embeddings for Retrieval-Augmented Generation
          </p>
        </div>

        {/* Architecture Overview */}
        <Section title="🏗️ Processing Pipeline" id="architecture">
          <div className="flex flex-wrap justify-center items-center gap-2 md:gap-4">
            {stages.map((stage, index) => (
              <React.Fragment key={stage.id}>
                <div
                  className={`relative group cursor-pointer transition-all duration-300 ${
                    activeStage === stage.id ? 'scale-110' : 'hover:scale-105'
                  }`}
                  onMouseEnter={() => setActiveStage(stage.id)}
                  onMouseLeave={() => setActiveStage(null)}
                >
                  <div className={`${stage.color} p-4 rounded-xl shadow-lg`}>
                    <stage.icon className="w-8 h-8 text-white" />
                  </div>
                  <div className="mt-2 text-center">
                    <p className="text-sm font-medium text-gray-700">{stage.name}</p>
                  </div>
                  {activeStage === stage.id && (
                    <div className="absolute top-full mt-2 left-1/2 transform -translate-x-1/2 bg-gray-900 text-white text-xs p-2 rounded-lg shadow-xl w-48 z-10">
                      {stage.description}
                    </div>
                  )}
                </div>
                {index < stages.length - 1 && (
                  <ArrowRight className="w-6 h-6 text-gray-400 hidden md:block" />
                )}
              </React.Fragment>
            ))}
          </div>
        </Section>

        {/* Content Types */}
        <Section title="📁 Supported Content Types" id="content">
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {contentTypes.map((content) => (
              <div
                key={content.type}
                className={`${content.bgColor} rounded-xl p-4 border border-gray-200 hover:shadow-md transition-shadow`}
              >
                <div className="flex items-center gap-3 mb-3">
                  <content.icon className={`w-6 h-6 ${content.color}`} />
                  <h3 className={`font-semibold ${content.color}`}>{content.type}</h3>
                </div>
                <div className="flex flex-wrap gap-1">
                  {content.extensions.map((ext) => (
                    <span
                      key={ext}
                      className="px-2 py-0.5 bg-white rounded text-xs font-mono text-gray-600"
                    >
                      {ext}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Section>

        {/* Processing Flow */}
        <Section title="⚡ Processing Flow Detail" id="flow">
          <div className="bg-gray-900 rounded-xl p-6 text-sm font-mono overflow-x-auto">
            <div className="space-y-2">
              <div className="text-green-400">// 1. Cloud Run Job triggered with environment variables</div>
              <div className="text-gray-300">PROCESSING_JOB_ID, GCS_FILE_PATH, USER_ID, PROGRAM_ID</div>
              <div className="h-2"></div>
              <div className="text-green-400">// 2. Validate program ownership</div>
              <div className="text-blue-300">await db.verify_program_ownership(program_id, user_id)</div>
              <div className="h-2"></div>
              <div className="text-green-400">// 3. Download file from GCS</div>
              <div className="text-blue-300">local_file = await gcs.download_to_temp(gcs_path)</div>
              <div className="h-2"></div>
              <div className="text-green-400">// 4. Route based on content type</div>
              <div className="text-purple-300">content_type = content_router.detect(file_path)</div>
              <div className="text-yellow-300">
                {"switch (content_type) {"}
              </div>
              <div className="pl-4 text-gray-300">
                <div>case "document": → document_processing_service</div>
                <div>case "video": → video_processing_service</div>
                <div>case "audio": → audio_processing_service</div>
                <div>case "image": → image_processing_service</div>
              </div>
              <div className="text-yellow-300">{"}"}</div>
              <div className="h-2"></div>
              <div className="text-green-400">// 5. Generate embeddings</div>
              <div className="text-blue-300">text_embedding = gemini.embed(chunk.text) // 3072d</div>
              <div className="text-blue-300">multimodal_embedding = vertex_ai.embed(media) // 1408d</div>
              <div className="h-2"></div>
              <div className="text-green-400">// 6. Store in pgvector database</div>
              <div className="text-blue-300">await db.store_chunks(chunks, embeddings)</div>
            </div>
          </div>
        </Section>

        {/* Embedding Models */}
        <Section title="🧠 Embedding Models" id="models">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="bg-gradient-to-br from-blue-50 to-indigo-100 rounded-xl p-6 border border-blue-200">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 bg-blue-500 rounded-lg">
                  <FileText className="w-5 h-5 text-white" />
                </div>
                <h3 className="font-semibold text-blue-800">Text Embeddings</h3>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600">Model:</span>
                  <span className="font-mono text-blue-700">gemini-embedding-001</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Dimensions:</span>
                  <span className="font-semibold text-blue-700">3072</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Task Type:</span>
                  <span className="text-blue-700">RETRIEVAL_DOCUMENT</span>
                </div>
              </div>
            </div>
            <div className="bg-gradient-to-br from-purple-50 to-pink-100 rounded-xl p-6 border border-purple-200">
              <div className="flex items-center gap-3 mb-4">
                <div className="p-2 bg-purple-500 rounded-lg">
                  <Box className="w-5 h-5 text-white" />
                </div>
                <h3 className="font-semibold text-purple-800">Multimodal Embeddings</h3>
              </div>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600">Model:</span>
                  <span className="font-mono text-purple-700">multimodalembedding@001</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Dimensions:</span>
                  <span className="font-semibold text-purple-700">1408</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Supports:</span>
                  <span className="text-purple-700">Images, Videos</span>
                </div>
              </div>
            </div>
          </div>
        </Section>

        {/* Job Status Flow */}
        <Section title="📊 Processing Job Status" id="status">
          <div className="flex flex-wrap justify-center gap-3">
            {processingStages.map((item, index) => (
              <React.Fragment key={item.stage}>
                <div className="flex items-center gap-2 px-4 py-2 bg-white rounded-lg border border-gray-200 shadow-sm">
                  <item.icon className={`w-5 h-5 ${item.color}`} />
                  <span className="text-sm font-medium text-gray-700 capitalize">{item.stage}</span>
                </div>
                {index < processingStages.length - 1 && index !== 5 && (
                  <ArrowRight className="w-5 h-5 text-gray-300 self-center" />
                )}
              </React.Fragment>
            ))}
          </div>
        </Section>

        {/* Tech Stack */}
        <Section title="🛠️ Technology Stack" id="tech">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {techStack.map((tech) => (
              <div
                key={tech.name}
                className="bg-white rounded-lg p-4 border border-gray-200 hover:border-blue-300 hover:shadow-md transition-all"
              >
                <h4 className="font-semibold text-gray-800">{tech.name}</h4>
                <p className="text-xs text-gray-500 mt-1">{tech.desc}</p>
              </div>
            ))}
          </div>
        </Section>

        {/* Database Schema */}
        <Section title="💾 Database Schema" id="database">
          <div className="bg-gray-900 rounded-xl p-6 font-mono text-sm overflow-x-auto">
            <div className="text-purple-400 mb-4">-- PostgreSQL with pgvector extension</div>
            <div className="space-y-4">
              <div>
                <div className="text-green-400">CREATE TABLE ai.document_chunks (</div>
                <div className="pl-4 text-gray-300">
                  <div>id UUID PRIMARY KEY,</div>
                  <div>content TEXT,</div>
                  <div>chunk_index INTEGER,</div>
                  <div className="text-blue-300">text_embedding VECTOR(3072),</div>
                  <div className="text-purple-300">multimodal_embedding VECTOR(1408),</div>
                  <div>metadata JSONB,</div>
                  <div>context TEXT,</div>
                  <div>document_id UUID REFERENCES ai.documents,</div>
                  <div>program_id UUID,</div>
                  <div>creator_id UUID,</div>
                  <div>created_at TIMESTAMPTZ</div>
                </div>
                <div className="text-green-400">);</div>
              </div>
            </div>
          </div>
        </Section>

        {/* Footer */}
        <div className="text-center text-gray-500 text-sm mt-8">
          <p>RAG Processor v0.1.0 • Built for scalable document processing on Google Cloud</p>
        </div>
      </div>
    </div>
  );
};

export default RAGProcessorVisualization;
