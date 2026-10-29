import { AlertCircle, Globe, Send, X } from "lucide-react";
import { type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, useEffect, useId } from "react";
import { initials } from "@/utils/format";

const cx = (...a: (string | false | null | undefined)[]) => a.filter(Boolean).join(" ");
export { cx };

// ---- Button: one primary (terracotta) per screen; everything else is quiet
type Variant = "primary" | "secondary" | "ghost" | "danger";
const variants: Record<Variant, string> = {
  primary: "bg-terracotta text-white hover:bg-terracotta-dark",
  secondary: "border border-sand-dark bg-surface text-ink hover:bg-sand-light",
  ghost: "text-lagoon hover:bg-lagoon-tint",
  danger: "border border-terracotta/40 text-terracotta hover:bg-terracotta-tint",
};
export function Button({ variant = "secondary", size = "md", busy, className, children, disabled, ...p }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md"; busy?: boolean }) {
  return (
    <button {...p} disabled={disabled || busy}
      className={cx("inline-flex items-center justify-center gap-2 rounded font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-55",
        size === "sm" ? "px-3 py-1.5 text-sm" : "px-4 py-2.5 text-[15px]", variants[variant], className)}>
      {busy ? <span className="dots">Working</span> : children}
    </button>
  );
}

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string | null; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-semibold text-ink">{label}</label>
      {children(id)}
      {error ? <p role="alert" className="text-sm text-terracotta-dark">{error}</p> : hint ? <p className="text-sm text-ink-faint">{hint}</p> : null}
    </div>
  );
}

export function Input({ className, ...p }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...p} className={cx("w-full rounded border border-sand-dark bg-surface px-3 py-2.5 text-[15px] placeholder:text-ink-faint focus:border-lagoon", className)} />;
}

const tones = {
  neutral: "bg-sand-light text-ink-soft", teal: "bg-lagoon-tint text-lagoon", terracotta: "bg-terracotta-tint text-terracotta-dark",
  olive: "bg-olive-tint text-olive", amber: "bg-amber-tint text-amber",
};
export function Badge({ tone = "neutral", children, className }: { tone?: keyof typeof tones; children: ReactNode; className?: string }) {
  return <span className={cx("inline-flex items-center gap-1 rounded-sm px-2 py-0.5 text-xs font-semibold", tones[tone], className)}>{children}</span>;
}

// ---- Avatar: initials on muted sand-tinted colours, with a tiny platform glyph where useful
const AVATAR_TONES = ["#E9DFCF", "#DCE8E4", "#EBDDD5", "#E3E6D2", "#E5DCEB", "#DDE4EC"];
export function Avatar({ name, id = 0, size = 32, via }: { name: string; id?: number; size?: number; via?: "web" | "telegram" | null }) {
  return (
    <span className="relative inline-flex shrink-0" title={name}>
      <span aria-hidden className="grid place-items-center rounded-full font-semibold text-ink"
        style={{ width: size, height: size, background: AVATAR_TONES[id % AVATAR_TONES.length], fontSize: size * 0.38 }}>{initials(name)}</span>
      {via && <PlatformGlyph via={via} className="absolute -bottom-0.5 -right-0.5 rounded-full bg-paper p-[1px]" size={Math.max(11, size * 0.38)} />}
    </span>
  );
}

export function PlatformGlyph({ via, size = 13, className }: { via: "web" | "telegram" | "system"; size?: number; className?: string }) {
  if (via === "system") return null;
  const Icon = via === "telegram" ? Send : Globe;
  return <span className={className} role="img" aria-label={via === "telegram" ? "from Telegram" : "from the web"}>
    <Icon size={size} className={via === "telegram" ? "text-[#2A8BB6]" : "text-ink-faint"} aria-hidden /></span>;
}

export const Skeleton = ({ className }: { className?: string }) => <div aria-hidden className={cx("skeleton h-4", className)} />;

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mx-auto max-w-md py-12 text-center">
      <svg aria-hidden viewBox="0 0 80 40" className="mx-auto mb-4 h-10 text-sand-dark" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
        <path d="M4 30c14-24 24 8 38-6s22-12 34-16" strokeDasharray="1 7" /><circle cx="76" cy="8" r="3.5" fill="currentColor" stroke="none" /></svg>
      <h3 className="text-xl">{title}</h3>
      {children && <p className="mt-2 text-ink-soft">{children}</p>}
      {action && <div className="mt-5 flex justify-center gap-3">{action}</div>}
    </div>
  );
}

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-3 rounded border border-terracotta/30 bg-terracotta-tint px-4 py-3 text-sm text-terracotta-dark">
      <AlertCircle size={18} className="mt-0.5 shrink-0" aria-hidden />
      <p className="flex-1">{message}</p>
      {onRetry && <button onClick={onRetry} className="font-semibold underline underline-offset-2">Try again</button>}
    </div>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 grid place-items-end bg-ink/40 sm:place-items-center" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md animate-rise rounded-t-lg bg-surface p-6 shadow-pop sm:rounded-lg">
        <div className="mb-4 flex items-center justify-between"><h2 className="text-xl">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-ink-soft hover:bg-sand-light"><X size={18} /></button></div>
        {children}
      </div>
    </div>
  );
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return <div className="mb-3 flex items-baseline justify-between gap-3"><h2 className="text-xl">{children}</h2>{aside}</div>;
}
