import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { errorMessage, useAuth } from "../auth/AuthContext";
import { PASSWORD_COMPLEXITY_MESSAGE, isPasswordComplex } from "../auth/passwordPolicy";

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const passwordValid = password.length === 0 || isPasswordComplex(password);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!isPasswordComplex(password)) {
      // The inline hint below the password field already turns red and
      // states this — no need to duplicate it into the generic error box.
      return;
    }
    setSubmitting(true);
    try {
      await register(email, password, fullName);
      navigate("/");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <h1>Create account</h1>
        <label>
          Full name
          <input
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
            autoComplete="name"
          />
        </label>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoComplete="new-password"
          />
        </label>
        <p className={passwordValid ? "muted small" : "error-box"}>{PASSWORD_COMPLEXITY_MESSAGE}</p>
        {error && <div className="error-box">{error}</div>}
        <button type="submit" disabled={submitting}>
          {submitting ? "Creating…" : "Create account"}
        </button>
        <p className="muted">
          Already registered? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  );
}