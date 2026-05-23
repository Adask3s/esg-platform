import { useState } from "react";
import { Routes, Route, useNavigate, Navigate } from "react-router-dom";
import "./App.css";
import Dashboard from "./pages/Dashboard";
import AIReports from "./pages/AIReports";
import Login from "./pages/Login";
import SignUp from "./pages/SignUp";
import ContactUs from "./pages/ContactUs";
import ResetPassword from "./pages/ResetPassword";
import AdminPanel from "./pages/AdminPanel";
import { parseUserFromToken } from "./lib/authToken";

function App() {
  const navigate = useNavigate();
  const [user, setUser] = useState(() => parseUserFromToken(localStorage.getItem("token")));

  const handleLogin = (token) => {
    localStorage.setItem("token", token);
    setUser(parseUserFromToken(token));
    navigate("/");
  };

  const handleLogout = () => {
    localStorage.removeItem("token");
    setUser(null);
    navigate("/");
  };

  return (
    <Routes>
      <Route path="/" element={<Dashboard user={user} onLogout={handleLogout} />} />
      <Route path="/aireports" element={<AIReports />} />
      <Route
        path="/admin"
        element={user?.role === "admin" ? <AdminPanel user={user} /> : <Navigate to="/" replace />}
      />
      <Route path="/login" element={<Login onLogin={handleLogin} />} />
      <Route path="/signup" element={<SignUp onLogin={handleLogin} />} />
      <Route path="/contact" element={<ContactUs />} />
      <Route path="/reset-password" element={<ResetPassword />} />
    </Routes>
  );
}

export default App;
