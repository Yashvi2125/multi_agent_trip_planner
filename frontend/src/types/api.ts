// These mirror the FastAPI response models exactly. Money arrives as decimal strings.
export type Channel = "web" | "telegram" | "system";
export type SenderType = "user" | "ai" | "system";

export interface User { id: number; name: string; email: string | null; telegram_username: string | null; avatar_url: string | null }
export interface TokenOut { access_token: string; token_type: string; user: User }

export interface Member { user: User; role: "creator" | "member"; joined_via: Channel; joined_at: string }
export interface Trip {
  id: number; code: string; name: string; destination: string; start_date: string | null; end_date: string | null;
  group_budget: string | null; currency: string; status: "planning" | "researching" | "planned" | "locked";
  current_itinerary_version: number; creator_id: number | null; member_count: number;
}
export interface TripDetail extends Trip { members: Member[]; telegram_connected: boolean }
export interface TripCreate { name: string; destination: string; start_date?: string | null; end_date?: string | null; group_budget?: string | null }
export type TripUpdate = Partial<TripCreate>;

export interface Message {
  id: number; trip_id: number; sender_type: SenderType; source: Channel; text: string; created_at: string;
  sender: User | null; reply_to_id: number | null; meta: { conflict_ids?: number[]; version?: number; origin?: string } | null;
}

export interface ItineraryItem {
  place_id: string; name: string; kind: string; area: string; start: string; end: string; duration_min: number;
  cost_pp: number; travel_min_from_prev: number; why: string; serves: string[]; optional: boolean;
  lat: number | null; lon: number | null;
}
export interface ItineraryDay { index: number; date: string | null; title: string; note: string; items: ItineraryItem[] }
export interface Stay { tier: string; area: string; area_name: string; nightly_per_room: number; rooms: number; nights: number; why: string }
export interface Itinerary {
  destination: string; days: ItineraryDay[]; stay: Stay | null; food_tier: string; transport_id: string | null;
  used_fallback: boolean; summary: string;
}
export interface Budget {
  version?: number; total: string; per_person: string; travelers: number; cap: string | null; remaining: string | null;
  over_by: string; status: "within" | "tight" | "over" | "no_budget"; by_category: Record<string, string>;
  lines: { category: string; label: string; total: string }[];
}
export interface ItineraryOut { version: number; change_summary: string | null; created_at: string; itinerary: Itinerary; budget: Budget | null }
export interface VersionOut { version: number; change_summary: string | null; created_at: string }

export interface Conflict {
  id: number; kind: string; description: string; proposed_compromise: string | null; involved_user_ids: number[];
  status: "open" | "accepted" | "dismissed" | "resolved"; created_at: string; accept_votes: number; reject_votes: number;
  my_vote: "accept" | "reject" | null;
}
export interface Preference { user_id: number; user_name: string; category: string; value: string; weight: number }
export interface Constraint { user_id: number | null; user_name: string | null; type: string; value: Record<string, unknown> }
export interface Preferences { preferences: Preference[]; constraints: Constraint[] }
export interface ChecklistItem { id: number; label: string; category: "booking" | "document" | "packing"; done: boolean }
export interface WeatherDay { date: string; summary: string; temp_max: number; temp_min: number; rain_chance: number | null }
export interface Weather { supported: boolean; source: "live" | "climatology" | "none"; notes: string[]; days: WeatherDay[] }
export interface Destination { id: string; name: string; country: string; places: number; areas: number; peak_months: number[]; dry_months: number[]; highlights: string[] }
export interface DestinationLookup { query: string; status: "curated" | "found" | "too_broad" | "not_found" | "unavailable" | "unchecked"; name?: string; country?: string }
export interface TelegramStatus { configured: boolean; bot_username: string | null; mode: string }
export interface LinkCode { code: string; expires_in_seconds: number; bot_username: string | null }

export type WsEvent =
  | { type: "message.new"; data: Message }
  | { type: "ai.status"; data: { text: string | null } }
  | { type: "itinerary.updated"; data: { version: number; change_summary: string } }
  | { type: "budget.updated"; data: Budget }
  | { type: "conflict.new" | "conflict.updated" | "conflict.resolved"; data: Record<string, unknown> }
  | { type: "member.joined"; data: { user_id: number; name: string } }
  | { type: "trip.updated"; data: { id: number; fields: string[] } }
  | { type: "checklist.updated"; data: Record<string, unknown> };
