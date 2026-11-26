import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogOut, X } from "lucide-react";
import { useEffect } from "react";
import { createPortal } from "react-dom";
import { useToast } from "../context/Toast";
import { api, errorMessage } from "../lib/api";
import type { TripSummary } from "../lib/types";
import { Spinner } from "./ui";

/** Confirmation dialog + leave request for trips the user joined (not organises). */
export function LeaveTripDialog({ trip, onClose }: { trip: TripSummary; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const leave = useMutation({
    mutationFn: (tripId: number) => api(`/api/trips/${tripId}/leave`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["trips"] });
      toast.success(`You left “${trip.name}”.`);
      onClose();
    },
    onError: (err) => {
      toast.error(errorMessage(err));
    },
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !leave.isPending) onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose, leave.isPending]);

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex animate-fade-in items-center justify-center p-4"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="leave-trip-title"
      aria-describedby="leave-trip-desc"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget && !leave.isPending) onClose();
      }}
    >
      <div className="relative w-full max-w-md animate-fade-up overflow-hidden rounded-3xl bg-white shadow-[0_24px_70px_-12px_rgba(14,27,48,0.45)] ring-1 ring-ink-900/10">
        <div className="h-1.5 w-full bg-sun-500" aria-hidden />

        <button
          type="button"
          aria-label="Close"
          disabled={leave.isPending}
          onClick={onClose}
          className="absolute right-4 top-5 rounded-full p-1.5 text-ink-500 transition-colors hover:bg-sand-100 hover:text-ink-900 disabled:opacity-50"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="p-6 sm:p-7">
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-sun-100 text-sun-700">
            <LogOut className="h-6 w-6" aria-hidden />
          </div>

          <h3 id="leave-trip-title" className="mt-4 text-xl font-bold text-ink-900">Leave this trip?</h3>
          <p id="leave-trip-desc" className="mt-1.5 text-sm leading-relaxed text-ink-700">
            You’re about to leave <strong className="font-semibold text-ink-900">“{trip.name}”</strong>.
            Your preferences will be removed from the plan, and you’ll lose access to the chat and itineraries.
            The trip stays for everyone else, and you can rejoin later with the trip code.
          </p>

          <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
            <button
              type="button"
              disabled={leave.isPending}
              onClick={onClose}
              className="inline-flex min-h-[44px] items-center justify-center rounded-2xl border border-sand-300 bg-white px-5 text-[15px] font-semibold text-ink-900 transition-colors hover:bg-sand-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Stay in trip
            </button>
            <button
              type="button"
              disabled={leave.isPending}
              onClick={() => leave.mutate(trip.id)}
              className="inline-flex min-h-[44px] items-center justify-center gap-2 rounded-2xl bg-coral-500 px-5 text-[15px] font-semibold text-white shadow-sm transition-colors hover:bg-coral-700 focus:outline-none focus-visible:ring-4 focus-visible:ring-coral-100 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {leave.isPending && <Spinner />}
              {leave.isPending ? "Leaving…" : "Yes, leave trip"}
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}