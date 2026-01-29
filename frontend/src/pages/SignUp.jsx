import { useState } from "react";
import { useNavigate } from "react-router-dom";
import "../styles/Auth.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function SignUp({ onLogin }) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords don't match");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/auth/signup`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, email, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data?.detail || "Signup failed");
        return;
      }

      onLogin(data.access_token);
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
          <a href="/contact">Contact us</a>
        </nav>
      </header>

      <main className="auth-content">
        <div className="auth-form-wrapper">
          <h2>Sign up</h2>
          <p className="auth-subtitle">Already have an account? <a href="/login">Login</a></p>

          {error && <div className="error-message">{error}</div>}

          <form onSubmit={handleSubmit} className="auth-form">
            <div className="form-group">
              <label htmlFor="username">Username</label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="your-username"
                required
              />
            </div>

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
              <label htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </div>

            <div className="form-group">
              <label htmlFor="confirmPassword">Confirm Password</label>
              <input
                id="confirmPassword"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
            </div>

            <button type="submit" className="primary-btn" disabled={loading}>
              {loading ? "Signing up..." : "Sign up"}
            </button>
          </form>

          <div className="auth-footer">
            <p><a href="/contact">Need help?</a></p>
          </div>
        </div>
      </main>
    </div>
  );
}
