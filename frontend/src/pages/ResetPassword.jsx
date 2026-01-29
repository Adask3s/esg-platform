import { useState } from "react";
import { useNavigate } from "react-router-dom";
import "../styles/Auth.css";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export default function ResetPassword() {
  const [step, setStep] = useState("email"); 
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleRequestReset = async (e) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/auth/request-reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data?.detail || "Failed to send reset email");
        return;
      }

      setSuccess("Reset link sent to your email");
      setStep("reset");
    } catch (err) {
      setError(err.message || "An error occurred");
    } finally {
      setLoading(false);
    }
  };

  const handleResetPassword = async (e) => {
    e.preventDefault();
    setError("");
    setSuccess("");

    if (newPassword !== confirmPassword) {
      setError("Passwords don't match");
      return;
    }

    setLoading(true);

    try {
      const response = await fetch(`${API_URL}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, code, password: newPassword }),
      });

      const data = await response.json();

      if (!response.ok) {
        setError(data?.detail || "Failed to reset password");
        return;
      }

      setSuccess("Password reset successfully! Redirecting to login...");
      setTimeout(() => navigate("/login"), 2000);
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
          {step === "email" ? (
            <>
              <h2>Reset Password</h2>
              <p className="auth-subtitle">Enter your email address</p>

              {error && <div className="error-message">{error}</div>}
              {success && <div className="success-message">{success}</div>}

              <form onSubmit={handleRequestReset} className="auth-form">
                <div className="form-group">
                  <label htmlFor="email">Email</label>
                  <input
                    id="email"
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="your@email.com"
                    required
                    disabled={loading}
                  />
                </div>

                <button type="submit" className="primary-btn" disabled={loading}>
                  {loading ? "Sending..." : "Send Reset Link"}
                </button>
              </form>
            </>
          ) : (
            <>
              <h2>Reset Password</h2>
              <p className="auth-subtitle">Enter the code from your email</p>

              {error && <div className="error-message">{error}</div>}
              {success && <div className="success-message">{success}</div>}

              <form onSubmit={handleResetPassword} className="auth-form">
                <div className="form-group">
                  <label htmlFor="code">Reset Code</label>
                  <input
                    id="code"
                    type="text"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder="Enter code from email"
                    required
                    disabled={loading}
                  />
                </div>

                <div className="form-group">
                  <label htmlFor="newPassword">New Password</label>
                  <input
                    id="newPassword"
                    type="password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                    disabled={loading}
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
                    disabled={loading}
                  />
                </div>

                <button type="submit" className="primary-btn" disabled={loading}>
                  {loading ? "Resetting..." : "Reset Password"}
                </button>
              </form>

              <div className="auth-footer">
                <p><a href="/login">Back to login</a></p>
              </div>
            </>
          )}

          <div className="auth-footer">
            <p>Don't have an account? <a href="/signup">Sign up</a></p>
          </div>
        </div>
      </main>
    </div>
  );
}
