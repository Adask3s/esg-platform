import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import "../App.css";
import MultiFileUpload from "../components/MultiFileUpload";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const REPORT_SCOPES = [
  { value: "ESG", label: "Full ESG" },
  { value: "Environmental", label: "Environmental" },
  { value: "Social", label: "Social" },
  { value: "Governance", label: "Governance" },
];

function scopeFromTag(tag, fallback = "ESG") {
  const normalized = String(tag || "").trim().toLowerCase();
  if (normalized.startsWith("env") || normalized === "e") return "Environmental";
  if (normalized.startsWith("soc") || normalized === "s") return "Social";
  if (normalized.startsWith("gov") || normalized === "g") return "Governance";
  if (normalized === "esg") return "ESG";
  return fallback;
}

export default function Dashboard({ user, onLogout }) {
  const [userDocuments, setUserDocuments] = useState([]);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [refreshingDocuments, setRefreshingDocuments] = useState(false);
  const [documentsError, setDocumentsError] = useState("");
  const [selectedReportScope, setSelectedReportScope] = useState("ESG");
  const hasLoadedDocuments = useRef(false);
  const navigate = useNavigate();

  const isLoggedIn = !!user?.token;

  const refreshUserDocuments = useCallback(async (options = {}) => {
    if (!isLoggedIn) return;
    const keepTableVisible = options.keepTableVisible || hasLoadedDocuments.current;
    if (keepTableVisible) {
      setRefreshingDocuments(true);
    } else {
      setLoadingDocuments(true);
    }
    setDocumentsError("");
    try {
      const res = await fetch(`${API_URL}/documents/mine`, {
        method: "GET",
        headers: { Authorization: `Bearer ${user.token}` },
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || "Failed to load documents");
      }
      let docs = Array.isArray(data) ? data : data?.documents || [];
      docs = docs.filter((doc) => doc.origin === "user" || !doc.origin);
      setUserDocuments(docs);
      hasLoadedDocuments.current = true;
    } catch (err) {
      console.error("Failed to fetch documents:", err);
      setUserDocuments([]);
      setDocumentsError(err.message || "Failed to load documents");
    } finally {
      setLoadingDocuments(false);
      setRefreshingDocuments(false);
    }
  }, [isLoggedIn, user?.token]);

  useEffect(() => {
    refreshUserDocuments();
  }, [refreshUserDocuments]);

  const deleteUserDocument = async (documentId) => {
    if (!documentId) return;
    const confirmed = window.confirm("Delete this document and all related chunks?");
    if (!confirmed) return;

    try {
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

      await refreshUserDocuments();
    } catch (err) {
      console.error("Delete error:", err);
    }
  };

  const openAiReport = (doc, explicitScope) => {
    const scope = doc ? scopeFromTag(doc.tag, selectedReportScope) : explicitScope || selectedReportScope;
    navigate("/aireports", { state: { doc: doc || null, scope } });
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
                style={{
                  background: "none",
                  border: "none",
                  color: "#f6f1e7",
                  cursor: "pointer",
                  fontSize: "13px",
                }}
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
            <MultiFileUpload
              token={user.token}
              onFileCompleted={() => refreshUserDocuments({ keepTableVisible: true })}
              onAllCompleted={() => refreshUserDocuments({ keepTableVisible: true })}
            />
          </section>
        )}

        <section className="history-section">
          <div className="history-header">
            <h2>Document Processing History</h2>
            <div className="history-report-controls">
              <label className="history-scope-label" htmlFor="report-scope">
                Scope
              </label>
              <select
                id="report-scope"
                className="history-scope-select"
                value={selectedReportScope}
                onChange={(event) => setSelectedReportScope(event.target.value)}
                disabled={!userDocuments.length}
              >
                {REPORT_SCOPES.map((scope) => (
                  <option key={scope.value} value={scope.value}>
                    {scope.label}
                  </option>
                ))}
              </select>
              <button
                type="button"
                className="table-btn history-generate-btn"
                onClick={() => openAiReport(null, selectedReportScope)}
                disabled={!userDocuments.length}
              >
                Generate Report
              </button>
            </div>
          </div>
          {refreshingDocuments ? (
            <div className="history-refreshing">Refreshing documents...</div>
          ) : null}
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
              <div
                style={{
                  textAlign: "center",
                  padding: "40px 20px",
                  gridColumn: "1/-1",
                }}
              >
                <p style={{ marginBottom: "10px", color: "#1F2041" }}>
                  No documents processed yet
                </p>
                <p style={{ color: "#666", fontSize: "14px" }}>
                  Login to upload and process your documents
                </p>
              </div>
            ) : loadingDocuments ? (
              <div
                style={{
                  textAlign: "center",
                  padding: "40px 20px",
                  gridColumn: "1/-1",
                }}
              >
                <p>Loading your documents...</p>
              </div>
            ) : documentsError ? (
              <div style={{ textAlign: "center", padding: "40px 20px", gridColumn: "1/-1" }}>
                <p style={{ marginBottom: "10px", color: "#1F2041" }}>Could not load your documents</p>
                <p style={{ color: "#666", fontSize: "14px" }}>{documentsError}</p>
              </div>
            ) : userDocuments.length === 0 ? (
              <div
                style={{
                  textAlign: "center",
                  padding: "40px 20px",
                  gridColumn: "1/-1",
                }}
              >
                <p style={{ marginBottom: "10px", color: "#1F2041" }}>
                  No documents processed yet
                </p>
                <p style={{ color: "#666", fontSize: "14px" }}>
                  Upload files to start ESG analysis
                </p>
              </div>
            ) : (
              userDocuments.map((doc) => (
                <div className="history-row" key={doc.id}>
                  <span>{doc.name || doc.filename || "-"}</span>
                  <span>{doc.file_type || "-"}</span>
                  <span>
                    {doc.created_at
                      ? new Date(doc.created_at).toLocaleDateString()
                      : "-"}
                  </span>
                  <span className="status-cell status-processed">
                    <span className="status-dot" />
                    Processed
                  </span>
                  <span className="field-pill">
                    {doc.tag
                      ? doc.tag === "social"
                        ? "S"
                        : doc.tag === "environmental"
                        ? "E"
                        : doc.tag === "governance"
                        ? "G"
                        : doc.tag?.[0]?.toUpperCase()
                      : "-"}
                  </span>
                  <span className="history-row-actions">
                    <button className="table-btn" onClick={() => openAiReport(doc)}>
                      Report
                    </button>
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
