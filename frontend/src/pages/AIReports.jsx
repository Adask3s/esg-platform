import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "../App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

const CHAPTERS = [
  { key: "Environmental", label: "Environmental Impact", sectionId: "section-environmental" },
  { key: "Social", label: "Social Responsibility", sectionId: "section-social" },
  { key: "Governance", label: "Governance & Ethics", sectionId: "section-governance" },
];

function mapTagToApi(tag) {
  if (!tag) return "ESG";
  const normalized = String(tag).trim().toLowerCase();
  if (normalized.startsWith("env")) return "Environmental";
  if (normalized.startsWith("soc")) return "Social";
  if (normalized.startsWith("gov")) return "Governance";
  return "ESG";
}

function formatIndicator(indicator) {
  if (!indicator) return "No metric available yet.";
  const name = indicator.nazwa || "Indicator";
  const value = indicator.wartosc ?? "-";
  const unit = indicator.jednostka ? ` ${indicator.jednostka}` : "";
  return `${name}: ${value}${unit}`;
}

export default function AIReports() {
  const [ragSidebarOpen, setRagSidebarOpen] = useState(false);
  const [activeChapter, setActiveChapter] = useState("Environmental");
  const [taskId, setTaskId] = useState(null);
  const [taskState, setTaskState] = useState("IDLE");
  const [taskProgress, setTaskProgress] = useState(0);
  const [error, setError] = useState("");
  const [reportResult, setReportResult] = useState(null);
  const navigate = useNavigate();
  const location = useLocation();
  const activeReportDoc = location.state?.doc || null;
  const token = localStorage.getItem("token");
  const environmentalRef = useRef(null);
  const socialRef = useRef(null);
  const governanceRef = useRef(null);

  const indicators = reportResult?.wskazniki_liczbowe || [];
  const actions = reportResult?.wdrozone_polityki_i_dzialania || [];
  const risks = reportResult?.zidentyfikowane_ryzyka || [];
  const legalSummary = reportResult?.wnioski_i_zgodnosc_prawna || "";

  const launchReportGeneration = async (tag) => {
    if (!token) {
      navigate("/login");
      return;
    }

    try {
      setError("");
      setTaskId(null);
      setTaskState("QUEUED");
      setTaskProgress(0);
      setReportResult(null);

      const response = await fetch(`${API_URL}/report/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ tag }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.detail || "Failed to start report generation.");
      }

      setTaskId(data.task_id);
      setTaskState("PENDING");
    } catch (err) {
      setTaskState("FAILURE");
      setError(err.message || "Unknown error during report generation.");
    }
  };

  useEffect(() => {
    const initialTag = mapTagToApi(activeReportDoc?.tag);
    launchReportGeneration(initialTag);
  }, []);

  useEffect(() => {
    if (!taskId || !token) return;

    let isCancelled = false;
    const intervalId = setInterval(async () => {
      try {
        const response = await fetch(`${API_URL}/status/${taskId}`, {
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });
        const data = await response.json();

        if (!response.ok) {
          throw new Error(data?.detail || "Cannot read task status.");
        }

        if (isCancelled) return;

        setTaskState(data.state || "PENDING");
        setTaskProgress(Number.isFinite(data.progress) ? data.progress : 0);

        if (data.state === "SUCCESS") {
          const payload = data?.result?.data || null;
          setReportResult(payload);
          clearInterval(intervalId);
        }

        if (data.state === "FAILURE") {
          setError(data?.error?.message || "Report generation failed.");
          clearInterval(intervalId);
        }
      } catch (err) {
        if (!isCancelled) {
          setError(err.message || "Unexpected status polling error.");
        }
        clearInterval(intervalId);
      }
    }, 1800);

    return () => {
      isCancelled = true;
      clearInterval(intervalId);
    };
  }, [taskId, token]);

  useEffect(() => {
    const sections = [
      { key: "Environmental", element: environmentalRef.current },
      { key: "Social", element: socialRef.current },
      { key: "Governance", element: governanceRef.current },
    ].filter((item) => item.element);

    if (!sections.length) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible.length) {
          const matched = sections.find((item) => item.element === visible[0].target);
          if (matched) setActiveChapter(matched.key);
        }
      },
      { root: null, threshold: [0.2, 0.4, 0.7], rootMargin: "-120px 0px -45% 0px" }
    );

    sections.forEach((item) => observer.observe(item.element));
    return () => observer.disconnect();
  }, [reportResult]);

  const scrollToChapter = (chapter) => {
    const target = document.getElementById(chapter.sectionId);
    if (!target) return;
    setActiveChapter(chapter.key);
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <div className="ai-report-shell">
      <header className="ai-report-topbar">
        <div className="ai-report-brand">ESG</div>
        <div className="ai-report-topbar-right">
          <button type="button" className="ai-report-back-btn" onClick={() => navigate("/")}>
            Back to Dashboard
          </button>
        </div>
      </header>

      <main className={`ai-report-main ${ragSidebarOpen ? "is-rag-open" : ""}`}>
        <aside className="ai-report-left">
          <p className="ai-report-left-label">REPORT CHAPTERS</p>
          {CHAPTERS.map((chapter) => (
            <button
              key={chapter.key}
              type="button"
              className={`ai-report-chapter ${activeChapter === chapter.key ? "is-active" : ""}`}
              onClick={() => scrollToChapter(chapter)}
            >
              <span>{chapter.label}</span>
              {activeChapter === chapter.key ? <span>›</span> : null}
            </button>
          ))}
        </aside>

        <section className="ai-report-canvas">
          <div className="ai-report-stage">
            <article className="ai-report-page">
              <div className="ai-report-model-pill">GPT-4 POWERED</div>
              <h1>Annual ESG Performance Report - 2025</h1>
              <div className="ai-report-rule" />

              <section ref={environmentalRef} id="section-environmental" className="ai-report-section-block">
                <h2>Environmental Impact</h2>
                <p>
                  {legalSummary ||
                    "Generating a grounded summary from your uploaded documents and knowledge base. This section updates automatically once the background task is complete."}
                </p>
                <p className="ai-report-highlight">{formatIndicator(indicators[0])}</p>
                <p>
                  {actions.length
                    ? actions.slice(0, 2).join(" ")
                    : "Policy and action details will be listed here after the report task reaches SUCCESS."}
                </p>
              </section>

              <section ref={socialRef} id="section-social" className="ai-report-section-block">
                <h2>Social Responsibility</h2>
                <p>
                  {actions.length
                    ? actions.join(" ")
                    : "No social actions extracted yet. Generate a dedicated social report to fill this section."}
                </p>
                <p className="ai-report-highlight">{formatIndicator(indicators[1])}</p>
                <p>
                  This chapter captures workforce impact, safety and development indicators sourced from uploaded
                  documents.
                </p>
              </section>

              <section ref={governanceRef} id="section-governance" className="ai-report-section-block">
                <h2>Governance &amp; Ethics</h2>
                <p>
                  {risks.length
                    ? risks.join(" ")
                    : "No governance risks extracted yet. Generate a dedicated governance report to fill this section."}
                </p>
                <p className="ai-report-highlight">{formatIndicator(indicators[2])}</p>
                <p>
                  This chapter summarizes compliance posture, controls and governance-related risk observations.
                </p>
              </section>

              <div className="ai-report-placeholder" aria-hidden="true" />
              <p className="ai-report-page-footer">TASK: {taskState} · {taskProgress}%</p>
            </article>

            <button
              type="button"
              className="ai-report-insight"
              onClick={() => setRagSidebarOpen((v) => !v)}
              aria-expanded={ragSidebarOpen}
            >
              <span className="ai-report-insight-title">AI INSIGHT</span>
              <span className="ai-report-insight-copy">{legalSummary || "Waiting for generated insight"}</span>
              <span className="ai-report-insight-btn">Update Section</span>
            </button>
          </div>
        </section>

        <aside className={`ai-report-rag ${ragSidebarOpen ? "is-open" : ""}`}>
          <div className="ai-report-accuracy">96%</div>
          <p className="ai-report-accuracy-label">GROUNDING ACCURACY</p>

          <p className="ai-report-side-label">ACTIVE CITATIONS</p>
          {(indicators.length ? indicators : [{ nazwa: "No extracted metric yet" }]).slice(0, 3).map((item, idx) => (
            <div className="ai-report-citation" key={`${item.nazwa || "metric"}-${idx}`}>
              <strong>{activeReportDoc?.name || activeReportDoc?.filename || "Generated Report"}</strong>
              <span>{formatIndicator(item)}</span>
              <button type="button">COMPARE WITH ORIGINAL</button>
            </div>
          ))}

          <div className="ai-report-warning">
            <p>COMPLIANCE WARNING</p>
            <strong>{risks[0] || "No critical risk detected yet"}</strong>
          </div>

          {error ? <p className="ai-report-error">{error}</p> : null}
        </aside>
      </main>

      <footer className="ai-report-footer">
        <div className="ai-report-file">{activeReportDoc?.name || activeReportDoc?.filename || "annual_report_draft_v2.pdf"}</div>
        <div className="ai-report-footer-actions">
          <button type="button" className="save-btn">
            Save Draft
          </button>
          <button type="button" className="export-btn">
            Finalize &amp; Export PDF
          </button>
        </div>
      </footer>
    </div>
  );
}
