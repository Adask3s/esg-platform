import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "../App.css";
import MultiFileUpload from "../components/MultiFileUpload";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function Dashboard({ user, onLogout }) {
  const [userDocuments, setUserDocuments] = useState([]);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const navigate = useNavigate();

  const isLoggedIn = !!user?.token;

  const refreshUserDocuments = useCallback(async () => {
    if (!isLoggedIn) return;
    setLoadingDocuments(true);
    try {
      const res = await fetch(`${API_URL}/documents/mine`, {
        method: "GET",
        headers: { Authorization: `Bearer ${user.token}` },
      });
      const data = await res.json();
      let docs = Array.isArray(data) ? data : data?.documents || [];
      docs = docs.filter((doc) => doc.origin === "user" || !doc.origin);
      setUserDocuments(docs);
    } catch (err) {
      console.error("Failed to fetch documents:", err);
      setUserDocuments([]);
    } finally {
      setLoadingDocuments(false);
    }
  }, [isLoggedIn, user?.token]);

  useEffect(() => {
    refreshUserDocuments();
  }, [refreshUserDocuments]);

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
              onAllCompleted={refreshUserDocuments}
            />
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
                  <span>
                    <button
                      className="table-btn"
                      onClick={() => openAiReport(doc)}
                    >
                      AI Report
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
