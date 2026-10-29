import { type FormEvent, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { Button, ErrorBanner, Field, Input } from "@/components/ui";
import { ApiError } from "@/services/api";
import { useAuth } from "@/store/auth";

function useAuthForm(run: () => Promise<void>) {
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/trips";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try { await run(); nav(from, { replace: true }); } catch (x) { setError(x instanceof ApiError ? x : new ApiError("Something went wrong. Please try again.", "error", 0)); } finally { setBusy(false); }
  }
  return { submit, busy, error, fieldError: (f: string) => error?.fields.find((x) => x.field === f)?.issue ?? null };
}

function Frame({ title, sub, children, foot }: { title: string; sub: string; children: React.ReactNode; foot: React.ReactNode }) {
  return (
    <main className="mx-auto max-w-md px-4 py-14">
      <h1 className="text-4xl">{title}</h1><p className="mt-2 text-ink-soft">{sub}</p>
      <div className="mt-8">{children}</div><p className="mt-6 text-ink-soft">{foot}</p>
    </main>
  );
}

export function Login() {
  const { login, status } = useAuth();
  const [email, setEmail] = useState(""), [password, setPassword] = useState("");
  const f = useAuthForm(() => login(email, password));
  if (status === "authed") return <Navigate to="/trips" replace />;
  return (
    <Frame title="Welcome back" sub="Sign in to pick up where the group left off." foot={<>New here? <Link className="font-semibold text-lagoon underline" to="/register">Create an account</Link></>}>
      <form onSubmit={f.submit} className="space-y-4" noValidate>
        {f.error && !f.error.fields.length && <ErrorBanner message={f.error.message} />}
        <Field label="Email" error={f.fieldError("email")}>{(id) => <Input id={id} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
        <Field label="Password" error={f.fieldError("password")}>{(id) => <Input id={id} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
        <Button type="submit" variant="primary" busy={f.busy} className="w-full">Sign in</Button>
      </form>
    </Frame>
  );
}

export function Register() {
  const { register, status } = useAuth();
  const [name, setName] = useState(""), [email, setEmail] = useState(""), [password, setPassword] = useState("");
  const f = useAuthForm(() => register(name, email, password));
  if (status === "authed") return <Navigate to="/trips" replace />;
  return (
    <Frame title="Start planning" sub="One account works on every trip you join." foot={<>Already have an account? <Link className="font-semibold text-lagoon underline" to="/login">Sign in</Link></>}>
      <form onSubmit={f.submit} className="space-y-4" noValidate>
        {f.error && !f.error.fields.length && <ErrorBanner message={f.error.message} />}
        <Field label="Your name" hint="This is how your friends see you in the chat." error={f.fieldError("name")}>{(id) => <Input id={id} autoComplete="name" required value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />}</Field>
        <Field label="Email" error={f.fieldError("email")}>{(id) => <Input id={id} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
        <Field label="Password" hint="At least 8 characters." error={f.fieldError("password")}>{(id) => <Input id={id} type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
        <Button type="submit" variant="primary" busy={f.busy} className="w-full">Create account</Button>
      </form>
    </Frame>
  );
}
