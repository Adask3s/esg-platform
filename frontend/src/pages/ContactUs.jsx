import { useState } from "react";
import "../styles/Auth.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function ContactUs() {
  const [email, setEmail] = useState("");
  const [problem, setProblem] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSuccess(false);
    setLoading(true);

    try {

      const response = await fetch(`${API_URL}/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, problem }),
      });

      if (!response.ok) {
        const data = await response.json();
        setError(data?.detail || "Failed to send message");
        return;
      }

      setSuccess(true);
      setEmail("");
      setProblem("");
    } catch (err) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-container">
      <header className="topbar">
        <div className="brand">
          E<span>S</span>G
        </div>
        <nav className="nav">
          <a href="/">Home</a>
          <a href="/login">Login</a>
          <a href="/signup">Sign up</a>
        </nav>
      </header>

      <main className="auth-content">
        <div className="auth-form-wrapper">
          <h2>Contact us</h2>
          <p className="auth-subtitle">Have a question? Let us know</p>

          {error && <div className="error-message">{error}</div>}
          {success && <div className="success-message">Message sent successfully! We'll get back to you soon.</div>}

          <form onSubmit={handleSubmit} className="auth-form">
            <div className="form-group">
              <label htmlFor="email">Email</label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="your@email.com"
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="problem">Your Problem</label>
              <textarea
                id="problem"
                value={problem}
                onChange={(e) => setProblem(e.target.value)}
                placeholder="Describe your issue..."
                rows="6"
                required
                style={{ width: "100%", padding: "12px", borderRadius: "8px", border: "1px solid #ccc", fontFamily: "inherit" }}
              />
            </div>

            <button type="submit" className="primary-btn" disabled={loading}>
              {loading ? "Sending..." : "Submit"}
            </button>
          </form>

          <div className="auth-footer">
            <p>Or <a href="/">go back home</a></p>
          </div>
        </div>
      </main>
    </div>
  );
}
