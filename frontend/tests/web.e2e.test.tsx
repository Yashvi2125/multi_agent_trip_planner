/** The real UI against the real backend: no mocked fetch, no mocked WebSocket. */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import { call, createTrip, newUser, renderApp, GOA } from "./helpers";

const RAHUL = "I'd love nightlife and beaches!";
const PRIYA = "I'm not into nightlife, I'd rather relax";
const say = (token: string, id: number, text: string) => call(token, "POST", `/trips/${id}/messages`, { text });
const chat = () => within(screen.getByRole("log", { name: "Trip chat" }));
const planMessage = (token: string, id: number) =>
  call<any[]>(token, "GET", `/trips/${id}/messages`).then((ms) => ms.find((m) => m.sender_type === "ai" && m.text.includes("version")));

describe("accounts", () => {
  test("registering in the UI lands on My trips, and the account really exists", async () => {
    const user = userEvent.setup();
    renderApp("/register");
    const email = `new.${Date.now()}@example.com`;
    await user.type(screen.getByLabelText("Your name"), "Neha Rao");
    await user.type(screen.getByLabelText("Email"), email);
    await user.type(screen.getByLabelText("Password"), "goa-trip-2026");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("heading", { name: "Your trips" })).toBeInTheDocument();
    const login = await call<any>(null, "POST", "/auth/login", { email, password: "goa-trip-2026" });
    expect(login.user.name).toBe("Neha Rao");
  });

  test("a wrong password shows a friendly message, the right one signs in", async () => {
    const u = await newUser("Rahul Mehta");
    const user = userEvent.setup();
    renderApp("/login");
    await user.type(screen.getByLabelText("Email"), u.email);
    await user.type(screen.getByLabelText("Password"), "not-the-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("don't match");
    await user.clear(screen.getByLabelText("Password"));
    await user.type(screen.getByLabelText("Password"), u.password);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Your trips" })).toBeInTheDocument();
  });

  test("signed-out visitors are sent to sign in, and a non-member can't open a trip", async () => {
    renderApp("/trips");
    expect(await screen.findByRole("heading", { name: "Welcome back" })).toBeInTheDocument();
  });

  test("a non-member gets a clear message instead of someone else's trip", async () => {
    const owner = await newUser("Rahul Mehta"), outsider = await newUser("Outsider");
    const trip = await createTrip(owner.token);
    renderApp(`/trip/${trip.id}`, outsider.token);
    expect(await screen.findByText("We couldn't open this trip")).toBeInTheDocument();
    expect(screen.getByText(/not part of this trip/i)).toBeInTheDocument();
  });
});

describe("creating and joining", () => {
  test("the create-trip stepper makes a real trip with a shareable code", async () => {
    const a = await newUser("Rahul Mehta");
    const user = userEvent.setup();
    renderApp("/create", a.token);
    await user.click(await screen.findByRole("button", { name: /^Goa/ }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.change(screen.getByLabelText("First day"), { target: { value: "2026-12-10" } });
    fireEvent.change(screen.getByLabelText("Last day"), { target: { value: "2026-12-14" } });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(screen.getByLabelText(/Total for the whole group/), "60000");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Create trip" }));

    expect(await screen.findByRole("heading", { name: "Goa is on." })).toBeInTheDocument();
    const code = screen.getByLabelText(/^Trip code /).textContent!;
    expect(code).toMatch(/^GOA-[A-Z2-9]{3}$/);
    const trips = await call<any[]>(a.token, "GET", "/trips");
    expect(trips[0]).toMatchObject({ code, destination: "Goa", start_date: "2026-12-10", end_date: "2026-12-14" });
    expect(Number(trips[0].group_budget)).toBe(60000);

    await user.click(screen.getByRole("button", { name: "Open the trip" }));
    expect(await screen.findByRole("heading", { name: "Goa" })).toBeInTheDocument();
    expect(await screen.findByText("No itinerary yet.")).toBeInTheDocument();
  });

  test("joining by an invite link adds you, and an unknown code is explained kindly", async () => {
    const a = await newUser("Rahul Mehta"), b = await newUser("Priya Shah");
    await createTrip(a.token);
    const user = userEvent.setup();
    renderApp("/join", b.token);
    await user.type(await screen.findByLabelText("Trip code"), "ZZZ-999");
    await user.click(screen.getByRole("button", { name: "Join trip" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("doesn't match any trip");
  });

  test("joining with the real code lands on the trip", async () => {
    const a = await newUser("Rahul Mehta"), b = await newUser("Priya Shah");
    const trip = await createTrip(a.token);
    const user = userEvent.setup();
    renderApp(`/join/${trip.code}`, b.token);
    await user.click(await screen.findByRole("button", { name: "Join trip" }));
    expect(await screen.findByRole("heading", { name: "Goa" })).toBeInTheDocument();
    expect(await screen.findByText(/2 travellers/)).toBeInTheDocument();
  });
});

describe("live updates over the WebSocket", () => {
  test("someone joining appears without a reload", async () => {
    const a = await newUser("Rahul Mehta"), b = await newUser("Priya Shah");
    const trip = await createTrip(a.token);
    renderApp(`/trip/${trip.id}`, a.token);
    expect(await screen.findByText(/1 traveller\b/)).toBeInTheDocument();
    await call(b.token, "POST", "/trips/join", { code: trip.code });
    expect(await screen.findByText(/2 travellers/)).toBeInTheDocument();
  });

  test("chat: my message is sent for real, and a friend's message arrives live", async () => {
    const a = await newUser("Rahul Mehta"), b = await newUser("Priya Shah");
    const trip = await createTrip(a.token);
    await call(b.token, "POST", "/trips/join", { code: trip.code });
    const user = userEvent.setup();
    renderApp(`/trip/${trip.id}/chat`, a.token);
    await user.type(await screen.findByRole("textbox", { name: "Message the group" }), "Anyone up for Dudhsagar?{Enter}");
    expect(await chat().findByText("Anyone up for Dudhsagar?")).toBeInTheDocument();
    const stored = await call<any[]>(b.token, "GET", `/trips/${trip.id}/messages`);
    expect(stored.some((m) => m.text === "Anyone up for Dudhsagar?" && m.source === "web")).toBe(true);

    await say(b.token, trip.id, "Yes, early start though");
    expect(await chat().findByText("Yes, early start though")).toBeInTheDocument();
  });
});

describe("planning, end to end", () => {
  test("asking @planner builds a plan that the Plan and Budget pages show, then an update becomes version 2 live", async () => {
    const a = await newUser("Rahul Mehta");
    const trip = await createTrip(a.token);
    const user = userEvent.setup();
    renderApp(`/trip/${trip.id}/chat`, a.token);
    await user.type(await screen.findByRole("textbox", { name: "Message the group" }), "@planner make the itinerary{Enter}");
    expect(await chat().findByText(/Here's version 1 of the Goa plan/)).toBeInTheDocument();

    const plan = await call<any>(a.token, "GET", `/trips/${trip.id}/itinerary`);
    expect(plan.version).toBe(1);
    expect(plan.itinerary.days).toHaveLength(5);

    await user.click(screen.getAllByRole("link", { name: "Plan" })[0]!);
    expect((await screen.findAllByText(/Day 1/)).length).toBeGreaterThan(0);   // timeline header and the map's day switcher
    const firstStop = plan.itinerary.days.flatMap((d: any) => d.items)[0].name as string;
    expect((await screen.findAllByText(firstStop)).length).toBeGreaterThan(0);

    await user.click(screen.getAllByRole("link", { name: "Budget" })[0]!);
    expect(await screen.findByText("Estimated total")).toBeInTheDocument();
    expect(screen.getByText("Per person")).toBeInTheDocument();

    await user.click(screen.getAllByRole("link", { name: "Plan" })[0]!);
    await call(a.token, "POST", `/trips/${trip.id}/regenerate`);
    expect(await screen.findByRole("option", { name: /Version 2 \(latest\)/ })).toBeInTheDocument();
    expect((await planMessage(a.token, trip.id))?.text).toContain("version 1");
  });
});

describe("people and decisions", () => {
  test("a disagreement raised in chat shows on People, with voting that persists", async () => {
    const a = await newUser("Rahul Mehta"), b = await newUser("Priya Shah");
    const trip = await createTrip(a.token);
    await call(b.token, "POST", "/trips/join", { code: trip.code });
    const user = userEvent.setup();
    renderApp(`/trip/${trip.id}/members`, a.token);
    expect(await screen.findByText("Travellers")).toBeInTheDocument();
    expect(screen.getByText("You")).toBeInTheDocument();
    expect(screen.getByText("Trip creator")).toBeInTheDocument();

    await say(a.token, trip.id, RAHUL);
    await say(b.token, trip.id, PRIYA);
    // The same decision also appears in the chat dock by design; scope to the People page section.
    const needs = within(await screen.findByRole("region", { name: "Needs a decision" }));
    expect(needs.getByText(/would like nightlife, but Priya Shah would rather skip it/)).toBeInTheDocument();
    expect((await screen.findAllByText("nightlife")).length).toBeGreaterThan(0);   // preference chips

    await user.click(needs.getByRole("button", { name: "Works for me" }));
    expect(await needs.findByText(/1 for · 0 against/)).toBeInTheDocument();
    const [c] = await call<any[]>(b.token, "GET", `/trips/${trip.id}/conflicts`);
    expect(c).toMatchObject({ status: "open", accept_votes: 1, my_vote: null });   // Priya hasn't voted; Rahul's vote counted
  });

  test("an empty group gets a helpful prompt instead of a blank page", async () => {
    const a = await newUser("Rahul Mehta");
    const trip = await createTrip(a.token);
    renderApp(`/trip/${trip.id}/members`, a.token);
    expect(await screen.findByText("Nobody has shared preferences yet")).toBeInTheDocument();
  });
});

describe("settings", () => {
  test("the creator can edit the budget for real; the header and the server both update", async () => {
    const a = await newUser("Rahul Mehta");
    const trip = await createTrip(a.token);
    const user = userEvent.setup();
    renderApp(`/trip/${trip.id}/settings`, a.token);
    const budget = await screen.findByLabelText(/Group budget/);
    await user.clear(budget);
    await user.type(budget, "80000");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Saved.");
    expect(await screen.findByText(/₹80,000 group budget/)).toBeInTheDocument();
    const saved = await call<any>(a.token, "GET", `/trips/${trip.id}`);
    expect(Number(saved.group_budget)).toBe(80000);
  });

  test("invalid input is explained, not swallowed", async () => {
    const a = await newUser("Rahul Mehta");
    const trip = await createTrip(a.token);
    const user = userEvent.setup();
    renderApp(`/trip/${trip.id}/settings`, a.token);
    const end = await screen.findByLabelText("Ends");
    fireEvent.change(end, { target: { value: "2026-12-01" } });
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("The trip can't end before it starts.")).toBeInTheDocument();
    const same = await call<any>(a.token, "GET", `/trips/${trip.id}`);
    expect(same.end_date).toBe("2026-12-14");           // nothing was saved
  });

  test("non-creators see the details read-only", async () => {
    const a = await newUser("Rahul Mehta"), b = await newUser("Priya Shah");
    const trip = await createTrip(a.token);
    await call(b.token, "POST", "/trips/join", { code: trip.code });
    renderApp(`/trip/${trip.id}/settings`, b.token);
    expect(await screen.findByText(/Only Rahul Mehta can change these details/)).toBeInTheDocument();
    expect(screen.getByLabelText("Trip name")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
  });

  test("the destination locks once a plan exists, with the reason shown", async () => {
    const a = await newUser("Rahul Mehta");
    const trip = await createTrip(a.token);
    await say(a.token, trip.id, "@planner make the itinerary");
    await waitFor(async () => expect(await planMessage(a.token, trip.id)).toBeTruthy(), { timeout: 8000 });
    renderApp(`/trip/${trip.id}/settings`, a.token);
    expect(await screen.findByText(/Locked once a plan exists/)).toBeInTheDocument();
    expect(screen.getByLabelText("Destination")).toBeDisabled();
  });

  test("invite details and the Telegram connection steps use the real trip code and bot", async () => {
    const a = await newUser("Rahul Mehta");
    const trip = await createTrip(a.token);
    const user = userEvent.setup();
    renderApp(`/trip/${trip.id}/settings`, a.token);
    expect(await screen.findByLabelText("trip code")).toHaveTextContent(trip.code);
    expect(screen.getByLabelText("invite link")).toHaveTextContent(`/join/${trip.code}`);
    expect(await screen.findByText(/@WayfareE2EBot/, { selector: "li" })).toBeInTheDocument();
    expect(screen.getByText(`/join ${trip.code}`)).toBeInTheDocument();
    expect(screen.getByText("No group yet")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Get a link code" }));
    expect(await screen.findByLabelText("link command")).toHaveTextContent(/^\/link [A-Z2-9]{6}$/);
    expect(screen.getByText(/within 10 minutes/)).toBeInTheDocument();
  });
});

describe("Bali and unsupported destinations, through the real UI", () => {
  const BALI = { ...GOA, name: "Bali with the gang", destination: "Bali", group_budget: "150000" };

  test("Bali is offered when creating a trip, and the trip gets a BAL code", async () => {
    const a = await newUser("Rahul Mehta");
    const user = userEvent.setup();
    renderApp("/create", a.token);
    await user.click(await screen.findByRole("button", { name: /^Bali/ }));      // listed from the live /destinations API
    await user.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.change(screen.getByLabelText("First day"), { target: { value: "2026-12-10" } });
    fireEvent.change(screen.getByLabelText("Last day"), { target: { value: "2026-12-14" } });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(screen.getByLabelText(/Total for the whole group/), "150000");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Create trip" }));
    expect(await screen.findByRole("heading", { name: "Bali is on." })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Trip code /).textContent!).toMatch(/^BAL-[A-Z2-9]{3}$/);
  });

  test("'Build the first plan' for Bali saves a plan, the Plan page shows its stops, and the Budget page shows an estimate", async () => {
    const a = await newUser("Rahul Mehta");
    const trip = await createTrip(a.token, BALI);
    const user = userEvent.setup();
    renderApp(`/trip/${trip.id}/itinerary`, a.token);
    await user.click(await screen.findByRole("button", { name: "Build the first plan" }));
    expect(await screen.findByRole("option", { name: /Version 1/ }, { timeout: 10000 })).toBeInTheDocument();

    const saved = await call<any>(a.token, "GET", `/trips/${trip.id}/itinerary`);   // really in the database
    expect(saved.version).toBe(1);
    expect(saved.itinerary.destination).toBe("Bali");
    expect(saved.itinerary.days).toHaveLength(5);
    const stops: string[] = saved.itinerary.days.flatMap((d: any) => d.items.map((i: any) => i.name));
    expect(stops.length).toBeGreaterThan(4);
    for (const name of stops.slice(0, 3)) expect((await screen.findAllByText(name)).length).toBeGreaterThan(0);

    await user.click(screen.getAllByRole("link", { name: "Budget" })[0]!);
    expect(await screen.findByText("Estimated total")).toBeInTheDocument();
    expect(screen.getByText("Per person")).toBeInTheDocument();
    const budget = await call<any>(a.token, "GET", `/trips/${trip.id}/budget`);
    expect(Number(budget.total)).toBeGreaterThan(0);
  });

  test("an unsupported destination gets a helpful answer in the chat, with no plan saved", async () => {
    const a = await newUser("Rahul Mehta");
    const trip = await createTrip(a.token, { ...GOA, name: "Lisbon weekend", destination: "Lisbon" });
    const user = userEvent.setup();
    renderApp(`/trip/${trip.id}/chat`, a.token);
    await user.type(await screen.findByRole("textbox", { name: "Message the group" }), "@planner make the itinerary{Enter}");
    expect(await chat().findByText(/Bali, Goa, Jaipur, Manali/)).toBeInTheDocument();
    expect(await chat().findByText(/change the trip's destination in Settings/)).toBeInTheDocument();
    await expect(call(a.token, "GET", `/trips/${trip.id}/itinerary`)).rejects.toBeTruthy();   // 404: nothing was saved
  });
});

describe("arbitrary destinations, through the real UI", () => {
  const TOKYO = { ...GOA, name: "Tokyo with the gang", destination: "Tokyo", group_budget: "150000" };

  test("a destination with no curated data can be typed freely, gets a research hint, and creates a trip", async () => {
    const a = await newUser("Rahul Mehta");
    const user = userEvent.setup();
    renderApp("/create", a.token);
    await user.click(await screen.findByRole("button", { name: "Somewhere else" }));
    await user.type(screen.getByLabelText("Destination"), "Tokyo");
    expect(await screen.findByText(/We'll research Tokyo, Japan for you/, undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByText(/prices are estimates/)).toBeInTheDocument();       // set expectations before the plan exists
    await user.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.change(screen.getByLabelText("First day"), { target: { value: "2026-12-10" } });
    fireEvent.change(screen.getByLabelText("Last day"), { target: { value: "2026-12-14" } });
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.type(screen.getByLabelText(/Total for the whole group/), "150000");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("button", { name: "Create trip" }));
    expect(await screen.findByRole("heading", { name: "Tokyo is on." })).toBeInTheDocument();
    expect(screen.getByLabelText(/^Trip code /).textContent!).toMatch(/^TOK-[A-Z2-9]{3}$/);
  });

  test("the hint is honest when the place can't be found or is a whole country, and never blocks creating the trip", async () => {
    const a = await newUser("Rahul Mehta");
    const user = userEvent.setup();
    renderApp("/create", a.token);
    await user.click(await screen.findByRole("button", { name: "Somewhere else" }));
    await user.type(screen.getByLabelText("Destination"), "Atlantis");
    expect(await screen.findByText(/couldn't find that on the map/, undefined, { timeout: 5000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue" })).toBeEnabled();
    await user.clear(screen.getByLabelText("Destination"));
    await user.type(screen.getByLabelText("Destination"), "Japan");
    expect(await screen.findByText(/whole country or region/, undefined, { timeout: 5000 })).toBeInTheDocument();
  });

  test("'Build the first plan' researches Tokyo, saves a plan, and the Plan and Budget pages show it", async () => {
    const a = await newUser("Rahul Mehta");
    const trip = await createTrip(a.token, TOKYO);
    const user = userEvent.setup();
    renderApp(`/trip/${trip.id}/itinerary`, a.token);
    await user.click(await screen.findByRole("button", { name: "Build the first plan" }));
    expect(await screen.findByRole("option", { name: /Version 1/ }, { timeout: 10000 })).toBeInTheDocument();

    const saved = await call<any>(a.token, "GET", `/trips/${trip.id}/itinerary`);
    expect(saved.version).toBe(1);
    expect(saved.itinerary.destination).toBe("Tokyo");
    const stops: string[] = saved.itinerary.days.flatMap((d: any) => d.items.map((i: any) => i.name));
    expect(stops.length).toBeGreaterThan(4);
    for (const name of stops.slice(0, 3)) expect((await screen.findAllByText(name)).length).toBeGreaterThan(0);

    await user.click(screen.getAllByRole("link", { name: "Budget" })[0]!);
    expect(await screen.findByText("Estimated total")).toBeInTheDocument();
    const budget = await call<any>(a.token, "GET", `/trips/${trip.id}/budget`);
    expect(Number(budget.total)).toBeGreaterThan(0);
  });

  test("@planner can plan and then re-plan a researched destination from the chat", async () => {
    const a = await newUser("Rahul Mehta");
    const trip = await createTrip(a.token, TOKYO);
    const user = userEvent.setup();
    renderApp(`/trip/${trip.id}/chat`, a.token);
    const box = await screen.findByRole("textbox", { name: "Message the group" });
    await user.type(box, "@planner make the itinerary{Enter}");
    expect(await chat().findByText(/researched Tokyo live/, undefined, { timeout: 10000 })).toBeInTheDocument();   // facts vs estimates, said up front
    expect(await chat().findByText(/version 1 of the Tokyo plan/)).toBeInTheDocument();
    await user.type(box, "@planner regenerate the itinerary{Enter}");
    await waitFor(async () => expect((await call<any>(a.token, "GET", `/trips/${trip.id}/itinerary/versions`)).length).toBeGreaterThanOrEqual(2),
      { timeout: 10000 });
  });

  test("a recognised place with too little data gets the helpful fallback, not 'unsupported'", async () => {
    const a = await newUser("Rahul Mehta");
    const trip = await createTrip(a.token, { ...GOA, name: "Smallville", destination: "Smallville" });
    const user = userEvent.setup();
    renderApp(`/trip/${trip.id}/chat`, a.token);
    await user.type(await screen.findByRole("textbox", { name: "Message the group" }), "@planner make the itinerary{Enter}");
    expect(await chat().findByText(/I can recognize Smallville, but I couldn't gather enough reliable information/, undefined, { timeout: 10000 })).toBeInTheDocument();
    expect(await chat().findByText(/add preferences in chat or try another destination/)).toBeInTheDocument();
    await expect(call(a.token, "GET", `/trips/${trip.id}/itinerary`)).rejects.toBeTruthy();   // nothing saved
  });
});
