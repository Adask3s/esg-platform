import { useState } from "react";
import "../styles/Auth.css";

export default function ResetPassword() {
  const [step, setStep] = useState("email"); 
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(false);

  const handleRequestReset = async (e) => {
    e.preventDefault();
    setError("");
    setSuccess("");
    setLoading(true);

    try {
      setSuccess("Password reset is not connected in the backend yet. Use the contact form for support.");
      setStep("email");
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
      setSuccess("Password reset is not connected in the backend yet. Use the contact form for support.");
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
          <a href="/privacy">Privacy</a>
        </nav>
      </header>

      <main className="auth-content">
        <div className="auth-form-wrapper">
          {step === "email" ? (
            <>
              <h2>Reset Password</h2>
              <p className="auth-subtitle">Password reset is not automated yet. Use contact support.</p>

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
                  {loading ? "Please wait..." : "Continue"}
                </button>
              </form>
            </>
          ) : (
            <>
              <h2>Reset Password</h2>
              <p className="auth-subtitle">Password reset is not automated yet. Use contact support.</p>

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
                  {loading ? "Please wait..." : "Reset Password"}
                </button>
              </form>

              <div className="auth-footer">
                <p><a href="/contact">Contact support</a> | <a href="/login">Back to login</a> | <a href="/privacy">Privacy</a></p>
              </div>
            </>
          )}

          <div className="auth-footer">
            <p>Don't have an account? <a href="/signup">Sign up</a> | <a href="/privacy">Privacy</a></p>
          </div>
        </div>
      </main>
    </div>
  );
}
