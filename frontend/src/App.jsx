import { useState } from 'react'
import viteLogo from '/vite.svg'
import './App.css'

const API_URL = import.meta.env.VITE_API_URL; 

function App() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [message, setMessage] = useState("");

  async function uploadFile() {
    if (!selectedFile) {
      setMessage("ALE DAJ PLIK!");
      return;
    }

    const formdata = new FormData();
    formdata.append("file", selectedFile);

    try {
      const response = await fetch(`${API_URL}/upload`, {
        method: "POST",
        body: formdata,
      });

      if (!response.ok) throw new Error("Błąd wysyłania pliku");

      const result = await response.json();
      setMessage(`Udało się: ${result.filename}`);
    } catch (err) {
      console.error(err);
      setMessage(" Błąd wysyłania pliku");
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
          <label htmlFor="plik" className="wybierz">Wybierz plik</label><br/>
          <input id="plik" type="file" className="miejsce" onChange={handleFileChange} />
          
          <p className="podglad">
            {selectedFile ? `Wybrano: ${selectedFile.name}` : "Nie wybrano pliku"}
          </p>

          <button onClick={uploadFile}>Wyślij do procesowania</button>
          <p>{message}</p>
        </div>
      </div>
    </>
  );
}

export default App;
