/** Telegram ↔ web through the rendered UI. Real: backend, database, WebSocket, planner, the bot's HTTP calls.
 *  Faked: the LLM/weather and Telegram's own servers (a recorder that lets us see exactly what the bot sent). */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, test } from "vitest";
import { call, createTrip, newGroup, newUser, renderApp, tgPress, tgReset, tgSend, tgSent, tgUser } from "./helpers";

const RAHUL = "I'd love nightlife and beaches!";
const PRIYA = "I'm not into nightlife, I'd rather relax";
const chat = () => within(screen.getByRole("log", { name: "Trip chat" }));
const eventually = (fn: () => unknown, timeout = 8000) => waitFor(fn, { timeout, interval: 100 });
const texts = async (chatId: number) => (await tgSent(chatId)).map((c) => c.body.text as string);
let tgSeq = 1000;
const newTgUser = (name: string) => tgUser(tgSeq++, name);       // fresh Telegram identity per test
const ready = () => screen.findByRole("textbox", { name: "Message the group" });

beforeEach(async () => { await tgReset(); });

describe("a Telegram friend and a web friend, one trip", () => {
  test("joining and speaking in Telegram shows up live on the web, marked as Telegram", async () => {
    const rahul = await newUser("Rahul Mehta");
    const trip = await createTrip(rahul.token);
    const group = newGroup(), priya = newTgUser("Priya");
    renderApp(`/trip/${trip.id}/chat`, rahul.token);
    await ready();

    await tgSend(priya, group, `/join ${trip.code}`);
    expect(await chat().findByText(/Priya joined the trip from Telegram/)).toBeInTheDocument();

    await tgSend(priya, group, "Can we add Dudhsagar?");
    const line = await chat().findByText("Can we add Dudhsagar?");
    const row = line.closest("div.min-w-0") as HTMLElement;
    expect(within(row).getByText("Priya")).toBeInTheDocument();
    expect(within(row).getByRole("img", { name: "from Telegram" })).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "People" }).length).toBeGreaterThan(0);

    await userEvent.setup().click(screen.getAllByRole("link", { name: "People" })[0]!);
    expect(await screen.findByText(/joined from Telegram/)).toBeInTheDocument();
  });

  test("a message typed on the web reaches the Telegram group with the sender's name, and nothing is echoed back", async () => {
    const rahul = await newUser("Rahul Mehta");
    const trip = await createTrip(rahul.token);
    const group = newGroup(), priya = newTgUser("Priya");
    await tgSend(priya, group, `/join ${trip.code}`);
    renderApp(`/trip/${trip.id}/chat`, rahul.token);
    const user = userEvent.setup();

    await user.type(await ready(), "Sunset at Chapora?{Enter}");
    await eventually(async () => expect(await texts(group.id)).toContain("Rahul Mehta (web): Sunset at Chapora?"));
    expect(within(chat().getByText("Sunset at Chapora?").closest("div.min-w-0") as HTMLElement)
      .getByRole("img", { name: "from the web" })).toBeInTheDocument();

    await tgSend(priya, group, "Looks good to me");
    expect(await chat().findByText("Looks good to me")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 600));
    expect((await texts(group.id)).some((t) => t.includes("Looks good to me"))).toBe(false);   // never echoed to its origin
  });

  test("one disagreement across both channels is one decision; Telegram buttons and the web button count on the same record", async () => {
    const rahul = await newUser("Rahul Mehta");
    const trip = await createTrip(rahul.token);
    const group = newGroup(), priya = newTgUser("Priya"), aman = newTgUser("Aman");
    for (const u of [priya, aman]) await tgSend(u, group, `/join ${trip.code}`);
    renderApp(`/trip/${trip.id}/members`, rahul.token);
    await screen.findByText("Travellers");

    await call(rahul.token, "POST", `/trips/${trip.id}/messages`, { text: RAHUL });      // from the web
    await tgSend(priya, group, PRIYA);                                                    // from Telegram
    expect((await screen.findAllByText(/would like nightlife, but Priya would rather skip it/)).length).toBeGreaterThan(0);

    let data = "";                                          // the bot offered inline buttons in the Telegram group
    await eventually(async () => {
      const withKb = (await tgSent(group.id)).find((c) => c.body.reply_markup);
      expect(withKb).toBeTruthy();
      data = withKb!.body.reply_markup.inline_keyboard[0][0].callback_data as string;
    });
    const cid = /^v:(\d+):accept$/.exec(data)![1];

    await tgPress(priya, `v:${cid}:accept`);
    expect((await screen.findAllByText(/1 for · 0 against/)).length).toBeGreaterThan(0);   // arrives live on the web
    await tgPress(aman, `v:${cid}:reject`);
    expect((await screen.findAllByText(/1 for · 1 against/)).length).toBeGreaterThan(0);
    await userEvent.setup().click(screen.getAllByRole("button", { name: "Works for me" })[0]!);
    expect((await screen.findAllByText(/2 for · 1 against/)).length).toBeGreaterThan(0);

    const [c] = await call<any[]>(rahul.token, "GET", `/trips/${trip.id}/conflicts`);
    // Three members, so two accepts are a strict majority: the one record closes as accepted for both channels.
    expect(c).toMatchObject({ status: "accepted", accept_votes: 2, reject_votes: 1, my_vote: "accept" });
  });

  test("a plan asked for in Telegram appears on the web Plan page, /itinerary answers in Telegram, and a web update flows back", async () => {
    const rahul = await newUser("Rahul Mehta");
    const trip = await createTrip(rahul.token);
    const group = newGroup(), priya = newTgUser("Priya");
    await tgSend(priya, group, `/join ${trip.code}`);
    renderApp(`/trip/${trip.id}/itinerary`, rahul.token);
    await screen.findByRole("heading", { level: 1 });

    await tgSend(priya, group, "/plan");
    expect(await screen.findByRole("option", { name: /Version 1/ }, { timeout: 10000 })).toBeInTheDocument();

    await tgSend(priya, group, "/itinerary");
    await eventually(async () => {
      const t = (await texts(group.id)).find((x) => /^Goa plan, version 1/.test(x));
      expect(t).toBeTruthy();
      expect(t).toMatch(/Day 1 \(Thu 10 Dec\)/);
    });

    await call(rahul.token, "POST", `/trips/${trip.id}/regenerate`);
    expect(await screen.findByRole("option", { name: /Version 2 \(latest\)/ }, { timeout: 10000 })).toBeInTheDocument();
    await eventually(async () => expect((await texts(group.id)).some((x) => /Here's version 2 of the Goa plan/.test(x))).toBe(true));
  });
});

describe("Telegram direct messages (no group)", () => {
  test("a DM-only member receives web messages and the planner's replies in their private chat", async () => {
    const rahul = await newUser("Rahul Mehta");
    const trip = await createTrip(rahul.token);
    const aman = newTgUser("Aman"), dm = { id: aman.id, type: "private" };
    renderApp(`/trip/${trip.id}/chat`, rahul.token);
    await ready();

    await tgSend(aman, dm, `/join ${trip.code}`);
    expect(await chat().findByText(/Aman joined the trip from Telegram/)).toBeInTheDocument();
    expect((await texts(aman.id)).some((t) => /joined the trip from Telegram/.test(t))).toBe(false);   // not told about themselves

    await userEvent.setup().type(await ready(), "Anyone for a sunrise trek?{Enter}");
    await eventually(async () => expect(await texts(aman.id)).toContain("Rahul Mehta (web): Anyone for a sunrise trek?"));

    await tgSend(aman, dm, "@planner hello");
    await eventually(async () => expect((await texts(aman.id)).some((t) => /I'm here/.test(t))).toBe(true));
  });
});
