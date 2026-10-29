import { type FormEvent, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button, ErrorBanner, Field, Input } from "@/components/ui";
import { api, ApiError } from "@/services/api";

export default function JoinTrip() {
  const nav = useNavigate();
  const [code, setCode] = useState((useParams().code ?? "").toUpperCase());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault(); setBusy(true); setError(null);
    try { nav(`/trip/${(await api.trips.join(code.trim())).id}`); }
    catch (x) { setError(x instanceof ApiError ? x.message : "Couldn't join that trip. Please try again."); setBusy(false); }
  }
  return (
    <main className="mx-auto max-w-md px-4 py-14">
      <h1 className="text-4xl">Join a trip</h1>
      <p className="mt-2 text-ink-soft">Enter the code a friend shared. It works the same whether they invited you from Telegram or the web.</p>
      <form onSubmit={submit} className="mt-8 space-y-4">
        {error && <ErrorBanner message={error} />}
        <Field label="Trip code" hint="Looks like GOA-4X7">{(id) => <Input id={id} value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} className="font-mono text-lg uppercase tracking-widest" maxLength={12} autoFocus required />}</Field>
        <Button type="submit" variant="primary" busy={busy} disabled={code.trim().length < 3} className="w-full">Join trip</Button>
      </form>
    </main>
  );
}
