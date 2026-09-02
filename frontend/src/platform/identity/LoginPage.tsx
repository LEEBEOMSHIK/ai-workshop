import { type FormEvent, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { login } from "./api";
import type { SessionUser } from "./session";

interface LoginPageProps {
  authenticate?: (email: string, password: string) => Promise<SessionUser>;
}

export function LoginPage({ authenticate = login }: LoginPageProps) {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError(null);
    setIsSubmitting(true);
    try {
      const authenticated = await authenticate(
        String(form.get("email")),
        String(form.get("password")),
      );
      setUser(authenticated);
      navigate(safeReturnPath(searchParams.get("next")), { replace: true });
    } catch {
      setError("이메일 또는 비밀번호를 확인해 주세요.");
    } finally {
      setIsSubmitting(false);
    }
  }

  if (user) {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <p className="eyebrow">AUTHENTICATED</p>
          <h1 className="auth-title">{user.display_name}님, 환영합니다.</h1>
          <a className="primary-link" href="/">
            작업소 둘러보기
          </a>
        </section>
      </main>
    );
  }

  return (
    <main className="auth-shell">
      <section className="auth-card" aria-labelledby="login-title">
        <p className="eyebrow">PRIVATE WORKSHOP</p>
        <h1 className="auth-title" id="login-title">
          다시 오셨군요.
        </h1>
        <p className="auth-copy">소유자 계정으로 로컬 작업소에 입장합니다.</p>
        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            이메일
            <input name="email" type="email" autoComplete="email" required />
          </label>
          <label>
            비밀번호
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </label>
          {error ? <p className="form-error">{error}</p> : null}
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "확인 중…" : "작업소 입장"}
          </button>
        </form>
      </section>
    </main>
  );
}

function safeReturnPath(candidate: string | null): string {
  if (!candidate?.startsWith("/") || candidate.startsWith("//")) return "/workspaces";
  return candidate;
}
