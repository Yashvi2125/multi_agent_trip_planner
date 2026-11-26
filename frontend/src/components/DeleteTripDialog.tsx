import { useMutation, useQueryClient } from "@tanstack/react-query";
import { MessageSquare, ListChecks, Map, TriangleAlert, Users, X } from "lucide-react";
import { useEffect } from "react";
import { createPortal } from "react-dom";
import { useToast } from "../context/Toast";
import { api, errorMessage } from "../lib/api";
import type { TripSummary } from "../lib/types";
import { Spinner } from "./ui";

const CONSEQUENCES = [
  { icon: Users, label: "Members & their preferences" },
  { icon: MessageSquare, label: "Group chat history" },
  { icon: Map, label: "All generated itineraries" },
  { icon: ListChecks, label: "Checklist for everyone" },
];

/** Confirmation dialog + delete request, shared by Overview and My Trips. */
export function DeleteTripDialog({ trip, onClose }: { trip: TripSummary; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const del = useMutation({
    mutationFn: (tripId: number) => api(`/api/trips/${tripId}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["trips"] });
      toast.success("Trip deleted successfully.");
      onClose();
    },
    onError: (err) => {
      toast.error(errorMessage(err));
    },
  });

  // Escape to close + lock page scroll while open
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !del.isPending) onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose, del.isPending]);

  // Portal to <body> so the overlay covers the whole screen (incl. sidebar),
  // not just the page container it is rendered inside.
  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex animate-fade-in items-center justify-center p-4"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="delete-trip-title"
      aria-describedby="delete-trip-desc"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !del.isPending) onClose();
      }}
    >
      <div className="relative w-full max-w-md animate-fade-up overflow-hidden rounded-3xl bg-white shadow-[0_24px_70px_-12px_rgba(14,27,48,0.45)] ring-1 ring-ink-900/10">
        <div className="h-1.5 w-full bg-coral-500" aria-hidden />

        <button
          type="button"
          aria-label="Close"
          disabled={del.isPending}
          onClick={onClose}
          className="absolute right-4 top-5 rounded-full p-1.5 text-ink-500 transition-colors hover:bg-sand-100 hover:text-ink-900 disabled:opacity-50"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="p-6 sm:p-7">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-coral-100 text-coral-700">
            <TriangleAlert className="h-6 w-6" aria-hidden />
          </div>

          <h3 id="delete-trip-title" className="mt-4 text-xl font-bold text-ink-900">
            Delete this trip?
          </h3>
          <p id="delete-trip-desc" className="mt-1.5 text-sm leading-relaxed text-ink-700">
            You’re about to permanently delete{" "}
            <strong className="font-semibold text-ink-900">“{trip.name}”</strong>. This can’t be undone.
          </p>

          <div className="mt-4 rounded-2xl border border-coral-500/20 bg-coral-100/50 p-4">
            <p className="text-xs font-bold uppercase tracking-wider text-coral-700">This will remove for everyone</p>
            <ul className="mt-2.5 space-y-2">
              {CONSEQUENCES.map(({ icon: Icon, label }) => (
                <li key={label} className="flex items-center gap-2.5 text-sm text-ink-700">
                  <Icon className="h-4 w-4 shrink-0 text-coral-500" aria-hidden />
                  {label}
                </li>
              ))}
            </ul>
          </div>

          <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <button
              type="button"
              disabled={del.isPending}
              onClick={onClose}
              className="inline-flex min-h-[44px] items-center justify-center rounded-2xl border border-sand-300 bg-white px-5 text-[15px] font-semibold text-ink-900 transition-colors hover:bg-sand-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={del.isPending}
              onClick={() => del.mutate(trip.id)}
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-2xl bg-coral-500 px-5 text-[15px] font-semibold text-white shadow-sm transition-colors hover:bg-coral-700 focus:outline-none focus-visible:ring-4 focus-visible:ring-coral-100 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {del.isPending && <Spinner />}
              {del.isPending ? "Deleting…" : "Yes, delete trip"}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}