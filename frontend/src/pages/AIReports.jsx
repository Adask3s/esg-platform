import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import "../App.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const REPORT_YEAR = new Date().getFullYear();
const REPORT_MODEL_LABEL = import.meta.env.VITE_REPORT_MODEL_LABEL || "AI POWERED";

const CHAPTERS = [
  { key: "Environmental", label: "Executive Summary", sectionId: "section-environmental" },
  { key: "Social", label: "Detailed Analysis", sectionId: "section-social" },
  { key: "Governance", label: "Risks & Compliance", sectionId: "section-governance" },
];

const LOADING_STATES = new Set(["QUEUED", "PENDING", "STARTED", "PROGRESS", "RETRY"]);
const VALIDATION_STANDARDS = [
  { value: "GRI", label: "GRI" },
  { value: "SASB", label: "SASB" },
  { value: "TCFD", label: "TCFD" },
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
  if (!indicator) return "Metric extraction in progress.";
  const name = indicator.nazwa || "Indicator";
  const value = indicator.wartosc ?? "-";
  const unit = indicator.jednostka ? ` ${indicator.jednostka}` : "";
  return `${name}: ${value}${unit}`;
}

function ReportList({ items, emptyText }) {
  const cleaned = Array.isArray(items) ? items.filter(Boolean) : [];
  if (!cleaned.length) {
    return <p className="ai-report-muted">{emptyText}</p>;
  }

  return (
    <ul className="ai-report-list">
      {cleaned.map((item, index) => (
        <li key={`${String(item).slice(0, 42)}-${index}`}>{item}</li>
      ))}
    </ul>
  );
}

function MetricList({ indicators, isGenerating }) {
  const cleaned = Array.isArray(indicators) ? indicators.filter(Boolean) : [];
  if (!cleaned.length) {
    return (
      <div className={`ai-report-metric-list ${isGenerating ? "is-loading" : ""}`}>
        <div className="ai-report-metric-row">
          <strong>{isGenerating ? "Extracting metrics..." : "No numeric metrics found."}</strong>
          <span>{isGenerating ? "RAG is searching source documents." : "Check source data or choose another scope."}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="ai-report-metric-list">
      {cleaned.slice(0, 8).map((indicator, index) => (
        <div className="ai-report-metric-row" key={`${indicator.nazwa || "metric"}-${index}`}>
          <strong>{indicator.nazwa || "Indicator"}</strong>
          <span>
            {indicator.wartosc ?? "-"}
            {indicator.jednostka ? ` ${indicator.jednostka}` : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

function ValidationPanel({
  standard,
  onStandardChange,
  onValidate,
  status,
  error,
  result,
  disabled,
  reportId,
}) {
  const items = Array.isArray(result?.items) ? result.items : [];
  const isLoading = status === "loading";

  return (
    <div className="ai-report-validation-panel">
      <div className="ai-report-validation-header">
        <div>
          <h3>Standards validation</h3>
          <p>{reportId ? `Report ID: ${reportId}` : "Report is not saved yet."}</p>
        </div>
        <div className="ai-report-validation-controls">
          <select
            value={standard}
            onChange={(event) => onStandardChange(event.target.value)}
            disabled={isLoading}
            aria-label="Validation standard"
          >
            {VALIDATION_STANDARDS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          <button type="button" onClick={onValidate} disabled={disabled || isLoading}>
            {isLoading ? "Validating..." : "Validate"}
          </button>
        </div>
      </div>

      {error ? <p className="ai-report-validation-error">{error}</p> : null}

      {result ? (
        <>
          <div className="ai-report-validation-score">
            <strong>{result.score ?? 0}%</strong>
            <span>{result.overall_status || "partial"}</span>
          </div>
          <p className="ai-report-muted">{result.summary}</p>
          <ul className="ai-report-validation-list">
            {items.map((item) => (
              <li key={item.code} className={item.present ? "is-present" : "is-missing"}>
                <span className="ai-report-validation-mark">{item.present ? "\u2713" : "\u2717"}</span>
                <div>
                  <strong>
                    {item.code} {item.present ? "obecne" : "brakuje"}
                  </strong>
                  <p>{item.label}</p>
                  {item.evidence ? <span>{item.evidence}</span> : null}
                  {!item.present && item.recommendation ? <span>{item.recommendation}</span> : null}
                </div>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="ai-report-muted">
          {disabled ? "Validation is available after the report is saved." : "Choose a standard and validate the report."}
        </p>
      )}
    </div>
  );
}

function filenameFromDisposition(disposition) {
  if (!disposition) return "raport_ESG.pdf";
  const utfMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utfMatch?.[1]) return decodeURIComponent(utfMatch[1]);
  const asciiMatch = disposition.match(/filename="?([^";]+)"?/i);
  return asciiMatch?.[1] || "raport_ESG.pdf";
}

export default function AIReports() {
  const [ragSidebarOpen, setRagSidebarOpen] = useState(false);
  const [activeChapter, setActiveChapter] = useState("Environmental");
  const [taskId, setTaskId] = useState(null);
  const [taskState, setTaskState] = useState("IDLE");
  const [taskProgress, setTaskProgress] = useState(0);
  const [taskStagePl, setTaskStagePl] = useState("");
  const [error, setError] = useState("");
  const [pdfStatus, setPdfStatus] = useState("");
  const [isDownloadingPdf, setIsDownloadingPdf] = useState(false);
  const [reportResult, setReportResult] = useState(null);
  const [reportMeta, setReportMeta] = useState(null);
  const [validationStandard, setValidationStandard] = useState("GRI");
  const [validationStatus, setValidationStatus] = useState("idle");
  const [validationResult, setValidationResult] = useState(null);
  const [validationError, setValidationError] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const activeReportDoc = location.state?.doc || null;
  const savedReportId = location.state?.reportId || null;
  const savedReportType = location.state?.reportType || null;
  const requestedScope = location.state?.scope || mapTagToApi(activeReportDoc?.tag);
  const requestedStandard = location.state?.standard || "GRI";
  const isSavedReportPreview = !!savedReportId;
  const reportSourceLabel = isSavedReportPreview
    ? `Saved report ${savedReportId}${savedReportType ? ` · ${savedReportType}` : ""}`
    : activeReportDoc?.name || activeReportDoc?.filename || "All uploaded documents";
  const token = localStorage.getItem("token");
  const environmentalRef = useRef(null);
  const socialRef = useRef(null);
  const governanceRef = useRef(null);

  const indicators = reportResult?.wskazniki_liczbowe || [];
  const actions = reportResult?.wdrozone_polityki_i_dzialania || [];
  const risks = reportResult?.zidentyfikowane_ryzyka || [];
  const executiveSummary = reportResult?.streszczenie_wykonawcze || "";
  const methodology = reportResult?.zakres_i_metodyka || "";
  const detailedAnalysis = reportResult?.szczegolowa_analiza || [];
  const dataGaps = reportResult?.luki_w_danych || [];
  const recommendations = reportResult?.rekomendacje || [];
  const standardCompliance = reportResult?.zgodnosc_ze_standardami || [];
  const legalSummary = reportResult?.wnioski_i_zgodnosc_prawna || "";
  const isGenerating = LOADING_STATES.has(taskState);
  const isPreviewLoading = taskState === "LOADING";
  const isPartialSuccess = taskState === "SUCCESS" && reportMeta?.status === "partial_success";
  const partialMessage = reportMeta?.message || "No source data found for this report scope.";

  const loadSavedReport = useCallback(async () => {
    if (!savedReportId) return;
    if (!token) {
      navigate("/login");
      return;
    }

    try {
      setError("");
      setTaskId(null);
      setTaskState("LOADING");
      setTaskProgress(100);
      setTaskStagePl("Wczytywanie zapisanego raportu");
      setReportResult(null);
      setReportMeta(null);
      setPdfStatus("");
      setValidationResult(null);
      setValidationError("");
      setValidationStatus("idle");
      setValidationStandard(requestedStandard);

      const response = await fetch(`${API_URL}/reports/${savedReportId}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.detail || "Failed to load saved report.");
      }

      let parsedReport = data?.content ?? data?.response_text ?? null;
      if (typeof parsedReport === "string") {
        try {
          parsedReport = JSON.parse(parsedReport);
        } catch {
          parsedReport = null;
        }
      }
      const savedStandard = parsedReport?.standard_raportowania || data?.metadata?.standard || requestedStandard;
      setValidationStandard(savedStandard);

      setReportMeta({
        status: "saved",
        report_id: data?.metadata?.id || savedReportId,
        standard: savedStandard,
        report_type: data?.metadata?.report_type || data?.report_type || savedReportType || "ESG",
        created_at: data?.metadata?.created_at || data?.created_at || null,
        message: "Saved report preview",
      });
      setReportResult(parsedReport || {});
      setTaskState("SUCCESS");
      setTaskStagePl("Podgląd raportu");
      setTaskProgress(100);
    } catch (err) {
      setTaskState("FAILURE");
      setTaskStagePl("");
      setError(err.message || "Unexpected saved report preview error.");
    }
  }, [navigate, requestedStandard, savedReportId, savedReportType, token]);

  const launchReportGeneration = useCallback(async (tag, standard) => {
    if (!token) {
      navigate("/login");
      return;
    }

    try {
      setError("");
      setTaskId(null);
      setTaskState("QUEUED");
      setTaskProgress(0);
      setTaskStagePl("Kolejkowanie zadania");
      setReportResult(null);
      setReportMeta(null);
      setPdfStatus("");
      setValidationStandard(standard || "GRI");
      setValidationResult(null);
      setValidationError("");
      setValidationStatus("idle");

      const response = await fetch(`${API_URL}/report/generate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ report_scope: tag, standard: standard || "GRI" }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.detail || "Failed to start report generation.");
      }

      setTaskId(data.task_id);
      setTaskState("PENDING");
      setTaskStagePl("Oczekiwanie na worker Celery");
    } catch (err) {
      setTaskState("FAILURE");
      setTaskStagePl("");
      setError(err.message || "Unknown error during report generation.");
    }
  }, [navigate, token]);

  useEffect(() => {
    if (isSavedReportPreview) {
      loadSavedReport();
      return;
    }

    launchReportGeneration(requestedScope, requestedStandard);
  }, [isSavedReportPreview, launchReportGeneration, loadSavedReport, requestedScope, requestedStandard]);

  useEffect(() => {
    try {
      window.scrollTo({ top: 0, left: 0 });
    } catch {
      // ignore
    }
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
        setTaskStagePl(data.stage_pl || data.stage || "Przetwarzanie");

        if (data.state === "SUCCESS") {
          const result = data?.result || null;
          const payload = result?.data || null;
          setReportMeta(result);
          setReportResult(payload);
          setValidationStandard(result?.standard || payload?.standard_raportowania || requestedStandard);
          setPdfStatus(result?.status === "partial_success" ? "Empty report PDF ready for export." : "Report ready for PDF export.");
          setTaskStagePl("Gotowe");
          clearInterval(intervalId);
        }

        if (data.state === "FAILURE") {
          setError(data?.error?.message || "Report generation failed.");
          setTaskStagePl("Błąd generowania");
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
  }, [requestedStandard, taskId, token]);

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

  const downloadGeneratedPdf = async () => {
    if (!token) {
      navigate("/login");
      return;
    }

    if (isSavedReportPreview) {
      setError("PDF export is available only for freshly generated reports.");
      return;
    }

    if (!taskId || taskState !== "SUCCESS") {
      setError("Report PDF is available after the background task reaches SUCCESS.");
      return;
    }

    try {
      setError("");
      setPdfStatus("Preparing PDF...");
      setIsDownloadingPdf(true);

      const response = await fetch(`${API_URL}/report/download/${taskId}`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.detail || `PDF download failed (${response.status}).`);
      }

      const blob = await response.blob();
      const filename = filenameFromDisposition(response.headers.get("Content-Disposition"));
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      setPdfStatus("PDF downloaded.");
    } catch (err) {
      setPdfStatus("");
      setError(err.message || "Unexpected PDF download error.");
    } finally {
      setIsDownloadingPdf(false);
    }
  };

  const validationReportId = savedReportId || reportMeta?.report_id || null;

  const updateValidationStandard = (nextStandard) => {
    setValidationStandard(nextStandard);
    setValidationResult(null);
    setValidationError("");
    setValidationStatus("idle");
  };

  const validateReport = async () => {
    if (!token) {
      navigate("/login");
      return;
    }

    if (!validationReportId) {
      setValidationError("Validation is available after the report is saved.");
      return;
    }

    try {
      setValidationError("");
      setValidationStatus("loading");

      const response = await fetch(`${API_URL}/report/${validationReportId}/validate`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ standard: validationStandard }),
      });

      const data = await response.json();
      if (!response.ok) {
        throw new Error(data?.detail || "Report validation failed.");
      }

      setValidationResult(data);
      setValidationStatus("success");
    } catch (err) {
      setValidationStatus("error");
      setValidationResult(null);
      setValidationError(err.message || "Unexpected report validation error.");
    }
  };

  const displayScope = reportResult?.kategoria || reportMeta?.report_type || requestedScope;
  const showLoadingPanel = isGenerating || isPreviewLoading;

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
              <div className="ai-report-model-pill">{REPORT_MODEL_LABEL}</div>
              <h1>{displayScope} Performance Report - {REPORT_YEAR}</h1>
              <div className="ai-report-rule" />

              {showLoadingPanel ? (
                <div className="ai-report-loading-panel" role="status" aria-live="polite">
                  <div className="ai-report-spinner" aria-hidden="true" />
                  <div>
                    <strong>{isSavedReportPreview ? "Wczytywanie zapisanego raportu..." : "Generowanie raportu..."}</strong>
                    <span>
                      {taskStagePl || (isSavedReportPreview ? "Pobieranie raportu z historii" : "Analiza dokumentów i kontekstu RAG")}
                    </span>
                  </div>
                  <div className="ai-report-loading-bar">
                    <div style={{ width: `${Math.max(5, taskProgress)}%` }} />
                  </div>
                  <p>
                    {isSavedReportPreview
                      ? "To jest podgląd wcześniej zapisnego raportu."
                      : "Celery pracuje w tle. Raport pojawi się automatycznie po zakończeniu zadania."}
                  </p>
                </div>
              ) : null}

              {isPartialSuccess ? (
                <div className="ai-report-empty-panel">
                  <strong>Brak danych dla zakresu {displayScope}</strong>
                  <p>{partialMessage}</p>
                </div>
              ) : null}

              <section ref={environmentalRef} id="section-environmental" className="ai-report-section-block">
                <h2>Executive Summary</h2>
                <p>
                  {showLoadingPanel
                    ? "System analizuje dokumenty użytkownika, pobiera pasujące chunki i buduje prompt raportowy."
                    : executiveSummary || legalSummary || partialMessage}
                </p>
                <p className="ai-report-highlight">
                  Scope: {displayScope} · Status: {taskState} · {taskProgress}%
                </p>
                <p>
                  {methodology ||
                    (showLoadingPanel
                      ? "Metodyka i ograniczenia danych zostaną pokazane po zakończeniu generowania."
                      : "Brak opisu metodyki w odpowiedzi modelu.")}
                </p>
              </section>

              <section ref={socialRef} id="section-social" className="ai-report-section-block">
                <h2>Detailed Analysis</h2>
                <MetricList indicators={indicators} isGenerating={isGenerating} />
                <ReportList
                  items={detailedAnalysis}
                  emptyText={
                    showLoadingPanel
                      ? "Szczegółowa analiza pojawi się po zakończeniu zadania."
                      : "Brak szczegółowej analizy w odpowiedzi modelu."
                  }
                />
                <h3>Implemented actions</h3>
                <ReportList
                  items={actions}
                  emptyText={
                    showLoadingPanel
                      ? "Działania i polityki są jeszcze ekstrahowane."
                      : "Nie znaleziono działań ani polityk dla tego zakresu."
                  }
                />
              </section>

              <section ref={governanceRef} id="section-governance" className="ai-report-section-block">
                <h2>Risks, Recommendations &amp; Compliance</h2>
                <h3>Risks</h3>
                <ReportList
                  items={risks}
                  emptyText={showLoadingPanel ? "Ryzyka są jeszcze identyfikowane." : "Nie znaleziono ryzyk dla tego zakresu."}
                />
                <h3>Data gaps</h3>
                <ReportList
                  items={dataGaps}
                  emptyText={showLoadingPanel ? "Luki danych są jeszcze oceniane." : "Brak wskazanych luk danych."}
                />
                <h3>Recommendations</h3>
                <ReportList
                  items={recommendations}
                  emptyText={showLoadingPanel ? "Rekomendacje zostaną wygenerowane po analizie." : "Brak rekomendacji."}
                />
                <h3>Standards and legal context</h3>
                <ValidationPanel
                  standard={validationStandard}
                  onStandardChange={updateValidationStandard}
                  onValidate={validateReport}
                  status={validationStatus}
                  error={validationError}
                  result={validationResult}
                  disabled={!validationReportId || showLoadingPanel}
                  reportId={validationReportId}
                />
                <ReportList
                  items={standardCompliance}
                  emptyText={legalSummary || "Brak oceny zgodności ze standardami."}
                />
              </section>

              <p className="ai-report-page-footer">TASK: {taskState} · {taskProgress}%</p>
            </article>
          </div>

          <button
            type="button"
            className="ai-report-insight-toggle"
            onClick={() => setRagSidebarOpen((v) => !v)}
            title="Show statistics"
          >
            {ragSidebarOpen ? "<" : ">"}
          </button>

          <button
            type="button"
            className="ai-report-insight"
            onClick={() => setRagSidebarOpen((v) => !v)}
            aria-expanded={ragSidebarOpen}
          >
            <span className="ai-report-insight-title">AI INSIGHT</span>
            <span className="ai-report-insight-copy">
                {showLoadingPanel ? taskStagePl || (isSavedReportPreview ? "Loading saved report" : "Generating report") : legalSummary || executiveSummary || partialMessage}
            </span>
            <span className="ai-report-insight-btn">Update Section</span>
          </button>
        </section>

        <aside className={`ai-report-rag ${ragSidebarOpen ? "is-open" : ""}`}>
          <div className="ai-report-accuracy">{isGenerating ? `${taskProgress}%` : "RAG"}</div>
          <p className="ai-report-accuracy-label">
            {showLoadingPanel ? (isSavedReportPreview ? "REPORT PREVIEW" : "GENERATION PROGRESS") : "GROUNDING CONTEXT"}
          </p>
          <p className="ai-report-side-label">TASK STATUS</p>
          <div className="ai-report-citation">
            <strong>{taskState}</strong>
            <span>{taskStagePl || reportMeta?.applied_filter || "Ready"}</span>
          </div>

          <p className="ai-report-side-label">ACTIVE CITATIONS</p>
          {(indicators.length ? indicators : [{ nazwa: "No extracted metric yet" }]).slice(0, 3).map((item, idx) => (
            <div className="ai-report-citation" key={`${item.nazwa || "metric"}-${idx}`}>
              <strong>{reportSourceLabel}</strong>
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
        <div className="ai-report-file">{reportSourceLabel}</div>
        <div className="ai-report-footer-actions">
          <button type="button" className="save-btn">
            Save Draft
          </button>
          {pdfStatus ? <span className="pdf-status">{pdfStatus}</span> : null}
          <button
            type="button"
            className="export-btn"
            onClick={downloadGeneratedPdf}
            disabled={isSavedReportPreview || taskState !== "SUCCESS" || isDownloadingPdf}
          >
            {isSavedReportPreview ? "Preview only" : isDownloadingPdf ? "Preparing PDF..." : "Finalize & Export PDF"}
          </button>
        </div>
      </footer>
    </div>
  );
}
