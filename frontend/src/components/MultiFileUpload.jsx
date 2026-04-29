import { useEffect, useRef, useState } from "react";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";
const MAX_FILES = 10;
const MAX_FILE_SIZE = 50 * 1024 * 1024;
const CONCURRENCY = 3;
const POLL_INTERVAL_MS = 1500;

const TAGS = [
  { value: "social", label: "Social (S)" },
  { value: "environmental", label: "Environmental (E)" },
  { value: "governance", label: "Governance (G)" },
];

function fileKey(file) {
  return `${file.name}__${file.size}__${file.lastModified}`;
}

let nextItemId = 0;
function makeItem(file) {
  nextItemId += 1;
  return {
    id: nextItemId,
    key: fileKey(file),
    file,
    tag: "",
    phase: "queued",
    progress: 0,
    stagePl: "",
    taskId: null,
    error: null,
  };
}

export default function MultiFileUpload({ token, onAllCompleted }) {
  const [items, setItems] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const [openTagFor, setOpenTagFor] = useState(null);
  const inputRef = useRef(null);
  const pollTimers = useRef(new Map());
  const cancelledIds = useRef(new Set());
  const itemsRef = useRef(items);
  const completionNotifiedRef = useRef(false);

  useEffect(() => {
    itemsRef.current = items;
  }, [items]);

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

  useEffect(() => {
    const timers = pollTimers.current;
    return () => {
      timers.forEach(clearInterval);
      timers.clear();
    };
  }, []);

  const usedSlots = items.length;
  const isFull = usedSlots >= MAX_FILES;
  const queuedCount = items.filter((it) => it.phase === "queued").length;
  const inFlightCount = items.filter(
    (it) => it.phase === "uploading" || it.phase === "processing"
  ).length;
  const allDone = items.length > 0 && items.every((it) => it.phase === "done");

  function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  function handleDragOver(e) {
    preventDefaults(e);
    if (!isFull) setIsDragging(true);
  }

  function handleDragLeave(e) {
    preventDefaults(e);
    setIsDragging(false);
  }

  function handleDrop(e) {
    preventDefaults(e);
    setIsDragging(false);
    addFiles(Array.from(e.dataTransfer?.files || []));
  }

  function handleClickDropzone() {
    if (isFull) return;
    inputRef.current?.click();
  }

  function handleFileChange(e) {
    addFiles(Array.from(e.target.files || []));
    e.target.value = "";
  }

  function addFiles(incoming) {
    if (!incoming.length) return;
    completionNotifiedRef.current = false;
    setItems((prev) => {
      const seen = new Set(prev.map((it) => it.key));
      const additions = [];
      for (const f of incoming) {
        const k = fileKey(f);
        if (seen.has(k)) continue;
        if (prev.length + additions.length >= MAX_FILES) break;
        additions.push(makeItem(f));
        seen.add(k);
      }
      return [...prev, ...additions];
    });
  }

  function patchItem(id, patch) {
    setItems((prev) => prev.map((it) => (it.id === id ? { ...it, ...patch } : it)));
  }

  function removeItem(id) {
    const it = itemsRef.current.find((x) => x.id === id);
    if (!it) return;
    if (it.phase === "uploading" || it.phase === "processing") return;
    const timer = pollTimers.current.get(id);
    if (timer) {
      clearInterval(timer);
      pollTimers.current.delete(id);
    }
    cancelledIds.current.add(id);
    setItems((prev) => prev.filter((x) => x.id !== id));
  }

  function setItemTag(id, tag) {
    patchItem(id, { tag });
    setOpenTagFor(null);
  }

  function retry(id) {
    patchItem(id, {
      phase: "queued",
      progress: 0,
      stagePl: "",
      error: null,
      taskId: null,
    });
  }

  async function handleSubmit() {
    const queuedIds = itemsRef.current
      .filter((it) => it.phase === "queued")
      .map((it) => it.id);
    if (!queuedIds.length) return;
    completionNotifiedRef.current = false;

    const queue = [...queuedIds];
    const worker = async () => {
      while (queue.length) {
        const id = queue.shift();
        await runUpload(id);
      }
    };
    const workers = Array.from(
      { length: Math.min(CONCURRENCY, queuedIds.length) },
      () => worker()
    );
    await Promise.all(workers);

    if (completionNotifiedRef.current) return;
    const final = itemsRef.current;
    const allFinished = final.length > 0 && final.every(
      (it) => it.phase === "done" || it.phase === "failed"
    );
    const successful = final.filter((it) => it.phase === "done");
    if (allFinished && successful.length && onAllCompleted) {
      completionNotifiedRef.current = true;
      onAllCompleted(successful);
    }
  }

  async function runUpload(id) {
    const it = itemsRef.current.find((x) => x.id === id);
    if (!it) return;

    if (it.file.size > MAX_FILE_SIZE) {
      patchItem(id, {
        phase: "failed",
        error: { message: "Plik przekracza limit 50 MB", retryable: false },
      });
      return;
    }

    patchItem(id, { phase: "uploading", progress: 0, stagePl: "Przesyłanie" });

    try {
      const fd = new FormData();
      fd.append("file", it.file);
      if (it.tag) fd.append("tag", it.tag);

      const res = await fetch(`${API_URL}/user/documents/upload`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        const message =
          data?.detail ||
          (res.status === 409
            ? "Ten dokument już istnieje"
            : `Błąd uploadu (${res.status})`);
        patchItem(id, {
          phase: "failed",
          error: { message, retryable: res.status >= 500 },
        });
        return;
      }

      const taskId = data.task_id;
      patchItem(id, {
        phase: "processing",
        taskId,
        progress: 0,
        stagePl: "Oczekiwanie...",
      });

      await pollUntilDone(id, taskId);
    } catch (err) {
      patchItem(id, {
        phase: "failed",
        error: { message: err.message || "Błąd sieci", retryable: true },
      });
    }
  }

  function pollUntilDone(id, taskId) {
    return new Promise((resolve) => {
      const intervalId = setInterval(async () => {
        if (cancelledIds.current.has(id)) {
          clearInterval(intervalId);
          pollTimers.current.delete(id);
          resolve();
          return;
        }
        try {
          const res = await fetch(`${API_URL}/status/${taskId}`, {
            headers: { Authorization: `Bearer ${token}` },
          });
          const data = await res.json().catch(() => ({}));

          if (!res.ok) {
            clearInterval(intervalId);
            pollTimers.current.delete(id);
            patchItem(id, {
              phase: "failed",
              error: {
                message: data?.detail || `Status check failed (${res.status})`,
                retryable: true,
              },
            });
            resolve();
            return;
          }

          const state = data.state;
          const progress = Number.isFinite(data.progress) ? data.progress : 0;
          const stagePl = data.stage_pl || "";

          if (state === "SUCCESS") {
            clearInterval(intervalId);
            pollTimers.current.delete(id);
            patchItem(id, { phase: "done", progress: 100, stagePl: "Gotowe" });
            resolve();
            return;
          }

          if (state === "FAILURE") {
            clearInterval(intervalId);
            pollTimers.current.delete(id);
            patchItem(id, {
              phase: "failed",
              error: data.error || {
                message: "Przetwarzanie nie powiodło się",
                retryable: false,
              },
            });
            resolve();
            return;
          }

          patchItem(id, {
            phase: "processing",
            progress,
            stagePl: state === "RETRY" ? "Ponawianie..." : stagePl,
          });
        } catch (err) {
          clearInterval(intervalId);
          pollTimers.current.delete(id);
          patchItem(id, {
            phase: "failed",
            error: { message: err.message || "Błąd pollingu", retryable: true },
          });
          resolve();
        }
      }, POLL_INTERVAL_MS);
      pollTimers.current.set(id, intervalId);
    });
  }

  return (
    <>
      <div
        className={`mfu-dropzone dropzone ${isDragging ? "dragging" : ""} ${
          isFull ? "is-full" : ""
        }`}
        onDragOver={handleDragOver}
        onDragEnter={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        onClick={handleClickDropzone}
      >
        <div className="dropzone-plus">+</div>
        <p>
          {isFull
            ? `Osiągnięto limit ${MAX_FILES} plików`
            : `Upuść pliki tutaj (max ${MAX_FILES}) lub kliknij, aby wybrać`}
        </p>
        <p className="mfu-dropzone-hint">PDF, DOCX, XLSX · do 50 MB każdy</p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".pdf,.docx,.xlsx"
          onChange={handleFileChange}
          style={{ display: "none" }}
        />
      </div>

      <div className="mfu-actions">
        <button
          className="primary-btn"
          onClick={handleSubmit}
          disabled={queuedCount === 0 || inFlightCount > 0}
          type="button"
        >
          {inFlightCount > 0
            ? `Przetwarzanie ${inFlightCount}...`
            : `Wyślij (${queuedCount})`}
        </button>
        <span className="mfu-counter">
          {items.length}/{MAX_FILES} plików
        </span>
      </div>

      {items.length > 0 && (
        <ul className="mfu-list">
          {items.map((it) => (
            <FileRow
              key={it.id}
              item={it}
              isTagOpen={openTagFor === it.id}
              onToggleTag={() =>
                setOpenTagFor(openTagFor === it.id ? null : it.id)
              }
              onSetTag={(tag) => setItemTag(it.id, tag)}
              onRemove={() => removeItem(it.id)}
              onRetry={() => retry(it.id)}
            />
          ))}
        </ul>
      )}

      {allDone && (
        <div className="success-toast">Wszystkie pliki przetworzone ✅</div>
      )}
    </>
  );
}

function FileRow({ item, isTagOpen, onToggleTag, onSetTag, onRemove, onRetry }) {
  const { file, tag, phase, progress, stagePl, error } = item;

  const phaseLabel = (() => {
    if (phase === "queued") return "Oczekuje na wysłanie";
    if (phase === "uploading") return "Przesyłanie";
    if (phase === "processing")
      return stagePl ? `Przetwarzanie · ${stagePl}` : "Przetwarzanie";
    if (phase === "done") return "Gotowe";
    if (phase === "failed")
      return error?.message ? `Błąd: ${error.message}` : "Błąd";
    return phase;
  })();

  const showBar =
    phase === "uploading" || phase === "processing" || phase === "done";
  const indeterminate = phase === "uploading";
  const fillPct = phase === "done" ? 100 : progress;
  const canRemove =
    phase === "queued" || phase === "done" || phase === "failed";
  const retryable = phase === "failed" && error?.retryable !== false;

  return (
    <li className={`mfu-item mfu-phase-${phase}`}>
      <div className="mfu-item-head">
        <div className="file-chip mfu-chip">
          <span className="file-chip-icon">📄</span>
          <span className="mfu-filename" title={file.name}>
            {file.name}
          </span>
          <span className="mfu-filesize">
            {(file.size / 1024 / 1024).toFixed(2)} MB
          </span>
        </div>

        <div className="file-actions mfu-row-actions">
          <div className="tag-pill-wrap">
            {tag ? (
              <span className="tag-pill">{tag.toUpperCase()}</span>
            ) : (
              <span className="tag-pill is-empty">Brak tagu</span>
            )}
          </div>
          {phase === "queued" && (
            <button
              className="icon-btn"
              onClick={onToggleTag}
              title="Wybierz tag"
              type="button"
            >
              +
            </button>
          )}
          {isTagOpen && (
            <div className="tag-menu">
              {TAGS.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => onSetTag(t.value)}
                >
                  {t.label}
                </button>
              ))}
              {tag && (
                <button
                  className="danger"
                  type="button"
                  onClick={() => onSetTag("")}
                >
                  Usuń tag
                </button>
              )}
            </div>
          )}
          {retryable && (
            <button
              className="mfu-retry-btn"
              onClick={onRetry}
              type="button"
            >
              Ponów
            </button>
          )}
          <button
            className="mfu-remove-btn"
            onClick={onRemove}
            disabled={!canRemove}
            title={
              canRemove
                ? "Usuń z listy"
                : "Nie można usunąć w trakcie przetwarzania"
            }
            type="button"
            aria-label="Usuń plik"
          >
            ×
          </button>
        </div>
      </div>

      {showBar && (
        <div
          className={`mfu-progress ${indeterminate ? "is-indeterminate" : ""}`}
        >
          <div
            className="mfu-progress-fill"
            style={indeterminate ? undefined : { width: `${fillPct}%` }}
          />
        </div>
      )}

      <div className="mfu-phase-label">{phaseLabel}</div>
    </li>
  );
}
