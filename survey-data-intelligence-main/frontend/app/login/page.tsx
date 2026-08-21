"use client";

import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";
import { Eye, EyeOff } from "lucide-react";
import { AccessInfoTooltip } from "@/components/ui/access-info-tooltip";
import { InstitutionalMark } from "@/components/brand/institutional-mark";
import { ApiError, getMe, login } from "@/lib/api";
import { writeSession } from "@/lib/auth";

function signInErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) {
    return "The username or password you entered is incorrect.";
  }
  return "We couldn't sign you in right now. Please try again.";
}

export default function LoginPage() {
  const router = useRouter();
  const usernameId = useId();
  const passwordId = useId();
  const errorId = useId();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signIn() {
    if (submitting) return;
    setError(null);
    const user = username.trim();
    if (!user || !password) {
      setError("The username or password you entered is incorrect.");
      return;
    }
    setSubmitting(true);
    try {
      await login(user, password);
      const me = await getMe();
      writeSession({
        username: me.username,
        role: me.role,
        display_name: me.display_name,
        demo: me.demo,
      });
      router.replace("/dashboard");
    } catch (err) {
      setError(signInErrorMessage(err));
      setSubmitting(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    event.stopPropagation();
    void signIn();
  }

  return (
    <div className="sv-portal min-h-screen w-full lg:grid lg:grid-cols-2">
      <section className="relative hidden overflow-hidden bg-inst-navy px-12 py-14 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute inset-x-0 top-0 flex h-1.5" aria-hidden="true">
          <span className="w-1/3 bg-inst-saffron" />
          <span className="w-1/3 bg-white" />
          <span className="w-1/3 bg-inst-green" />
        </div>
        <div className="sv-login-grid" aria-hidden="true" />
        <div className="sv-login-motif" aria-hidden="true" />
        <div className="relative">
          <InstitutionalMark className="h-[5.5rem] w-[5.5rem]" />
          <p className="mt-9 text-[0.7rem] font-semibold uppercase tracking-[0.2em] text-white/80">
            Survey Data Intelligence
          </p>
          <h1 className="mt-3 max-w-md font-display text-[2.05rem] font-semibold leading-snug">
            Official Statistics &amp; Survey Quality
          </h1>
          <p className="mt-6 max-w-sm font-sans text-[0.95rem] leading-7 text-white/80">
            Trusted data. Better decisions.
          </p>
        </div>
        <p className="relative text-[0.72rem] leading-5 text-white/75">
          Project identity for survey quality review · Not an official government service
        </p>
      </section>

      <section className="flex min-h-screen flex-col justify-center px-6 py-16 sm:px-10 lg:px-12 xl:px-16">
        <div className="mx-auto w-full max-w-[36rem]">
          <div className="mb-10 flex items-center gap-3 lg:hidden">
            <InstitutionalMark className="h-14 w-14" />
            <div>
              <p className="text-[0.7rem] font-semibold uppercase tracking-[0.18em] text-inst-text-secondary">
                Survey Data Intelligence
              </p>
              <p className="text-sm text-inst-text">Official Statistics &amp; Survey Quality</p>
            </div>
          </div>
          <p className="text-[0.72rem] font-semibold uppercase tracking-[0.2em] text-inst-navy/80">Supervisor Portal</p>
          <h2 className="mt-3 font-sans text-[2.25rem] font-semibold tracking-tight text-inst-navy">Sign in</h2>
          <p className="mt-3 text-[1rem] leading-6 text-inst-text-secondary">
            Access the Survey Data Intelligence platform.
          </p>

          <form className="mt-10 space-y-5" method="post" onSubmit={handleSubmit}>
            <div>
              <label htmlFor={usernameId} className="text-sm font-medium text-inst-text">
                Username
              </label>
              <input
                id={usernameId}
                className="sv-input mt-1.5"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                autoComplete="username"
                autoCapitalize="none"
                spellCheck={false}
                disabled={submitting}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? errorId : undefined}
              />
            </div>
            <div>
              <label htmlFor={passwordId} className="text-sm font-medium text-inst-text">
                Password
              </label>
              <div className="relative mt-1.5">
                <input
                  id={passwordId}
                  className="sv-input pr-12"
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  disabled={submitting}
                  aria-invalid={Boolean(error)}
                  aria-describedby={error ? errorId : undefined}
                />
                <button
                  type="button"
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-inst-text-secondary hover:text-inst-navy"
                  onClick={() => setShowPassword((value) => !value)}
                  aria-pressed={showPassword}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? <EyeOff className="h-4 w-4" aria-hidden="true" /> : <Eye className="h-4 w-4" aria-hidden="true" />}
                </button>
              </div>
            </div>
            {error ? (
              <p id={errorId} className="sv-alert-critical" role="alert">
                {error}
              </p>
            ) : null}
            <button className="sv-btn-primary" type="submit" disabled={submitting} aria-busy={submitting}>
              {submitting ? "Signing in..." : "Sign in"}
            </button>
          </form>

          <div className="mt-7 border-t border-inst-border pt-6 text-center">
            <p className="text-sm text-inst-text-secondary">New to Survey Data Intelligence?</p>
            <button
              type="button"
              className="mt-2 text-sm font-semibold text-inst-blue hover:underline"
              onClick={() => router.push("/register")}
            >
              Create a new account
            </button>
          </div>

          <p className="mt-10 flex items-center gap-2 text-[0.9375rem] font-medium text-inst-navy/85">
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-inst-blue" aria-hidden="true" />
            <span>Authorized personnel only</span>
            <AccessInfoTooltip />
          </p>
        </div>
      </section>
    </div>
  );
}
