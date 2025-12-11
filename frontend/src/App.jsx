import { useState, useEffect, useRef } from "react";
import viteLogo from "/vite.svg";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL;

function App() {
  // Gasowski: stan dla wielu plików + DnD
  const [selectedFiles, setSelectedFiles] = useState([]); // Gasowski
  const [isDragging, setIsDragging] = useState(false); // Gasowski
  const inputRef = useRef(null); // Gasowski: referencja do ukrytego inputa

  const [message, setMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isCompleted, setIsCompleted] = useState(false);

  const [fileStatuses, setFileStatuses] = useState({});// status plikow
  const [perFileTags, setPerFileTags] = useState({});
  const [openTagDropdownFor, setOpenTagDropdownFor] = useState(null);
  // Gasowski: pomocnicze, by przeglądarka nie otwierała plików
  function preventDefaults(e) {
    e.preventDefault();
    e.stopPropagation();
  }

  // Gasowski: obsługa DnD
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
    setSelectedFiles(dropped.slice(0, 10)); // Gasowski: limit 10 po stronie frontu
  }

  // Gasowski: globalne wyłączenie domyślnego zachowania dla drag&drop (żeby przeglądarka nie otwierała plików)
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

  // Gasowski: wybór plików przez input
  function handleFileChange(event) {
    const files = Array.from(event.target.files || []);
    setSelectedFiles(files.slice(0, 10)); // Gasowski
  }

  // Gasowski: upload wielu plików do /parse
  async function uploadFiles() {
    if (!selectedFiles.length) {
      setMessage("ALE DAJ PLIK!");
      return;
    }

    const formdata = new FormData();
    for (const f of selectedFiles) formdata.append("files", f); // Gasowski

    try {
      setIsLoading(true);
      setIsCompleted(false);
      const response = await fetch(`${API_URL}/parse`, {
        method: "POST",
        body: formdata,
      });

      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || "Błąd wysyłania plików");

      const taskIds=[];
      for (const f of selectedFiles){
        const res=await processFile(f);
        setStatus(f.name, "QUEUED");
        const taskId=res.task_id;
        taskIds.push(taskId);

        const interval=setInterval(async()=>{
          const st= await checkStatus(taskId);
          setStatus(f.name, st.state);
          if (st.state === "SUCCESS") {
            clearInterval(interval);
            const fileTag = perFileTags[f.name];
            if (fileTag && st.result?.output_dir) {
              await runESGAnalysis(st.result.output_dir, fileTag, f.name);
            }
          }
          if (st.state === "FAILURE") {
            clearInterval(interval);
          }
        },2000);}
      setMessage(`zadanka w celery ${taskIds.join(", ")}`)

      setIsCompleted(true);
    } catch (err) {
      console.error(err);
      setMessage(err?.message || "Błąd wysyłania plików");
      setIsLoading(false);
    } finally {
      setIsLoading(false);
    }
  }

  async function processFile(file) {
    const formdata= new FormData();
    formdata.append("file",file);
    
    const response=await fetch(`${API_URL}/process`,{
      method:"POST",
      body:formdata,
    });

    const data= await response.json();
    if(!response.ok) throw new Error(data?.detail || "blad process");
    return data;
  }

  async function checkStatus(taskId){
    const response= await fetch(`${API_URL}/status/${taskId}`);
    const data= await response.json();
    return data;
  }

  //helper do statusu (zmienia stanu)
  function setStatus(filename, status) {
  setFileStatuses(prev => ({
    ...prev,
    [filename]: status
  }));
}

  async function runESGAnalysis(outputDir, tag, filename) {
    try {
      setStatus(filename, `ESG: ${tag.toUpperCase()}...`);
      const endpoint = tag === "social" 
        ? "/analyze-social"
        : tag === "environmental"
        ? "/analyze-environmental"
        : "/analyze-governance";
      const response = await fetch(`${API_URL}${endpoint}?report_path=${encodeURIComponent(outputDir)}`, {
        method: "POST",
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data?.detail || "Błąd analizy ESG");
      setStatus(filename, `✅ ESG: ${tag.toUpperCase()} done`);
      console.log(`ESG Analysis (${tag}) result:`, data);
    } catch (err) {
      console.error(`ESG Analysis error (${tag}):`, err);
      setStatus(filename, `❌ ESG: ${tag.toUpperCase()} failed`);
    }
  }


  return (
    <>
      <div>
        <a href="https://vite.dev" target="_blank">
          <img src={viteLogo} className="logo" alt="Vite logo" />
        </a>
      </div>

      <div>
        <h1>Platforma ETG</h1>
        <div className="uploadContainer">
          {/* Gasowski: strefa DnD */}
          <div
            className={`dropzone ${isDragging ? "dragging" : ""}`}
            onDragOver={handleDragOver}
            onDragEnter={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()} // Gasowski: klik w strefę otwiera dialog
          >
            <p>Upuść pliki tutaj (max 10) lub kliknij, aby wybrać</p>
            <input
              ref={inputRef}
              id="plik"
              type="file"
              className="miejsce"
              multiple // Gasowski
              onChange={handleFileChange}
              style={{ display: "none" }}
            />
          </div>

          <p className="podglad">
            {selectedFiles.length
              ? `Wybrano: ${selectedFiles.map((f) => f.name).join(", ")}`
              : "Nie wybrano plików"}
          </p>
          {selectedFiles.map((file) => (
            <div key={file.name} style={{ marginTop: "8px", display: "flex", alignItems: "center", gap: "8px", position: "relative" }}>
              <div style={{ flex: 1 }}>
                <strong>{file.name}</strong> — {fileStatuses[file.name] || "oczekuje…"}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <div style={{ minWidth: 140 }}>
                  {perFileTags[file.name] ? (
                    <span style={{ padding: "4px 8px", background: "#e8f5e9", borderRadius: 4 }}>
                      {perFileTags[file.name].toUpperCase()}
                    </span>
                  ) : (
                    <span style={{ padding: "4px 8px", background: "#f1f1f1", borderRadius: 4 }}>
                      No tag
                    </span>
                  )}
                </div>
                <button
                  onClick={() => setOpenTagDropdownFor(openTagDropdownFor === file.name ? null : file.name)}
                  style={{ padding: "6px 8px", borderRadius: "50%", border: "none", background: "#2196F3", color: "white", cursor: "pointer" }}
                  title="Wybierz tag dla tego pliku"
                >
                  +
                </button>
              </div>
              {openTagDropdownFor === file.name && (
                <div style={{ position: "absolute", right: 0, top: "32px", padding: 8, border: "1px solid #ccc", background: "white", borderRadius: 6, zIndex: 1000 }}>
                  <button onClick={() => { setPerFileTags(prev => ({ ...prev, [file.name]: "social" })); setOpenTagDropdownFor(null); }} style={{ display: "block", width: "100%", padding: "8px", margin: "4px 0", cursor: "pointer", background: "#2196F3", color: "white", border: "none", borderRadius: "4px", fontSize: "14px" }}>Social (S)</button>
                  <button onClick={() => { setPerFileTags(prev => ({ ...prev, [file.name]: "environmental" })); setOpenTagDropdownFor(null); }} style={{ display: "block", width: "100%", padding: "8px", margin: "4px 0", cursor: "pointer", background: "#2196F3", color: "white", border: "none", borderRadius: "4px", fontSize: "14px" }}>Environmental (E)</button>
                  <button onClick={() => { setPerFileTags(prev => ({ ...prev, [file.name]: "governance" })); setOpenTagDropdownFor(null); }} style={{ display: "block", width: "100%", padding: "8px", margin: "4px 0", cursor: "pointer", background: "#2196F3", color: "white", border: "none", borderRadius: "4px", fontSize: "14px" }}>Governance (G)</button>
                  <button onClick={() => { setPerFileTags(prev => { const copy = { ...prev }; delete copy[file.name]; return copy; }); setOpenTagDropdownFor(null); }} style={{ display: "block", width: "100%", padding: "8px", margin: "4px 0", cursor: "pointer", background: "#f44336", color: "white", border: "none", borderRadius: "4px", fontSize: "14px" }}>Usuń tag</button>
                </div>
              )}
            </div>
          ))}
          <button onClick={uploadFiles}>Wyślij do procesowania</button>
          {isLoading && <div className="loader"></div>}
          {isCompleted && (
            <div className="success-toast">Pliki zostały przetworzone! ✅</div>
          )}
          <p>{message}</p>
        </div>
      </div>
    </>
  );
}

export default App;
