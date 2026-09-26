// The app's navigation, organised around what a person wants to know rather than around the engine's
// modules. The rail, the tabs inside a section, Home's links and the page titles all read this one list.
// Routes are unchanged from the stage pages, so old links keep working.
import type { RunKey } from "../state/store";

export interface NavPage {
  id: string;          // route
  label: string;       // what the rail and the tabs call it
  question: string;    // the question the page answers, in plain words
  run?: RunKey;        // the result the page shows (for its freshness dot)
  optional?: boolean;  // a deeper tool most people can skip
}

export interface NavItem extends NavPage {
  /** Pages shown as tabs inside this item; the first is the item itself. */
  tabs?: NavPage[];
}

export interface NavGroup {
  label: string | null;
  items: NavItem[];
}

const supply: NavPage = { id: "plan", label: "Supply plan", question: "What do we make, buy and move, and when?", run: "plan" };
const network: NavPage = { id: "network", label: "Map", question: "What does the network look like?" };

export const NAV: NavGroup[] = [
  { label: null, items: [{ id: "home", label: "Home", question: "How are we doing, and what should I do now?" }] },
  { label: "Plan", items: [
    { id: "demand", label: "Demand", question: "What will customers order?", run: "forecast" },
    { ...supply, label: "Supply", tabs: [
      supply,
      { id: "inventory", label: "Buffers", question: "Where should safety stock sit, and how much?", run: "inventory", optional: true },
      { id: "sop", label: "Capacity plan", question: "Can the plants and suppliers keep up, month by month?", run: "sop", optional: true },
      { id: "schedule", label: "Shop floor", question: "In what order should each machine run its jobs?", run: "schedule", optional: true },
    ] },
  ] },
  { label: "Customers", items: [
    { id: "promise", label: "Orders", question: "What can we promise each customer, and when?", run: "promise" },
    { id: "execution", label: "Actuals", question: "What actually happened?", run: "actuals" },
  ] },
  { label: "Results", items: [
    { id: "finance", label: "Money", question: "What does the plan cost and earn?", run: "finance" },
    { id: "tower", label: "Performance", question: "Are we hitting our targets, and what needs following up?", run: "tower" },
  ] },
  { label: "Setup", items: [
    { id: "setup", label: "Set up", question: "What is my company made of, and what's still missing?" },
    { ...network, label: "Network", tabs: [
      network,
      { id: "readiness", label: "Data check", question: "Is the data complete enough to plan?" },
    ] },
    { id: "data", label: "Master data", question: "Locations, products, suppliers, demand and every other input." },
  ] },
];

/** Every page the navigation knows, with the rail item it belongs to. */
export const PAGES: (NavPage & { parent: NavItem })[] = NAV.flatMap((g) => g.items.flatMap((it) =>
  (it.tabs ?? [it]).map((p) => ({ ...p, parent: it }))));

/** The rail item a route belongs to ("settings" is part of master data). */
export function navItemFor(page: string): NavItem | undefined {
  if (page === "settings") page = "data";
  return PAGES.find((p) => p.id === page)?.parent;
}
