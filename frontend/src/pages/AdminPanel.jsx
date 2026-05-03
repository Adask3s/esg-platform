import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import "./AdminPanel.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const ALLOWED_EXTENSIONS = [".pdf", ".txt"];

function isSupportedUploadFile(file) {
  const lowerName = (file?.name || "").toLowerCase();
  return ALLOWED_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleDateString();
}

function normalizeText(value) {
  return value || "-";
}

function statusLabel(value) {
  if (!value) return "Active";
  const normalized = String(value).toLowerCase();
  if (normalized === "queued") return "Queued";
  if (normalized === "error") return "Error";
  if (normalized === "processing") return "Processing";
  if (normalized === "inactive") return "Inactive";
  return value;
}

export default function AdminPanel({ user }) {
  const navigate = useNavigate();
  const inputRef = useRef(null);
  const [dropActive, setDropActive] = useState(false);
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [knowledgeDocs, setKnowledgeDocs] = useState([]);
  const [userDocs, setUserDocs] = useState([]);
  const [embeddingStatus, setEmbeddingStatus] = useState(null);
  const [uploadResults, setUploadResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [reindexing, setReindexing] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [tag, setTag] = useState("general");
  const [documentType, setDocumentType] = useState("general");
  const [version, setVersion] = useState("1.0");

  const isAdmin = user?.role === "admin";

  const recentActivity = useMemo(() => {
    if (uploadResults.length) {
      return uploadResults.slice(0, 6).map((item) => ({
        key: item.task_id || item.filename,
        name: item.filename,
        status: item.status,
        detail: item.error || item.task_id || "Queued",
      }));
    }

    return knowledgeDocs.slice(0, 6).map((doc) => ({
      key: doc.id,
      name: doc.name,
      status: "indexed",
      detail: doc.tag || doc.document_type || "general",
    }));
  }, [knowledgeDocs, uploadResults]);

  const loadAdminData = async () => {
    if (!isAdmin) return;

    setLoading(true);
    setError("");

    try {
      const [knowledgeResponse, userResponse, statusResponse] = await Promise.all([
        fetch(`${API_URL}/documents/knowledge`, {
          headers: { Authorization: `Bearer ${user.token}` },
        }),
        fetch(`${API_URL}/documents`, {
          headers: { Authorization: `Bearer ${user.token}` },
        }),
        fetch(`${API_URL}/embeddings/status`, {
          headers: { Authorization: `Bearer ${user.token}` },
        }),
      ]);

      const knowledgeData = await knowledgeResponse.json();
      const userData = await userResponse.json();
      const statusData = await statusResponse.json();

      if (!knowledgeResponse.ok) {
        throw new Error(knowledgeData?.detail || "Failed to load knowledge documents.");
      }
      if (!userResponse.ok) {
        throw new Error(userData?.detail || "Failed to load user documents.");
      }
      if (!statusResponse.ok) {
        throw new Error(statusData?.detail || "Failed to load embeddings status.");
      }

      setKnowledgeDocs(Array.isArray(knowledgeData) ? knowledgeData : knowledgeData?.documents || []);
      setUserDocs((Array.isArray(userData) ? userData : userData?.documents || []).filter((doc) => doc.origin === "user" || !doc.origin));
      setEmbeddingStatus(statusData);
    } catch (err) {
      setError(err.message || "Failed to load admin data.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isAdmin) {
      loadAdminData();
    }
  }, [isAdmin, user?.token]);

  const preventDefaults = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };

  const handleDrop = (event) => {
    preventDefaults(event);
    setDropActive(false);
    const dropped = Array.from(event.dataTransfer?.files || []);
    if (!dropped.length) return;

    const supportedFiles = dropped.filter(isSupportedUploadFile).slice(0, 10);
    setSelectedFiles(supportedFiles);
    if (supportedFiles.length !== dropped.length) {
      setMessage("Only PDF and TXT files are supported here.");
    }
  };

  const handleFileChange = (event) => {
    const files = Array.from(event.target.files || []);

    const supportedFiles = files.filter(isSupportedUploadFile).slice(0, 10);
    setSelectedFiles(supportedFiles);
    if (supportedFiles.length !== files.length) {
      setMessage("Only PDF and TXT files are supported here.");
    }
  };

  const handleKnowledgeUpload = async () => {
    if (!selectedFiles.length) {
      setMessage("Select files first.");
      return;
    }

    setUploading(true);
    setError("");
    setMessage("");

    try {
      const formData = new FormData();
      selectedFiles.forEach((file) => {
        formData.append("files", file);
      });
      formData.append("tag", tag);
      formData.append("document_type", documentType);
      formData.append("version", version);

      const response = await fetch(`${API_URL}/knowledge/upload`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${user.token}`,
        },
        body: formData,
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.detail || "Upload failed.");
      }

      setUploadResults(Array.isArray(data?.results) ? data.results : []);
      setSelectedFiles([]);
      if (inputRef.current) {
        inputRef.current.value = "";
      }
      setMessage("Knowledge documents queued successfully.");
      await loadAdminData();
    } catch (err) {
      setError(err.message || "Upload error");
    } finally {
      setUploading(false);
    }
  };

  const generateAllEmbeddings = async () => {
    setReindexing(true);
    setError("");
    setMessage("");

    try {
      const response = await fetch(`${API_URL}/embeddings/generate-all?model=text-embedding-3-small`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${user.token}`,
        },
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.detail || "Failed to queue embedding generation.");
      }
      setMessage(`Embedding generation queued: ${data.task_id}`);
      await loadAdminData();
    } catch (err) {
      setError(err.message || "Embedding generation error");
    } finally {
      setReindexing(false);
    }
  };

  const generateDocumentEmbeddings = async (documentId) => {
    if (!documentId) return;

    setError("");
    try {
      const response = await fetch(`${API_URL}/embeddings/generate-for-document`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${user.token}`,
        },
        body: JSON.stringify({ document_id: documentId, model: "text-embedding-3-small", table_name: "knowledge_chunks" }),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.detail || "Failed to queue document embeddings.");
      }
      setMessage(`Embeddings queued for ${documentId}`);
    } catch (err) {
      setError(err.message || "Embedding error");
    }
  };

  if (!isAdmin) {
    return (
      <div className="admin-shell">
        <div className="admin-card">
          <h1>Admin Panel</h1>
          <p>This view is available for admin users only.</p>
          <button type="button" className="primary-btn" onClick={() => navigate("/")}>Back to Dashboard</button>
        </div>
      </div>
    );
  }

  return (
    <div className="admin-shell">
      <header className="admin-header">
        <div className="admin-brand-row">
          <span className="admin-brand-icon">E</span>
          <div>
            <h1>Admin Panel</h1>
            <p>Manage ESG documentation, indexing and embeddings.</p>
          </div>
        </div>
        <div className="admin-header-meta">
          <div className="admin-header-stat">
            <span>{knowledgeDocs.length}</span>
            <small>Standards</small>
          </div>
          <div className="admin-header-stat">
            <span>{userDocs.length}</span>
            <small>Uploads</small>
          </div>
          <div className="admin-header-stat is-accent">
            <span>{embeddingStatus?.coverage_percent ?? 0}%</span>
            <small>Coverage</small>
          </div>
          <button type="button" className="admin-back-btn" onClick={() => navigate("/")}>Back to Dashboard</button>
        </div>
      </header>

      {error ? <div className="admin-alert is-error">{error}</div> : null}
      {message ? <div className="admin-alert is-success">{message}</div> : null}

      <main className="admin-grid">
        <section className="admin-card admin-upload-card">
          <div className="admin-card-title-row">
            <h2>Upload &amp; Index Documents</h2>
            <button type="button" className="admin-secondary-btn" onClick={generateAllEmbeddings} disabled={reindexing}>
              {reindexing ? "Queueing..." : "Generate All Embeddings"}
            </button>
          </div>

          <div
            className={`admin-dropzone ${dropActive ? "is-active" : ""}`}
            onDragOver={(event) => {
              preventDefaults(event);
              setDropActive(true);
            }}
            onDragEnter={(event) => {
              preventDefaults(event);
              setDropActive(true);
            }}
            onDragLeave={(event) => {
              preventDefaults(event);
              setDropActive(false);
            }}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
          >
            <div className="admin-dropzone-icon">⇪</div>
            <strong>Drag &amp; drop files here</strong>
            <span>Supports PDF and TXT files.</span>
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".pdf,.txt,application/pdf,text/plain"
              className="admin-hidden-input"
              onChange={handleFileChange}
            />
          </div>

          <div className="admin-form-grid">
            <label>
              Standard Category
              <input value={tag} onChange={(event) => setTag(event.target.value)} placeholder="general / environmental / social / governance" />
            </label>
            <label>
              Document Type
              <input value={documentType} onChange={(event) => setDocumentType(event.target.value)} placeholder="standard / report / policy" />
            </label>
            <label>
              Version
              <input value={version} onChange={(event) => setVersion(event.target.value)} placeholder="1.0" />
            </label>
          </div>

          <div className="admin-upload-actions">
            <button type="button" className="primary-btn admin-upload-btn" onClick={handleKnowledgeUpload} disabled={uploading}>
              {uploading ? "Uploading..." : "Start Indexing"}
            </button>
            <button type="button" className="admin-secondary-btn" onClick={() => setSelectedFiles([])} disabled={!selectedFiles.length}>
              Clear Selection
            </button>
          </div>

          <div className="admin-selected-files">
            {selectedFiles.length ? selectedFiles.map((file) => <span key={`${file.name}-${file.lastModified}`}>{file.name}</span>) : <p>No files selected</p>}
          </div>
        </section>

        <section className="admin-card admin-knowledge-card">
          <div className="admin-card-title-row">
            <h2>Global ESG Standards in Knowledge Base</h2>
            <div className="admin-stat-mini">
              <span>{embeddingStatus?.coverage_percent ?? 0}%</span>
              <small>coverage</small>
            </div>
          </div>

          <div className="admin-table">
            <div className="admin-row admin-row-head">
              <span>Standard Name</span>
              <span>Last Updated</span>
              <span>Type</span>
              <span>Status</span>
              <span>Action</span>
            </div>
            {loading ? (
              <div className="admin-empty">Loading knowledge base...</div>
            ) : knowledgeDocs.length ? (
              knowledgeDocs.map((doc) => (
                <div className="admin-row" key={doc.id}>
                  <span>{normalizeText(doc.name)}</span>
                  <span>{formatDate(doc.created_at)}</span>
                  <span>{normalizeText(doc.document_type || doc.file_type || doc.version)}</span>
                  <span><span className="admin-pill is-active">Active</span></span>
                  <span>
                    <button type="button" className="admin-link-btn" onClick={() => generateDocumentEmbeddings(doc.id)}>
                      Reindex
                    </button>
                  </span>
                </div>
              ))
            ) : (
              <div className="admin-empty">No knowledge documents available.</div>
            )}
          </div>
        </section>

        <section className="admin-card admin-activity-card">
          <h2>Recent Upload Activity</h2>
          <div className="admin-table compact">
            <div className="admin-row admin-row-head">
              <span>Filename</span>
              <span>Status</span>
              <span>Details</span>
            </div>
            {recentActivity.length ? (
              recentActivity.map((item) => (
                <div className="admin-row" key={item.key}>
                  <span>{normalizeText(item.name)}</span>
                  <span>
                    <span className={`admin-pill is-${String(item.status).toLowerCase()}`}>{statusLabel(item.status)}</span>
                  </span>
                  <span>{normalizeText(item.detail)}</span>
                </div>
              ))
            ) : (
              <div className="admin-empty">No recent activity yet.</div>
            )}
          </div>
        </section>

        <section className="admin-card admin-user-card">
          <h2>User Upload Monitor</h2>
          <div className="admin-table compact">
            <div className="admin-row admin-row-head">
              <span>Document</span>
              <span>Category</span>
              <span>Uploaded At</span>
              <span>Action</span>
            </div>
            {userDocs.length ? (
              userDocs.slice(0, 12).map((doc) => (
                <div className="admin-row" key={doc.id}>
                  <span>{normalizeText(doc.name || doc.filename)}</span>
                  <span>{normalizeText(doc.tag)}</span>
                  <span>{formatDate(doc.created_at)}</span>
                  <span>
                    <button type="button" className="admin-link-btn" onClick={() => navigate("/")}>Open</button>
                  </span>
                </div>
              ))
            ) : (
              <div className="admin-empty">No user uploads available.</div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
