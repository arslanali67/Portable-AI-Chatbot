import { useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import { errorMessage } from "../auth/AuthContext";
import { PASSWORD_COMPLEXITY_MESSAGE, isPasswordComplex } from "../auth/passwordPolicy";

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token");

  const [newPassword, setNewPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const passwordValid = newPassword.length === 0 || isPasswordComplex(newPassword);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!token) return;
    setError(null);
    if (!isPasswordComplex(newPassword)) {
      // The inline hint below the password field already turns red and
      // states this — no need to duplicate it into the generic error box.
      return;
    }
    setSubmitting(true);
    try {
      await api.confirmPasswordReset(token, newPassword);
      setSubmitted(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-page">
      <form className="auth-card" onSubmit={onSubmit}>
        <h1>Reset password</h1>
        {!token ? (
          <div className="error-box">Missing reset token. Use the link from your email.</div>
        ) : submitted ? (
          <p className="muted">
            Password updated. <Link to="/login">Sign in</Link>
          </p>
        ) : (
          <>
            <label>
              New password
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={8}
                autoComplete="new-password"
              />
            </label>
            <p className={passwordValid ? "muted small" : "error-box"}>{PASSWORD_COMPLEXITY_MESSAGE}</p>
            {error && <div className="error-box">{error}</div>}
            <button type="submit" disabled={submitting}>
              {submitting ? "Resetting…" : "Reset password"}
            </button>
          </>
        )}
        <p className="muted">
          <Link to="/login">Back to sign in</Link>
        </p>
      </form>
    </div>
  );
}
