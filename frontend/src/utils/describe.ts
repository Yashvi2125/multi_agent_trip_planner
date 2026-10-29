import type { Constraint } from "@/types/api";
import { dateRange, firstName, inr } from "./format";

/** Hard constraints in plain language (the API stores them as {type, value}). */
export function describeConstraint(c: Constraint): string {
  const v = c.value as { amount?: string; text?: string; dates?: string[] };
  switch (c.type) {
    case "max_budget": return c.user_id === null ? `Group budget of ${inr(v.amount)}` : `Up to ${inr(v.amount)} per person`;
    case "must_avoid": return `No ${v.text}, ruled out for the whole plan`;
    case "must_include": return `Must include ${v.text}`;
    case "dietary": return `Dietary need: ${v.text}`;
    case "accessibility": return `Accessibility need: ${v.text}`;
    case "unavailable_day": return `Can't make ${(v.dates ?? []).map((d) => dateRange(d, d)).join(", ")}`;
    default: return c.type.replace(/_/g, " ");
  }
}

export const who = (c: Constraint) => (c.user_name ? firstName(c.user_name) : "Everyone");
