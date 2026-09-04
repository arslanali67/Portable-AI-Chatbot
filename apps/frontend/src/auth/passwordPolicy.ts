// Mirrors the backend's password complexity rule exactly
// (app/schemas/auth.py's _validate_password_complexity) — at least one
// uppercase letter and one special (non-alphanumeric) character, on top
// of the existing minLength=8 already enforced by the input itself.

export const PASSWORD_COMPLEXITY_MESSAGE =
  "Password must contain at least one uppercase letter and one special character";

export function isPasswordComplex(password: string): boolean {
  return /[A-Z]/.test(password) && /[^a-zA-Z0-9]/.test(password);
}
