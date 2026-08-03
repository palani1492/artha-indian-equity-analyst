import {
  DEMO_PERSONA,
  DEMO_SOURCES,
  type ChatMessage,
  type Citation,
  type Persona,
  type ResearchSource,
  type Stock,
} from "./artha-data";

export const API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");
export const ALLOW_DEMO_FALLBACK =
  process.env.NEXT_PUBLIC_ALLOW_DEMO_FALLBACK !== "false";
const INR_FORMATTER = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2,
});

export type AuthState = "checking" | "authenticated" | "guest" | "demo";
export type AuthUser = { name: string; email: string; initials: string };
type JsonRecord = Record<string, unknown>;

export function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function unwrap(value: unknown): unknown {
  if (!isRecord(value)) return value;
  return value.data ?? value;
}

async function requestJson(path: string, init?: RequestInit): Promise<unknown> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5500);
  try {
    const response = await fetch(`${API_ORIGIN}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        ...init?.headers,
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      throw Object.assign(new Error(`Request failed with ${response.status}`), {
        status: response.status,
      });
    }
    if (response.status === 204) return null;
    return unwrap(await response.json());
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function requestAuth(): Promise<unknown> {
  let lastError: unknown = new Error("Authentication API was unavailable");
  for (const path of ["/api/v1/auth/me", "/api/auth/me"]) {
    try {
      return await requestJson(path);
    } catch (error) {
      if (isRecord(error) && error.status === 401) return null;
      lastError = error;
    }
  }
  throw lastError;
}

export async function requestFirst(paths: string[], init?: RequestInit): Promise<unknown> {
  let lastError: unknown = new Error("No API path was available");
  for (const path of paths) {
    try {
      return await requestJson(path, init);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}

export async function requestPersonaUpdate(persona: Persona): Promise<unknown> {
  const risk = persona.risk.toLowerCase();
  const payload = {
    risk_tolerance: risk === "moderate" ? "balanced" : risk,
    style: persona.style,
    dividend_focused: /dividend/i.test(
      [persona.style, ...persona.focus].join(" "),
    ),
    avoid_high_debt: persona.avoid.some((item) => /debt/i.test(item)),
    preferred_sectors: persona.focus,
    excluded_sectors: persona.avoid.filter((item) => !/debt/i.test(item)),
    priorities: persona.focus,
    avoid: persona.avoid,
    horizon: persona.horizon,
  };
  try {
    return await requestJson("/api/v1/persona", {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  } catch {
    return requestJson("/api/persona", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }
}

export async function requestLogout(): Promise<void> {
  await requestJson("/api/v1/auth/logout", { method: "POST" });
}

export async function requestUnfollow(
  ticker: string,
  exchange: "NSE" | "BSE",
): Promise<void> {
  const providerTicker = exchange === "BSE" ? `${ticker}.BO` : ticker;
  await requestJson(`/api/v1/stocks/${encodeURIComponent(providerTicker)}/follow`, {
    method: "DELETE",
  });
}

export function stockList(payload: unknown): Stock[] | null {
  const raw = Array.isArray(payload)
    ? payload
    : isRecord(payload) && Array.isArray(payload.stocks)
      ? payload.stocks
      : null;
  if (!raw) return null;

  return raw.flatMap((item) => {
    if (!isRecord(item)) return [];
    const rawSymbol = item.symbol ?? item.ticker;
    if (typeof rawSymbol !== "string") return [];
    const change = Number(item.changePct ?? item.change_pct ?? item.change ?? 0);
    const rawTone = String(item.tone ?? item.sentiment ?? "Watch");
    const tone =
      rawTone.toLowerCase().includes("construct") ||
      rawTone.toLowerCase().includes("positive")
        ? "Constructive"
        : rawTone.toLowerCase().includes("caut") ||
            rawTone.toLowerCase().includes("negative")
          ? "Cautious"
          : "Watch";
    return [
      {
        symbol: rawSymbol.toUpperCase(),
        exchange: String(item.exchange).toUpperCase() === "BSE" ? "BSE" : "NSE",
        company: String(item.company ?? item.name ?? rawSymbol),
        sector: String(item.sector ?? "Indian equity"),
        price: Number(item.price ?? item.price_inr ?? item.last_price ?? 0),
        changePct: Number.isFinite(change) ? change : 0,
        tone,
        indexedDocuments: Number(item.indexedDocuments ?? item.document_count ?? 0),
        updatedLabel: String(item.updatedLabel ?? item.updated_at ?? "Recently"),
        updatedAt: typeof (item.updatedAt ?? item.updated_at) === "string"
          ? String(item.updatedAt ?? item.updated_at)
          : undefined,
      } satisfies Stock,
    ];
  });
}

export function personaValue(payload: unknown): Persona | null {
  const value = isRecord(payload) && isRecord(payload.persona) ? payload.persona : payload;
  if (!isRecord(value)) return null;
  const dividendFocused = value.dividend_focused === true;
  const avoidHighDebt = value.avoid_high_debt === true;
  const preferredSectors = stringList(value.preferred_sectors, []);
  const excludedSectors = stringList(value.excluded_sectors, []);
  const priorities = stringList(value.priorities, []);
  const explicitAvoid = stringList(value.avoid, []);
  const risk = String(value.risk ?? value.risk_appetite ?? value.risk_tolerance ?? DEMO_PERSONA.risk);
  const notes = stringList(value.notes, []);
  return {
    risk: titleCase(risk === "balanced" ? "moderate" : risk),
    horizon: String(value.horizon ?? value.investment_horizon ?? DEMO_PERSONA.horizon),
    style: String(
      value.style ??
        value.investment_style ??
        (dividendFocused ? "Dividend and quality" : DEMO_PERSONA.style),
    ),
    focus:
      value.priorities !== undefined || value.preferred_sectors !== undefined
        ? uniqueStrings([
            ...priorities,
            ...preferredSectors,
            ...(dividendFocused ? ["Reliable dividends"] : []),
          ])
        : stringList(value.focus ?? value.preferences, DEMO_PERSONA.focus),
    avoid:
      value.avoid !== undefined || value.excluded_sectors !== undefined
        ? uniqueStrings([
            ...explicitAvoid,
            ...excludedSectors,
            ...(avoidHighDebt ? ["High debt"] : []),
          ])
        : stringList(value.avoid ?? value.exclusions, DEMO_PERSONA.avoid),
    note: String(
      value.note ?? value.summary ?? (notes.length ? notes.join(" ") : DEMO_PERSONA.note),
    ),
  };
}

function titleCase(value: string): string {
  return value ? `${value[0].toUpperCase()}${value.slice(1).toLowerCase()}` : value;
}

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function stringList(value: unknown, fallback: string[]): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [...fallback];
}

export function sourceList(payload: unknown): ResearchSource[] | null {
  const raw = Array.isArray(payload)
    ? payload
    : isRecord(payload) && Array.isArray(payload.sources)
      ? payload.sources
      : null;
  if (!raw) return null;
  return raw.flatMap((item, index) => {
    if (!isRecord(item)) return [];
    const sourceKind = String(item.kind ?? item.type ?? "News");
    return [
      {
        id: String(item.id ?? item.source_id ?? `source-${index + 1}`),
        publisher: String(item.publisher ?? item.source ?? publisherFromUrl(item.url)),
        title: String(item.title ?? "Research source"),
        kind: sourceKind.toLowerCase().includes("fund")
          ? "Fundamentals"
          : sourceKind.toLowerCase().includes("filing")
            ? "Exchange filing"
            : "News",
        dateLabel: String(item.dateLabel ?? item.published_at ?? "Recently indexed"),
        publishedAt: typeof (item.publishedAt ?? item.published_at) === "string"
          ? String(item.publishedAt ?? item.published_at)
          : undefined,
        url: String(item.url ?? item.link ?? "#"),
        excerpt: String(
          item.excerpt ?? item.snippet ?? item.content ?? "Open the source for full context.",
        ),
      } satisfies ResearchSource,
    ];
  });
}

function publisherFromUrl(value: unknown): string {
  if (typeof value !== "string") return "Indexed source";
  try {
    return new URL(value).hostname.replace(/^www\./, "");
  } catch {
    return "Indexed source";
  }
}

export function authUser(payload: unknown): AuthUser | null {
  const value = isRecord(payload) && isRecord(payload.user) ? payload.user : payload;
  if (!isRecord(value)) return null;
  const email = typeof value.email === "string" ? value.email : "";
  const name = String(value.name ?? value.full_name ?? value.display_name ?? email).trim();
  if (!name && !email) return null;
  const initials =
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("") || "AI";
  return { name: name || email, email, initials };
}

export function formatPrice(value: number): string {
  return value > 0 ? INR_FORMATTER.format(value) : "Quote pending";
}

export function formatGreeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour >= 5 && hour < 12) return "Good morning";
  if (hour >= 12 && hour < 17) return "Good afternoon";
  if (hour >= 17 && hour < 22) return "Good evening";
  return "Good night";
}

export function formatRelativeTime(value: string | undefined, now = Date.now()): string | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  const elapsedSeconds = Math.max(0, Math.floor((now - timestamp) / 1000));
  if (elapsedSeconds < 45) return "just now";
  if (elapsedSeconds < 90) return "1 min ago";
  if (elapsedSeconds < 3600) return `${Math.floor(elapsedSeconds / 60)} min ago`;
  if (elapsedSeconds < 86400) return `${Math.floor(elapsedSeconds / 3600)}h ago`;
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(timestamp);
}

export function inferPersona(text: string, current: Persona): Persona {
  const normalized = text.toLowerCase();
  const asksConservative = normalized.includes("conservative");
  const asksDividend = normalized.includes("dividend");
  const avoidsDebt = normalized.includes("avoid") && normalized.includes("debt");
  if (!asksConservative && !asksDividend && !avoidsDebt) return current;

  return {
    ...current,
    risk: asksConservative ? "Conservative" : current.risk,
    style: asksDividend ? "Dividend and quality" : current.style,
    focus: asksDividend
      ? Array.from(new Set([...current.focus, "Reliable dividends"]))
      : [...current.focus],
    avoid: avoidsDebt
      ? Array.from(new Set([...current.avoid, "High debt"]))
      : [...current.avoid],
    note: "Updated from this conversation. Review memory at any time.",
  };
}

export function demoAnswer(question: string, persona: Persona): ChatMessage {
  const normalized = question.toLowerCase();
  const isComparison = normalized.includes("infosys") || normalized.includes("compare");
  const isProfile = normalized.includes("profile") || normalized.includes("fit");
  const title = isComparison
    ? "TCS has the stronger evidence fit"
    : isProfile
      ? `A ${persona.risk.toLowerCase()} quality shortlist starts with TCS`
      : "The indexed evidence is mixed, with a quality bias";
  const text = isComparison
    ? "TCS currently has the clearer balance-sheet and company-reporting trail in this sample [1][2]. Infosys has recent price weakness, but I do not have enough indexed evidence here to call that an opportunity. Add fresh Infosys fundamentals before deciding."
    : "TCS best matches the recorded preference for durable cash flows and low leverage in this sample [1]. Company reporting supports the operating context [2], while recent market coverage argues for monitoring demand rather than issuing an immediate buy instruction [3].";
  return {
    id: crypto.randomUUID(),
    role: "assistant",
    title,
    text,
    citations: DEMO_SOURCES.map((source, index) => ({
      sourceId: source.id,
      label: String(index + 1),
    })),
    createdLabel: "Now",
    createdAt: new Date().toISOString(),
  };
}

export function apiAnswer(payload: unknown): ChatMessage | null {
  if (!isRecord(payload)) return null;
  const answer = payload.answer ?? payload.message ?? payload.response;
  if (typeof answer !== "string") return null;
  const rawCitations = Array.isArray(payload.citations) ? payload.citations : [];
  const citations = rawCitations.flatMap((item, index): Citation[] => {
    if (typeof item === "string") return [{ sourceId: item, label: String(index + 1) }];
    if (!isRecord(item)) return [];
    return [
      {
        sourceId: String(
          item.sourceId ??
            item.source_id ??
            item.document_id ??
            item.id ??
            `source-${index + 1}`,
        ),
        label: String(index + 1),
      },
    ];
  });
  return {
    id: crypto.randomUUID(),
    role: "assistant",
    title: typeof payload.title === "string" ? payload.title : "Grounded research response",
    text: answer,
    citations,
    createdLabel: "Now",
    createdAt:
      typeof payload.created_at === "string"
        ? payload.created_at
        : new Date().toISOString(),
  };
}
