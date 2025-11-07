import { useState } from "react";
import viteLogo from "/vite.svg";
import "./App.css";

const API_URL = import.meta.env.VITE_API_URL;

function App() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [message, setMessage] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [isCompleted, setIsCompleted] = useState(false);

  async function uploadFile() {
    if (!selectedFile) {
      setMessage("ALE DAJ PLIK!");
      return;
    }

    const formdata = new FormData();
    formdata.append("file", selectedFile);

    try {
      setIsLoading(true);
      setIsCompleted(false);
      const response = await fetch(`${API_URL}/process`, {
        method: "POST",
        body: formdata,
      });

      if (!response.ok) throw new Error("Błąd wysyłania pliku");
      const result = await response.json();

      setMessage(`Zadanie #${result.task_id} rozpoczęte...`);
      checkStatus(result.task_id);
    } catch (err) {
      console.error(err);
      setMessage("Błąd wysyłania pliku");
      setIsLoading(false);
    }
  }

  async function checkStatus(taskId) {
    try {
      const resp = await fetch(`${API_URL}/status/${taskId}`);
      const data = await resp.json();

      if (data.status === "in_progress") {
        setMessage(`Status zadania ${taskId}: ${data.status}`);
        setTimeout(() => checkStatus(taskId), 2000);
      } else if (data.status.startsWith("error")) {
        setMessage(`Błąd przetwarzania: ${data.status}`);
        setIsLoading(false);
      } else {
        setMessage(`Status zadania ${taskId}: ${data.status}`);
        setIsLoading(false);
        setIsCompleted(true);
      }
    } catch (err) {
      console.error(err);
      setMessage("Błąd sprawdzania statusu");
      setIsLoading(false);
    }
  }

  function handleFileChange(event) {
    const file = event.target.files[0];
    setSelectedFile(file);
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
          <label htmlFor="plik" className="wybierz">
            Wybierz plik
          </label>
          <br />
          <input
            id="plik"
            type="file"
            className="miejsce"
            onChange={handleFileChange}
          />

          <p className="podglad">
            {selectedFile
              ? `Wybrano: ${selectedFile.name}`
              : "Nie wybrano pliku"}
          </p>

          <button onClick={uploadFile}>Wyślij do procesowania</button>
          {isLoading && <div className="loader"></div>}
          {isCompleted && (
            <div className="success-toast">
              Plik został poprawnie przetworzony! ✅
            </div>
          )}
          <p>{message}</p>
        </div>
      </div>
    </>
  );
}

export default App;
