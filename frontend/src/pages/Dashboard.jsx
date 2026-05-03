import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import "../App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const ALLOWED_EXTENSIONS = [".pdf", ".txt"];

function isSupportedUploadFile(file) {
  const lowerName = (file?.name || "").toLowerCase();
  return ALLOWED_EXTENSIONS.some((extension) => lowerName.endsWith(extension));
}

export default function Dashboard({ user, onLogout }) {
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef(null);
  const [message, setMessage] = useState("");
  const [documentsError, setDocumentsError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isCompleted, setIsCompleted] = useState(false);
  const [perFileTags, setPerFileTags] = useState({});
  const [openTagDropdownFor, setOpenTagDropdownFor] = useState(null);
  const [userDocuments, setUserDocuments] = useState([]);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [uploadResults, setUploadResults] = useState([]);
  const navigate = useNavigate();

  const isLoggedIn = !!user?.token;

  const loadUserDocuments = () => {
    setDocumentsError("");
    return fetch(`${API_URL}/documents/mine`, {
      method: "GET",
      headers: { Authorization: `Bearer ${user.token}` },
    })
      .then(async (res) => {
        const data = await res.json().catch(() => null);
        if (!res.ok) {
          throw new Error(data?.detail || `Failed to load documents (${res.status})`);
        }
        return data;
      })
      .then((data) => {
        const docs = Array.isArray(data) ? data : data?.documents || [];
        setUserDocuments(docs.filter((doc) => doc.origin === "user" || !doc.origin));
      })
      .catch((err) => {
        console.error("Failed to fetch documents:", err);
        setUserDocuments([]);
        setDocumentsError(err.message || "Failed to load documents");
      })
      .finally(() => setLoadingDocuments(false));
  };

  const deleteUserDocument = async (documentId) => {
    if (!documentId) return;
    const confirmed = window.confirm("Delete this document and all related chunks?");
    if (!confirmed) return;

    try {
      setMessage("");
      const response = await fetch(`${API_URL}/user/documents/delete`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${user.token}`,
        },
        body: JSON.stringify({ document_id: documentId }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.detail || "Failed to delete document.");
      }

      await loadUserDocuments();
      setMessage("Document deleted successfully.");
    } catch (err) {
      setMessage(err.message || "Delete error");
    }
  };

  useEffect(() => {
    if (isLoggedIn) {
      setLoadingDocuments(true);
      loadUserDocuments();
    }
  }, [isLoggedIn, user?.token]);

  function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  function handleDragOver(e) {
    preventDefaults(e);
    setIsDragging(true);
  }

  function handleDragLeave(e) {
    preventDefaults(e);
    setIsDragging(false);
  }

  function handleDrop(e) {
    preventDefaults(e);
    setIsDragging(false);
    const dropped = Array.from(e.dataTransfer?.files || []);
    if (!dropped.length) return;

    const supportedFiles = dropped.filter(isSupportedUploadFile).slice(0, 10);
    setSelectedFiles(supportedFiles);
    if (supportedFiles.length !== dropped.length) {
      setMessage("Only PDF and TXT files are supported here.");
    }
  }

  useEffect(() => {
    const prevent = (e) => {
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("dragover", prevent);
    window.addEventListener("drop", prevent);
    return () => {
      window.removeEventListener("dragover", prevent);
      window.removeEventListener("drop", prevent);
    };
  }, []);

  function handleFileChange(event) {
    const files = Array.from(event.target.files || []);

    const supportedFiles = files.filter(isSupportedUploadFile).slice(0, 10);
    setSelectedFiles(supportedFiles);
    if (supportedFiles.length !== files.length) {
      setMessage("Only PDF and TXT files are supported here.");
    }
  }

  async function uploadFiles() {
    if (!selectedFiles.length) {
      setMessage("Please select files");
      return;
    }

    try {
      setIsLoading(true);
      setIsCompleted(false);
      setUploadResults([]);
      
      const results = [];
      for (const f of selectedFiles) {
        const formdata = new FormData();
        formdata.append("file", f);
        const tag = perFileTags[f.name] || ""; 
        if (tag) {
          formdata.append("tag", tag);
        }

        const response = await fetch(`${API_URL}/user/documents/upload`, {
          method: "POST",
          body: formdata,
          headers: { Authorization: `Bearer ${user.token}` },
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data?.detail || "Upload error");

        results.push({
          filename: data?.filename || f.name,
          status: data?.status || "queued",
          task_id: data?.task_id || null,
          message: data?.message || "Queued",
        });
      }

      setUploadResults(results);
      setMessage("Files processed successfully");
      setIsCompleted(true);
      setTimeout(() => {
        loadUserDocuments();
      }, 2000);
    } catch (err) {
      setMessage(err.message || "Upload error");
    } finally {
      setIsLoading(false);
    }
  }

  const openAiReport = (doc) => {
    navigate("/aireports", { state: { doc: doc || null } });
  };

  return (
    <div className="page">
      <header className="topbar">
        <div className="brand">
          E<span>S</span>G
        </div>
        <nav className="nav">
          {isLoggedIn ? (
            <>
              {user?.role === "admin" ? <a href="/admin">Admin Panel</a> : null}
              <a href="/contact">Contact us</a>
              <button 
                onClick={onLogout} 
                style={{ background: "none", border: "none", color: "#f6f1e7", cursor: "pointer", fontSize: "13px" }}
              >
                Logout
              </button>
            </>
          ) : (
            <>
              <a href="/contact">Contact us</a>
              <a href="/login">Login</a>
              <a href="/signup">Sign up</a>
            </>
          )}
        </nav>
      </header>

      <main className="content">
        <section className="hero">
          <div className="hero-text">
            <h1>
              Environmental
              <br />
              Social
              <br />
              Governance
            </h1>
            {!isLoggedIn && (
              <a href="/signup" style={{ textDecoration: "none" }}>
                <button className="primary-btn">Register</button>
              </a>
            )}
          </div>
          <div className="hero-logo" aria-hidden="true">
            <div className="logo-ring ring-left" />
            <div className="logo-ring ring-right" />
          </div>
        </section>

        {isLoggedIn && (
          <section className="upload-section">
            <div
              className={`dropzone ${isDragging ? "dragging" : ""}`}
              onDragOver={handleDragOver}
              onDragEnter={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => inputRef.current?.click()}
            >
              <div className="dropzone-plus">+</div>
              <p>Drop files here (max 10) or click to select</p>
              <input
                ref={inputRef}
                id="plik"
                type="file"
                className="miejsce"
                accept=".pdf,.txt,application/pdf,text/plain"
                multiple
                onChange={handleFileChange}
                style={{ display: "none" }}
              />
            </div>

            <button className="primary-btn" onClick={uploadFiles}>
              Submit
            </button>

            {uploadResults.length > 0 && (
              <div className="upload-results">
                {uploadResults.map((result) => (
                  <div className="upload-result-row" key={`${result.filename}-${result.task_id || result.status}`}>
                    <strong>{result.filename}</strong>
                    <span>{result.status}</span>
                    {result.task_id ? <small>Task: {result.task_id}</small> : null}
                  </div>
                ))}
              </div>
            )}

            {selectedFiles.length > 0 && (
              <div className="selected-files-list">
                {selectedFiles.map((file) => {
                  const fileName = file.name;

                  return (
                    <div className="file-row" key={`${fileName}-${file.lastModified}`}>
                      <div className="file-chip">
                        <span className="file-chip-icon">📄</span>
                        <span>{fileName}</span>
                      </div>
                      <div className="file-actions">
                        <div className="tag-pill-wrap">
                          {perFileTags[fileName] ? (
                            <span className="tag-pill">{perFileTags[fileName].toUpperCase()}</span>
                          ) : (
                            <span className="tag-pill is-empty">No tag</span>
                          )}
                        </div>
                        <button
                          className="icon-btn"
                          onClick={() => {
                            setOpenTagDropdownFor(openTagDropdownFor === fileName ? null : fileName);
                          }}
                          title={`Select tag for ${fileName}`}
                        >
                          +
                        </button>
                        {openTagDropdownFor === fileName && (
                          <div className="tag-menu">
                            <button
                              onClick={() => {
                                setPerFileTags((prev) => ({ ...prev, [fileName]: "social" }));
                                setOpenTagDropdownFor(null);
                              }}
                            >
                              Social (S)
                            </button>
                            <button
                              onClick={() => {
                                setPerFileTags((prev) => ({ ...prev, [fileName]: "environmental" }));
                                setOpenTagDropdownFor(null);
                              }}
                            >
                              Environmental (E)
                            </button>
                            <button
                              onClick={() => {
                                setPerFileTags((prev) => ({ ...prev, [fileName]: "governance" }));
                                setOpenTagDropdownFor(null);
                              }}
                            >
                              Governance (G)
                            </button>
                            <button
                              className="danger"
                              onClick={() => {
                                setPerFileTags((prev) => {
                                  const copy = { ...prev };
                                  delete copy[fileName];
                                  return copy;
                                });
                                setOpenTagDropdownFor(null);
                              }}
                            >
                              Remove tag
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            <p className="podglad">
              {selectedFiles.length ? `Selected: ${selectedFiles.map((f) => f.name).join(", ")}` : "No files selected"}
            </p>

            {isLoading && <div className="loader"></div>}
            {isCompleted && <div className="success-toast">Files processed! ✅</div>}
            <p className="message">{message}</p>
          </section>
        )}

        <section className="history-section">
          <div className="history-header">
            <h2>Document Processing History</h2>
            <button
              type="button"
              className="table-btn history-generate-btn"
              onClick={() => openAiReport()}
              disabled={!userDocuments.length}
            >
              Generate Report
            </button>
          </div>
          <div className="history-table">
            <div className="history-row history-head">
              <span>File name</span>
              <span>Type</span>
              <span>Uploaded</span>
              <span>Status</span>
              <span>Field</span>
              <span>Actions</span>
            </div>
            {!isLoggedIn ? (
              <div style={{ textAlign: "center", padding: "40px 20px", gridColumn: "1/-1" }}>
                <p style={{ marginBottom: "10px", color: "#1F2041" }}>No documents processed yet</p>
                <p style={{ color: "#666", fontSize: "14px" }}>Login to upload and process your documents</p>
              </div>
            ) : loadingDocuments ? (
              <div style={{ textAlign: "center", padding: "40px 20px", gridColumn: "1/-1" }}>
                <p>Loading your documents...</p>
              </div>
            ) : documentsError ? (
              <div style={{ textAlign: "center", padding: "40px 20px", gridColumn: "1/-1" }}>
                <p style={{ marginBottom: "10px", color: "#1F2041" }}>Could not load your documents</p>
                <p style={{ color: "#666", fontSize: "14px" }}>{documentsError}</p>
              </div>
            ) : userDocuments.length === 0 ? (
              <div style={{ textAlign: "center", padding: "40px 20px", gridColumn: "1/-1" }}>
                <p style={{ marginBottom: "10px", color: "#1F2041" }}>No documents processed yet</p>
                <p style={{ color: "#666", fontSize: "14px" }}>Upload files to start ESG analysis</p>
              </div>
            ) : (
              userDocuments.map((doc) => (
                <div className="history-row" key={doc.id}>
                  <span>{doc.name || doc.filename || "-"}</span>
                  <span>{doc.file_type || "-"}</span>
                  <span>{doc.created_at ? new Date(doc.created_at).toLocaleDateString() : "-"}</span>
                  <span className="status-cell status-processed">
                    <span className="status-dot" />
                    Processed
                  </span>
                  <span className="field-pill">
                    {doc.tag ? (
                      doc.tag === "social" ? "S" : 
                      doc.tag === "environmental" ? "E" : 
                      doc.tag === "governance" ? "G" :
                      doc.tag?.[0]?.toUpperCase()
                    ) : "-"}
                  </span>
                  <span>
                    <button className="table-btn danger" onClick={() => deleteUserDocument(doc.id)}>
                      Delete
                    </button>
                  </span>
                </div>
              ))
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
