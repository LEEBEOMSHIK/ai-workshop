"use client";

import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";

import { ApiError } from "../../shared/api/client";
import { setupOwner, type OwnerSetupRequest } from "./api";
import type { SessionUser } from "./session";

interface SetupPageProps {
  createOwner?: (request: OwnerSetupRequest) => Promise<SessionUser>;
}

export function SetupPage({ createOwner = setupOwner }: SetupPageProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const request: OwnerSetupRequest = {
      display_name: String(form.get("display_name")),
      email: String(form.get("email")),
      password: String(form.get("password")),
      password_confirmation: String(form.get("password_confirmation")),
    };

    setError(null);
    if (request.password !== request.password_confirmation) {
      setError("비밀번호가 일치하지 않습니다.");
      return;
    }

    setIsSubmitting(true);
    try {
      await createOwner(request);
      router.replace("/app/workspaces");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        setError("관리자 설정이 이미 완료되었습니다. 로그인해 주세요.");
      } else {
        setError("관리자 계정을 만들지 못했습니다. 입력값과 서버 상태를 확인해 주세요.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-shell">
      <section className="auth-card" aria-labelledby="setup-title">
        <p className="eyebrow">FIRST WORKSHOP SETUP</p>
        <h1 className="auth-title" id="setup-title">
          첫 관리자를 만듭니다.
        </h1>
        <p className="auth-copy">
          이 계정은 작업소 전체를 관리합니다. 전사 지식 공간과 개인 연구 공간도 함께
          준비됩니다.
        </p>
        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            이름
            <input
              name="display_name"
              autoComplete="name"
              maxLength={120}
              required
            />
          </label>
          <label>
            이메일
            <input name="email" type="email" autoComplete="email" required />
          </label>
          <label>
            비밀번호
            <input
              name="password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              required
            />
          </label>
          <label>
            비밀번호 확인
            <input
              name="password_confirmation"
              type="password"
              autoComplete="new-password"
              minLength={12}
              required
            />
          </label>
          <p className="auth-hint">비밀번호는 12자 이상으로 설정해 주세요.</p>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
          <button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "작업소 준비 중…" : "관리자 계정 만들기"}
          </button>
        </form>
      </section>
    </main>
  );
}
