import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import "../App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function Dashboard({ user, onLogout }) {
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef(null);
  const [message, setMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isCompleted, setIsCompleted] = useState(false);
  const [fileStatuses, setFileStatuses] = useState({});
  const [perFileTags, setPerFileTags] = useState({});
  const [openTagDropdownFor, setOpenTagDropdownFor] = useState(null);
  const [userDocuments, setUserDocuments] = useState([]);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const navigate = useNavigate();

  const isLoggedIn = !!user?.token;

  useEffect(() => {
    if (isLoggedIn) {
      setLoadingDocuments(true);
      fetch(`${API_URL}/documents/mine`, {
        method: "GET",
        headers: { Authorization: `Bearer ${user.token}` },
      })
        .then((res) => res.json())
        .then((data) => {
     
          let docs = Array.isArray(data) ? data : data?.documents || [];
          docs = docs.filter(doc => doc.origin === "user" || !doc.origin);
          setUserDocuments(docs);
        })
        .catch((err) => {
          console.error("Failed to fetch documents:", err);
          setUserDocuments([]);
        })
        .finally(() => setLoadingDocuments(false));
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
    setSelectedFiles(dropped.slice(0, 10));
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
    setSelectedFiles(files.slice(0, 10));
  }

  async function uploadFiles() {
    if (!selectedFiles.length) {
      setMessage("Please select files");
      return;
    }

    try {
      setIsLoading(true);
      setIsCompleted(false);
      
      for (const f of selectedFiles) {
        const formdata = new FormData();
        formdata.append("files", f);
        const tag = perFileTags[f.name] || ""; 
        if (tag) {
          formdata.append("tag", tag);
        }

        const response = await fetch(`${API_URL}/parse`, {
          method: "POST",
          body: formdata,
          headers: { Authorization: `Bearer ${user.token}` },
        });

        const data = await response.json();
        if (!response.ok) throw new Error(data?.detail || "Upload error");
      }

      setMessage("Files processed successfully");
      setIsCompleted(true);
      setTimeout(() => {
        fetch(`${API_URL}/documents/mine`, {
          method: "GET",
          headers: { Authorization: `Bearer ${user.token}` },
        })
          .then((res) => res.json())
          .then((data) => {
            const docs = Array.isArray(data) ? data : data?.documents || [];
            setUserDocuments(docs);
          })
          .catch((err) => console.error("Failed to refresh documents:", err));
      }, 1000);
    } catch (err) {
      setMessage(err.message || "Upload error");
    } finally {
      setIsLoading(false);
    }
  }

  function setStatus(filename, status) {
    setFileStatuses((prev) => ({
      ...prev,
      [filename]: status,
    }));
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
                multiple
                onChange={handleFileChange}
                style={{ display: "none" }}
              />
            </div>

            <button className="primary-btn" onClick={uploadFiles}>
              Submit
            </button>

            {selectedFiles.length > 0 && (
              <div className="file-status-row">
                <span className="file-label">Files</span>
                <div className="file-chip">
                  <span className="file-chip-icon">📄</span>
                  <span>{selectedFiles[0]?.name}</span>
                </div>
                <div className="file-actions">
                  <div className="tag-pill-wrap">
                    {perFileTags[selectedFiles[0].name] ? (
                      <span className="tag-pill">{perFileTags[selectedFiles[0].name].toUpperCase()}</span>
                    ) : (
                      <span className="tag-pill is-empty">No tag</span>
                    )}
                  </div>
                  <button
                    className="icon-btn"
                    onClick={() => {
                      const fileName = selectedFiles[0]?.name;
                      if (!fileName) return;
                      setOpenTagDropdownFor(openTagDropdownFor === fileName ? null : fileName);
                    }}
                    title="Select tag"
                  >
                    +
                  </button>
                  {openTagDropdownFor === selectedFiles[0]?.name && (
                    <div className="tag-menu">
                      <button onClick={() => { const fileName = selectedFiles[0]?.name; if (!fileName) return; setPerFileTags((prev) => ({ ...prev, [fileName]: "social" })); setOpenTagDropdownFor(null); }}>Social (S)</button>
                      <button onClick={() => { const fileName = selectedFiles[0]?.name; if (!fileName) return; setPerFileTags((prev) => ({ ...prev, [fileName]: "environmental" })); setOpenTagDropdownFor(null); }}>Environmental (E)</button>
                      <button onClick={() => { const fileName = selectedFiles[0]?.name; if (!fileName) return; setPerFileTags((prev) => ({ ...prev, [fileName]: "governance" })); setOpenTagDropdownFor(null); }}>Governance (G)</button>
                      <button className="danger" onClick={() => { const fileName = selectedFiles[0]?.name; if (!fileName) return; setPerFileTags((prev) => { const copy = { ...prev }; delete copy[fileName]; return copy; }); setOpenTagDropdownFor(null); }}>Remove tag</button>
                    </div>
                  )}
                </div>
                <span className="file-status">Status:</span>
                <span className="file-status-value">
                  {fileStatuses[selectedFiles[0].name] || "<status>"}
                </span>
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
          <h2>Document Processing History</h2>
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
                    <button className="table-btn" onClick={() => openAiReport(doc)}>AI Report</button>
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
