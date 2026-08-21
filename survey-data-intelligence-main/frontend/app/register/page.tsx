"use client";

import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";
import { Eye, EyeOff, ArrowLeft } from "lucide-react";
import { InstitutionalMark } from "@/components/brand/institutional-mark";
import { ApiError, register } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const nameId = useId();
  const usernameId = useId();
  const passwordId = useId();
  const confirmId = useId();
  const errorId = useId();
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    setError(null);
    const cleanUsername = username.trim();
    const cleanName = displayName.trim();
    if (cleanUsername.length < 3) { setError("Username must be at least 3 characters."); return; }
    if (password.length < 6) { setError("Password must be at least 6 characters."); return; }
    if (password !== confirmPassword) { setError("Passwords do not match."); return; }
    setSubmitting(true);
    try {
      await register(cleanUsername, password, cleanName);
      router.replace(`/login?registered=1`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setError("That username is already registered. Please choose another.");
      else if (err instanceof ApiError && err.status === 422) setError("Please check the details and try again.");
      else setError("We couldn't create your account right now. Please try again.");
      setSubmitting(false);
    }
  }

  return (
    <div className="sv-portal min-h-screen w-full lg:grid lg:grid-cols-2">
      <section className="relative hidden overflow-hidden bg-inst-navy px-12 py-14 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="absolute inset-x-0 top-0 flex h-1.5" aria-hidden="true"><span className="w-1/3 bg-inst-saffron" /><span className="w-1/3 bg-white" /><span className="w-1/3 bg-inst-green" /></div>
        <div className="sv-login-grid" aria-hidden="true" /><div className="sv-login-motif" aria-hidden="true" />
        <div className="relative">
          <InstitutionalMark className="h-[5.5rem] w-[5.5rem]" />
          <p className="mt-9 text-[0.7rem] font-semibold uppercase tracking-[0.2em] text-white/80">Survey Data Intelligence</p>
          <h1 className="mt-3 max-w-md font-display text-[2.05rem] font-semibold leading-snug">Official Statistics &amp; Survey Quality</h1>
          <p className="mt-6 max-w-sm text-[0.95rem] leading-7 text-white/80">Create your secure supervisor account and start reviewing survey quality data.</p>
        </div>
        <p className="relative text-[0.72rem] leading-5 text-white/75">Project identity for survey quality review · Not an official government service</p>
      </section>

      <section className="flex min-h-screen flex-col justify-center px-6 py-12 sm:px-10 lg:px-12 xl:px-16">
        <div className="mx-auto w-full max-w-[36rem]">
          <div className="mb-8 flex items-center gap-3 lg:hidden"><InstitutionalMark className="h-14 w-14" /><div><p className="text-[0.7rem] font-semibold uppercase tracking-[0.18em] text-inst-text-secondary">Survey Data Intelligence</p><p className="text-sm text-inst-text">Official Statistics &amp; Survey Quality</p></div></div>
          <button type="button" className="mb-7 inline-flex items-center gap-2 text-sm font-semibold text-inst-navy hover:underline" onClick={() => router.push("/login")}><ArrowLeft className="h-4 w-4" /> Back to sign in</button>
          <p className="text-[0.72rem] font-semibold uppercase tracking-[0.2em] text-inst-navy/80">Supervisor Portal</p>
          <h2 className="mt-3 font-sans text-[2.25rem] font-semibold tracking-tight text-inst-navy">Create account</h2>
          <p className="mt-3 text-[1rem] leading-6 text-inst-text-secondary">Create a new user record for the Survey Data Intelligence platform.</p>

          <form className="mt-8 space-y-4" onSubmit={handleSubmit}>
            <div><label htmlFor={nameId} className="text-sm font-medium text-inst-text">Display name <span className="text-inst-text-secondary">(optional)</span></label><input id={nameId} className="sv-input mt-1.5" value={displayName} onChange={e=>setDisplayName(e.target.value)} autoComplete="name" disabled={submitting} placeholder="Your name" /></div>
            <div><label htmlFor={usernameId} className="text-sm font-medium text-inst-text">Username</label><input id={usernameId} className="sv-input mt-1.5" value={username} onChange={e=>setUsername(e.target.value)} autoComplete="username" autoCapitalize="none" spellCheck={false} disabled={submitting} placeholder="Choose a username" /></div>
            <div><label htmlFor={passwordId} className="text-sm font-medium text-inst-text">Password</label><div className="relative mt-1.5"><input id={passwordId} className="sv-input pr-12" type={showPassword ? "text" : "password"} value={password} onChange={e=>setPassword(e.target.value)} autoComplete="new-password" disabled={submitting} placeholder="At least 6 characters" /><button type="button" className="absolute inset-y-0 right-0 flex items-center px-3 text-inst-text-secondary hover:text-inst-navy" onClick={()=>setShowPassword(v=>!v)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword?<EyeOff className="h-4 w-4"/>:<Eye className="h-4 w-4"/>}</button></div></div>
            <div><label htmlFor={confirmId} className="text-sm font-medium text-inst-text">Confirm password</label><div className="relative mt-1.5"><input id={confirmId} className="sv-input pr-12" type={showConfirm ? "text" : "password"} value={confirmPassword} onChange={e=>setConfirmPassword(e.target.value)} autoComplete="new-password" disabled={submitting} /><button type="button" className="absolute inset-y-0 right-0 flex items-center px-3 text-inst-text-secondary hover:text-inst-navy" onClick={()=>setShowConfirm(v=>!v)} aria-label={showConfirm ? "Hide password" : "Show password"}>{showConfirm?<EyeOff className="h-4 w-4"/>:<Eye className="h-4 w-4"/>}</button></div></div>
            {error ? <p id={errorId} className="sv-alert-critical" role="alert">{error}</p> : null}
            <button className="sv-btn-primary" type="submit" disabled={submitting}>{submitting ? "Creating account..." : "Create account"}</button>
          </form>

          <p className="mt-7 text-center text-sm text-inst-text-secondary">Already have an account? <button type="button" className="font-semibold text-inst-blue hover:underline" onClick={()=>router.push("/login")}>Sign in</button></p>
          <p className="mt-7 flex items-center justify-center gap-2 text-[0.9375rem] font-medium text-inst-navy/85"><span className="h-1.5 w-1.5 shrink-0 rounded-full bg-inst-blue" />New accounts are created with the Field Supervisor role.</p>
        </div>
      </section>
    </div>
  );
}
