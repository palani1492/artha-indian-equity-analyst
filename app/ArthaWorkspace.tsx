"use client";

import {
  FormEvent,
  KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  DEMO_PERSONA,
  DEMO_SOURCES,
  DEMO_STOCKS,
  INITIAL_MESSAGES,
  type ChatMessage,
  type Citation,
  type Persona,
  type ResearchSource,
  type Stock,
} from "./artha-data";
import {
  API_ORIGIN,
  ALLOW_DEMO_FALLBACK,
  apiAnswer,
  authUser,
  demoAnswer,
  formatGreeting,
  formatPrice,
  formatRelativeTime,
  inferPersona,
  isRecord,
  personaValue,
  requestAuth,
  requestFirst,
  requestLogout,
  requestUnfollow,
  requestPersonaUpdate,
  sourceList,
  stockList,
  type AuthState,
  type AuthUser,
} from "./artha-api";

type ConnectionMode = "connecting" | "live" | "demo" | "error";
type ThemePreference = "system" | "light" | "dark";
type AnswerEvidence = {
  citations: Citation[];
  sources: ResearchSource[];
  scopeLabel: string;
};
const AUTO_REFRESH_MS = 120_000;

function scopedStorageKey(prefix: string, user: AuthUser | null): string {
  const identity = user?.email || "guest";
  return `${prefix}:${encodeURIComponent(identity)}`;
}

export function ArthaWorkspace() {
  const [stocks, setStocks] = useState<Stock[]>(DEMO_STOCKS);
  const [activeKey, setActiveKey] = useState("NSE:TCS");
  const [persona, setPersona] = useState<Persona>(DEMO_PERSONA);
  const [tickerSources, setTickerSources] = useState<ResearchSource[]>(DEMO_SOURCES);
  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES);
  const [connection, setConnection] = useState<ConnectionMode>("connecting");
  const [notice, setNotice] = useState("");
  const [question, setQuestion] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [followTicker, setFollowTicker] = useState("");
  const [exchange, setExchange] = useState<"NSE" | "BSE">("NSE");
  const [followStatus, setFollowStatus] = useState("");
  const [pendingUnfollow, setPendingUnfollow] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [personaOpen, setPersonaOpen] = useState(false);
  const [tutorialOpen, setTutorialOpen] = useState(false);
  const [openMemoryAfterTutorial, setOpenMemoryAfterTutorial] = useState(false);
  const [personaDraft, setPersonaDraft] = useState<Persona>(DEMO_PERSONA);
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const [expandedSource, setExpandedSource] = useState<string | null>("tcs-fundamentals");
  const [answerEvidence, setAnswerEvidence] = useState<AnswerEvidence | null>(() =>
    initialAnswerEvidence(),
  );
  const [pendingEvidenceScope, setPendingEvidenceScope] = useState<string | null>(null);
  const [theme, setTheme] = useState<ThemePreference>("system");
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const [welcomeTitle, setWelcomeTitle] = useState("Your research desk is ready.");
  const researchRequestId = useRef(0);

  const activeStock = useMemo(
    () => stocks.find((stock) => `${stock.exchange}:${stock.symbol}` === activeKey) ?? stocks[0],
    [activeKey, stocks],
  );
  const visibleSources = pendingEvidenceScope ? [] : answerEvidence?.sources ?? tickerSources;
  const visibleCitations = useMemo(() => answerEvidence?.citations ?? [], [answerEvidence]);
  const citationLabels = useMemo(
    () => new Map(visibleCitations.map((citation) => [citation.sourceId, citation.label])),
    [visibleCitations],
  );

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const now = Date.now();
      setWelcomeTitle(`${formatGreeting(new Date(now))}. Your research desk is ready.`);
      setStocks((current) =>
        current.map((stock, index) =>
          stock.updatedAt
            ? stock
            : {
                ...stock,
                updatedAt: new Date(now - [12, 18, 26, 31][index % 4] * 60_000).toISOString(),
              },
        ),
      );
      setTickerSources((current) =>
        current.map((source, index) =>
          source.publishedAt
            ? source
            : {
                ...source,
                publishedAt: new Date(now - [96 * 60, 48 * 60, 180][index % 3] * 60_000).toISOString(),
              },
        ),
      );
      setMessages((current) =>
        current.map((message) =>
          message.createdAt ? message : { ...message, createdAt: new Date(now).toISOString() },
        ),
      );
    });
    const timer = window.setInterval(() => setClock(Date.now()), 60_000);
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    let active = true;
    const localStateFrame = window.requestAnimationFrame(() => {
      const storedTheme = window.localStorage.getItem("artha-theme");
      if (storedTheme === "light" || storedTheme === "dark" || storedTheme === "system") {
        setTheme(storedTheme);
        applyTheme(storedTheme);
      }
      const storedPersonaKey = window.localStorage.getItem("artha-persona:guest")
        ? "artha-persona:guest"
        : "artha-persona";
      const storedPersona = window.localStorage.getItem(storedPersonaKey);
      if (storedPersona) {
        try {
          const parsed = personaValue(JSON.parse(storedPersona));
          if (parsed) {
            setPersona(parsed);
            setPersonaDraft(parsed);
          }
        } catch {
          window.localStorage.removeItem(storedPersonaKey);
        }
      }
    });

    void Promise.allSettled([
      requestFirst(["/api/v1/stocks", "/api/stocks"]),
      requestFirst(["/api/v1/persona", "/api/persona"]),
      requestAuth(),
    ]).then((results) => {
      if (!active) return;
      let successfulRequests = 0;
      const [stockResult, personaResult, authResult] = results;
      let hydratedStocks: Stock[] | null = null;
      if (stockResult.status === "fulfilled") {
        successfulRequests += 1;
        hydratedStocks = stockList(stockResult.value);
        if (hydratedStocks) {
          setStocks(hydratedStocks);
          if (!hydratedStocks.some((stock) => `${stock.exchange}:${stock.symbol}` === activeKey)) {
            setActiveKey(hydratedStocks[0] ? `${hydratedStocks[0].exchange}:${hydratedStocks[0].symbol}` : "");
          }
        }
      }
      if (personaResult.status === "fulfilled") {
        successfulRequests += 1;
        const nextPersona = personaValue(personaResult.value);
        if (nextPersona) {
          setPersona(nextPersona);
          setPersonaDraft(nextPersona);
        }
      }
      if (successfulRequests > 0) {
        researchRequestId.current += 1;
        setConnection("live");
        setMessages([]);
        setAnswerEvidence(null);
        setPendingEvidenceScope(null);
        setIsThinking(false);
        const initialTicker = hydratedStocks?.[0]?.symbol;
        if (initialTicker) void refreshSources(initialTicker, true);
      } else {
        if (ALLOW_DEMO_FALLBACK) {
          setConnection("demo");
          setAuthState("demo");
          setUser({ name: "Sample profile", email: "", initials: "SP" });
          setNotice("Live API unavailable. Showing the deterministic sample dataset.");
        } else {
          setConnection("error");
          setAuthState("guest");
          setUser(null);
          setStocks([]);
          setTickerSources([]);
          setMessages([]);
          setNotice("The live analyst is temporarily unavailable. Try again shortly.");
        }
      }
      if (authResult.status === "fulfilled") {
        const nextUser = authUser(authResult.value);
        setUser(nextUser);
        setAuthState(nextUser ? "authenticated" : "guest");
        const rawPersona = personaResult.status === "fulfilled" ? personaResult.value : null;
        const personaVersion = isRecord(rawPersona) ? Number(rawPersona.version ?? 1) : 1;
        if (nextUser) {
          const personaKey = scopedStorageKey("artha-persona", nextUser);
          const tutorialKey = scopedStorageKey("artha-tutorial-seen", nextUser);
          const storedPersona = window.localStorage.getItem(personaKey);
          if (storedPersona) {
            try {
              const parsed = personaValue(JSON.parse(storedPersona));
              if (parsed) {
                setPersona(parsed);
                setPersonaDraft(parsed);
              }
            } catch {
              window.localStorage.removeItem(personaKey);
            }
          }
          const firstVisit = !window.localStorage.getItem(tutorialKey);
          const needsOnboarding = personaVersion <= 1 && !storedPersona;
          if (needsOnboarding) setTutorialOpen(true);
          if (needsOnboarding) {
            setOpenMemoryAfterTutorial(true);
            if (!firstVisit) {
              setPersonaOpen(true);
              setNotice("Start by setting the investor memory Artha should use for your research.");
            }
          }
        }
      } else if (successfulRequests > 0) {
        setAuthState("guest");
      }
    });

    return () => {
      active = false;
      window.cancelAnimationFrame(localStateFrame);
    };
    // Initial hydration is intentionally one-shot; later changes use the refresh loop below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (connection !== "live" || authState !== "authenticated" || stocks.length === 0) {
      return;
    }
    let disposed = false;
    const refresh = async () => {
      try {
        const payload = await requestFirst(["/api/v1/refresh", "/api/refresh"], {
          method: "POST",
        });
        if (disposed) return;
        const nextStocks = isRecord(payload) ? stockList(payload.stocks) : null;
        if (nextStocks) setStocks(nextStocks);
        const refreshedActive = nextStocks?.find(
          (stock) => `${stock.exchange}:${stock.symbol}` === activeKey,
        ) ?? nextStocks?.[0];
        if (refreshedActive) await refreshSources(refreshedActive.symbol, true);
      } catch {
        // Keep the last verified snapshot visible; the next interval retries.
      }
    };
    const timer = window.setInterval(() => void refresh(), AUTO_REFRESH_MS);
    const onVisibilityChange = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    void refresh();
    return () => {
      disposed = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
    // refreshSources is an event helper; the interval is intentionally keyed to workspace state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeKey, authState, connection, stocks.length]);

  function persistPersona(nextPersona: Persona) {
    setPersona(nextPersona);
    setPersonaDraft(nextPersona);
    window.localStorage.setItem(
      scopedStorageKey("artha-persona", user),
      JSON.stringify(nextPersona),
    );
  }

  async function refreshSources(ticker?: string, force = false) {
    if (!force && connection !== "live") return;
    const query = ticker ? `?ticker=${encodeURIComponent(ticker)}` : "";
    try {
      const payload = await requestFirst([
        `/api/v1/sources${query}`,
        `/api/sources${query}`,
      ]);
      const nextSources = sourceList(payload);
      if (nextSources) {
        setTickerSources(nextSources);
        setExpandedSource((current) => current ?? nextSources[0]?.id ?? null);
      }
    } catch {
      // The answer path remains authoritative; the rail can show its empty state.
    }
  }

  async function sendQuestion(input: string) {
    const cleanQuestion = input.trim();
    if (!cleanQuestion || isThinking) return;
    const requestId = researchRequestId.current + 1;
    researchRequestId.current = requestId;
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: cleanQuestion,
      createdLabel: "Now",
      createdAt: new Date().toISOString(),
    };
    const nextPersona = inferPersona(cleanQuestion, persona);
    const requestedTicker = questionTicker(cleanQuestion, activeStock?.symbol);
    const evidenceScope = answerEvidenceScope(
      cleanQuestion,
      requestedTicker,
      stocks,
    );
    if (nextPersona !== persona) persistPersona(nextPersona);
    setMessages((current) => [...current, userMessage]);
    setQuestion("");
    setIsThinking(true);
    setNotice("");
    setAnswerEvidence(null);
    setPendingEvidenceScope(evidenceScope);
    setExpandedSource(null);

    let answer: ChatMessage | null = null;
    if (connection !== "demo") {
      try {
        const payload = await requestFirst(["/api/v1/chat", "/api/chat"], {
          method: "POST",
          body: JSON.stringify({
            message: cleanQuestion,
            ticker: requestedTicker,
            persona: nextPersona,
          }),
        });
        if (researchRequestId.current !== requestId) return;
        answer = apiAnswer(payload);
        const learnedPersona = isRecord(payload) ? personaValue(payload.persona) : null;
        if (learnedPersona) persistPersona(learnedPersona);
      } catch {
        if (researchRequestId.current !== requestId) return;
        if (!ALLOW_DEMO_FALLBACK) {
          setNotice("The live analyst could not answer right now. No sample answer was substituted.");
          setPendingEvidenceScope(null);
          setIsThinking(false);
          return;
        }
        setConnection("demo");
        setNotice("The live analyst did not respond. A deterministic sample answer is shown.");
      }
    }
    if (!answer) {
      await new Promise((resolve) => window.setTimeout(resolve, 420));
      if (researchRequestId.current !== requestId) return;
      answer = demoAnswer(cleanQuestion, nextPersona);
    }
    const citations = answer.citations ?? [];
    const citedSources = sourcesForCitations(citations, tickerSources);
    setAnswerEvidence({ citations, sources: citedSources, scopeLabel: evidenceScope });
    setPendingEvidenceScope(null);
    setExpandedSource(citedSources[0]?.id ?? null);
    setMessages((current) => [...current, answer]);
    setIsThinking(false);
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void sendQuestion(question);
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendQuestion(question);
    }
  }

  function resetResearchContext() {
    researchRequestId.current += 1;
    setMessages([]);
    setAnswerEvidence(null);
    setPendingEvidenceScope(null);
    setTickerSources([]);
    setExpandedSource(null);
    setIsThinking(false);
  }

  async function handleFollow(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const enteredTicker = followTicker
      .toUpperCase()
      .replace(/[^A-Z0-9&.]/g, "")
      .slice(0, 14);
    const explicitBse = /\.(?:BO|BSE)$/.test(enteredTicker);
    const explicitNse = /\.(?:NS|NSE)$/.test(enteredTicker);
    const selectedExchange = explicitBse ? "BSE" : explicitNse ? "NSE" : exchange;
    const symbol = enteredTicker.replace(/\.(?:BO|BSE|NS|NSE)$/, "");
    const providerTicker = selectedExchange === "BSE" ? `${symbol}.BO` : symbol;
    if (!symbol) {
      setFollowStatus("Enter a valid NSE or BSE ticker.");
      return;
    }
    if (stocks.some((stock) => stock.symbol === symbol)) {
      setActiveKey(`${selectedExchange}:${symbol}`);
      resetResearchContext();
      setFollowTicker("");
      setFollowStatus(`${symbol} is already on your research list.`);
      void refreshSources(symbol);
      return;
    }

    setFollowStatus(`Adding ${symbol} and queuing source ingestion.`);
    let addedStock: Stock | null = null;
    if (connection === "live") {
      try {
        const payload = await requestFirst([
          `/api/v1/stocks/${encodeURIComponent(providerTicker)}/follow`,
          "/api/follow",
        ], {
          method: "POST",
          body: JSON.stringify({
            ticker: providerTicker,
            symbol,
            exchange: selectedExchange,
          }),
        });
        const candidate = isRecord(payload) && isRecord(payload.stock) ? payload.stock : payload;
        addedStock = stockList([candidate])?.[0] ?? null;
      } catch {
        if (!ALLOW_DEMO_FALLBACK) {
          setFollowStatus("Live ingestion is unavailable. The ticker was not added.");
          return;
        }
        setConnection("demo");
        setNotice("Follow was saved in this demo session. The live API was unavailable.");
      }
    }
    const nextStock =
      addedStock ??
      ({
        symbol,
        exchange: selectedExchange,
        company: symbol,
        sector: "New research coverage",
        price: 0,
        changePct: 0,
        tone: "Watch",
        indexedDocuments: 0,
        updatedLabel: "Ingestion queued",
        updatedAt: new Date().toISOString(),
      } satisfies Stock);
    setStocks((current) => [...current, nextStock]);
    setActiveKey(`${selectedExchange}:${symbol}`);
    resetResearchContext();
    setFollowTicker("");
    await refreshSources(symbol);
    setFollowStatus(`${symbol} added. Fundamentals and news are queued.`);
  }

  function handleSelectStock(stock: Stock) {
    setActiveKey(`${stock.exchange}:${stock.symbol}`);
    setPendingUnfollow(null);
    resetResearchContext();
    void refreshSources(stock.symbol);
  }

  async function handleUnfollow(stock: Stock) {
    const key = `${stock.exchange}:${stock.symbol}`;
    if (pendingUnfollow !== key) {
      setPendingUnfollow(key);
      return;
    }
    setPendingUnfollow(null);
    setFollowStatus(`Removing ${stock.symbol} from your research list.`);
    if (connection === "live") {
      try {
        await requestUnfollow(stock.symbol, stock.exchange);
      } catch {
        setFollowStatus(`Could not remove ${stock.symbol}. Please try again.`);
        return;
      }
    }
    const remaining = stocks.filter(
      (item) => !(item.symbol === stock.symbol && item.exchange === stock.exchange),
    );
    setStocks(remaining);
    if (activeStock?.symbol === stock.symbol && activeStock.exchange === stock.exchange) {
      setActiveKey(remaining[0] ? `${remaining[0].exchange}:${remaining[0].symbol}` : "");
    }
    resetResearchContext();
    setFollowStatus(`${stock.symbol} removed from your research list.`);
  }

  async function handleIngest() {
    if (!activeStock || ingesting) return;
    const providerTicker =
      activeStock.exchange === "BSE"
        ? `${activeStock.symbol}.BO`
        : activeStock.symbol;
    setIngesting(true);
    setNotice("");
    if (connection === "live") {
      try {
        await requestFirst([
          `/api/v1/stocks/${encodeURIComponent(providerTicker)}/ingest`,
          "/api/ingest",
        ], {
          method: "POST",
          body: JSON.stringify({
            ticker: providerTicker,
            exchange: activeStock.exchange,
          }),
        });
        const refreshedStocks = await requestFirst(["/api/v1/stocks", "/api/stocks"]);
        const nextStocks = stockList(refreshedStocks);
        if (nextStocks) setStocks(nextStocks);
        await refreshSources(activeStock.symbol);
      } catch {
        if (!ALLOW_DEMO_FALLBACK) {
          setNotice("Live refresh is unavailable. No sample data was substituted.");
          setIngesting(false);
          return;
        }
        setConnection("demo");
        setNotice("Refresh completed as a demo. No live source records were changed.");
      }
    } else {
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
    setStocks((current) =>
      current.map((stock) =>
        stock.symbol === activeStock.symbol && stock.exchange === activeStock.exchange
          ? { ...stock, updatedLabel: "Just refreshed", updatedAt: new Date().toISOString() }
          : stock,
      ),
    );
    setIngesting(false);
  }

  async function handlePersonaSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    persistPersona(personaDraft);
    setPersonaOpen(false);
    setNotice("Investor memory updated for future research.");
    if (connection === "live") {
      try {
        await requestPersonaUpdate(personaDraft);
      } catch {
        if (ALLOW_DEMO_FALLBACK) {
          setConnection("demo");
          setNotice("Memory is saved locally. Live profile sync was unavailable.");
        } else {
          setNotice("Memory was saved on this device, but the live profile could not be updated.");
        }
      }
    }
  }

  async function handleLogout() {
    try {
      await requestLogout();
      setAuthState("guest");
      setUser(null);
      setNotice("Signed out securely.");
    } catch {
      setNotice("Sign out did not complete. Please try again.");
    }
  }

  function cycleTheme() {
    const nextTheme = theme === "system" ? "light" : theme === "light" ? "dark" : "system";
    setTheme(nextTheme);
    applyTheme(nextTheme);
    window.localStorage.setItem("artha-theme", nextTheme);
  }

  function revealSource(sourceId: string) {
    setSourcesOpen(true);
    setExpandedSource(sourceId);
    window.requestAnimationFrame(() => {
      document.getElementById(`source-${sourceId}`)?.scrollIntoView({
        behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? "auto"
          : "smooth",
        block: "nearest",
      });
    });
  }

  return (
    <div className="workspace-shell">
      <a className="skip-link" href="#research-thread">Skip to research</a>
      <header className="topbar">
        <div className="brand-lockup" aria-label="Artha home">
          <strong>Artha</strong>
        </div>
        <div className="topbar-actions">
          <ConnectionBadge mode={connection} />
          <button className="text-button theme-button" type="button" onClick={cycleTheme}>
            Theme: {theme === "system" ? "Auto" : theme === "light" ? "Light" : "Dark"}
          </button>
          <AccountControl state={authState} user={user} onLogout={handleLogout} />
        </div>
      </header>

      <main className="research-grid">
        <aside className="watchlist-rail" id="following" aria-labelledby="following-title">
          <div className="rail-heading">
            <div>
              <p className="eyebrow">Coverage</p>
              <h1 id="following-title">Followed equities</h1>
            </div>
            <span className="count-label">{stocks.length}</span>
          </div>

          <form className="follow-form" onSubmit={handleFollow}>
            <label htmlFor="ticker">Add a ticker</label>
            <div className="follow-controls">
              <select
                aria-label="Exchange"
                value={exchange}
                onChange={(event) => setExchange(event.target.value === "BSE" ? "BSE" : "NSE")}
              >
                <option>NSE</option>
                <option>BSE</option>
              </select>
              <input
                id="ticker"
                value={followTicker}
                onChange={(event) => setFollowTicker(event.target.value.toUpperCase())}
                placeholder="SBIN"
                autoComplete="off"
                spellCheck={false}
              />
              <button type="submit">Add</button>
            </div>
            <p className="form-help" aria-live="polite">
              {followStatus || "Following queues fundamentals and recent Indian market news."}
            </p>
          </form>

          {stocks.length === 0 ? (
            <EmptyState title="No equities followed" body="Add an NSE or BSE ticker to begin live research." />
          ) : (
            <div className="stock-list" aria-label="Followed equities">
              {stocks.map((stock) => {
                const key = `${stock.exchange}:${stock.symbol}`;
                const isActive = activeStock?.symbol === stock.symbol && activeStock.exchange === stock.exchange;
                const isPendingRemoval = pendingUnfollow === key;
                return (
                  <div className={`stock-row ${isActive ? "is-active" : ""}`} key={`${stock.exchange}-${stock.symbol}`}>
                    <button
                      className="stock-select"
                      type="button"
                      onClick={() => handleSelectStock(stock)}
                      aria-pressed={isActive}
                      aria-label={`${stock.symbol} ${stock.exchange} / ${stock.sector} ${formatPrice(stock.price)} ${stock.changePct >= 0 ? "+" : ""}${stock.changePct.toFixed(2)}%`}
                    >
                      <span className="stock-main">
                        <strong>{stock.symbol}</strong>
                        <small>{stock.exchange} / {stock.sector}</small>
                      </span>
                      <span className="stock-price">
                        <strong>{formatPrice(stock.price)}</strong>
                        <small className={stock.changePct >= 0 ? "positive" : "negative"}>
                          {stock.changePct >= 0 ? "+" : ""}{stock.changePct.toFixed(2)}%
                        </small>
                      </span>
                    </button>
                    <button
                      className="stock-remove"
                      type="button"
                      onClick={() => void handleUnfollow(stock)}
                      aria-label={`${isPendingRemoval ? "Confirm remove" : "Remove"} ${stock.symbol}`}
                    >
                      {isPendingRemoval ? "Confirm" : "Remove"}
                    </button>
                  </div>
                );
              })}
            </div>
          )}

          <div className="ingestion-summary">
            <div>
              <span>Live source refresh</span>
              <strong>
                {formatRelativeTime(activeStock?.updatedAt, clock) ??
                  activeStock?.updatedLabel ??
                  "No ticker selected"}
              </strong>
              <small>Automatic every 2 minutes</small>
            </div>
            <button type="button" onClick={handleIngest} disabled={!activeStock || ingesting}>
              {ingesting ? "Refreshing" : "Refresh"}
            </button>
          </div>
        </aside>

        <section className="conversation-panel" id="research-thread" aria-labelledby="desk-title">
          <div className="conversation-header">
            <div>
              <p className="desk-context">Research desk / {activeStock?.symbol ?? "No ticker"}</p>
              <h2 id="desk-title">Ask, compare, decide what to study next</h2>
            </div>
            {activeStock ? (
                <div className="active-quote" aria-label={`${activeStock.symbol} current quote`}>
                <span>{activeStock.exchange}: {activeStock.symbol}</span>
                <strong>{formatPrice(activeStock.price)}</strong>
                <small className={activeStock.changePct >= 0 ? "positive" : "negative"}>
                  {activeStock.changePct >= 0 ? "+" : ""}{activeStock.changePct.toFixed(2)}%
                </small>
              </div>
            ) : null}
          </div>

          {notice ? (
            <div className="context-notice" role="alert">
              <span>{notice}</span>
              <button type="button" onClick={() => setNotice("")}>Dismiss</button>
            </div>
          ) : null}

          <div className="message-thread" aria-live="polite" aria-busy={isThinking}>
            {messages.length === 0 ? (
              <ResearchStarter
                activeStock={activeStock}
                followedStocks={stocks}
                onAsk={(prompt) => void sendQuestion(prompt)}
              />
            ) : (
              messages.map((message) => (
                <article className={`message ${message.role}`} key={message.id}>
                  <div className="message-meta">
                    <span>{message.role === "assistant" ? "Artha research" : "You"}</span>
                    <time>{formatRelativeTime(message.createdAt, clock) ?? message.createdLabel}</time>
                  </div>
                  {message.title ? (
                    <h3>{message.id === "welcome" ? welcomeTitle : message.title}</h3>
                  ) : null}
                  <p>{message.text}</p>
                  {message.citations?.length ? (
                    <div className="citation-row" aria-label="Citations">
                      {message.citations.map((citation) => (
                        <button
                          type="button"
                          key={`${message.id}-${citation.sourceId}`}
                          onClick={() => revealSource(citation.sourceId)}
                          aria-label={`Open source ${citation.label}`}
                        >
                          [{citation.label}]
                        </button>
                      ))}
                    </div>
                  ) : null}
                </article>
              ))
            )}
            {isThinking ? <AnswerSkeleton /> : null}
          </div>

          <div className="composer-wrap">
            <form className="composer" aria-label="Ask Artha" onSubmit={handleSubmit}>
              <label className="sr-only" htmlFor="question">Ask Artha about an Indian equity</label>
              <textarea
                id="question"
                rows={2}
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={handleComposerKeyDown}
                placeholder="Ask about sentiment, fundamentals, or fit with your investor memory"
                disabled={isThinking}
              />
              <div className="composer-footer">
                <span>Enter to send / Shift + Enter for a new line</span>
                <button className="primary-button" type="submit" disabled={!question.trim() || isThinking}>
                  {isThinking ? "Researching" : "Ask Artha"}
                </button>
              </div>
            </form>
            <p className="disclaimer">Research aid only. Verify source data before making investment decisions.</p>
          </div>
        </section>

        <aside className="context-rail" aria-label="Research context">
          <section className="memory-panel" id="investor-memory" aria-labelledby="memory-title">
            <div className="section-heading-row">
              <div>
                <p className="eyebrow">Context</p>
                <h2 id="memory-title">Investor memory</h2>
              </div>
              <button
                className="text-button"
                type="button"
                onClick={() => {
                  setPersonaDraft(persona);
                  setPersonaOpen((open) => !open);
                }}
                aria-expanded={personaOpen}
                aria-controls="persona-editor"
              >
                {personaOpen ? "Cancel" : "Edit"}
              </button>
            </div>

            {personaOpen ? (
              <PersonaEditor
                value={personaDraft}
                onChange={setPersonaDraft}
                onSubmit={handlePersonaSave}
              />
            ) : (
              <PersonaSummary persona={persona} />
            )}
          </section>

          <section className="sources-panel" aria-labelledby="sources-title">
            <button
              className="sources-toggle"
              type="button"
              onClick={() => setSourcesOpen((open) => !open)}
              aria-expanded={sourcesOpen}
              aria-controls="source-list"
            >
              <span>
                <small>Evidence</small>
                <strong id="sources-title">Sources used ({visibleSources.length})</strong>
              </span>
              <span aria-hidden="true">{sourcesOpen ? "Hide" : "Show"}</span>
            </button>
            {sourcesOpen ? (
              <div id="source-list" className="source-list">
                <p className="source-explainer">
                  {pendingEvidenceScope
                    ? `Retrieving evidence for ${pendingEvidenceScope.replace("Current answer / ", "")}.`
                    : answerEvidence
                      ? `${answerEvidence.scopeLabel}. This rail is pinned to the exact sources cited by the current answer.`
                      : `Ticker evidence / ${activeStock?.symbol ?? "no ticker selected"}. Ask a question to pin its cited sources here.`}
                </p>
                {visibleSources.length === 0 ? (
                  <EmptyState
                    title={pendingEvidenceScope ? "Retrieving cited sources" : answerEvidence ? "No cited sources returned" : "No sources retrieved"}
                    body={pendingEvidenceScope ? "The rail will update when the answer is ready." : answerEvidence ? "This answer did not include evidence that can be opened." : "Refresh this ticker, then ask a grounded question."}
                  />
                ) : (
                  visibleSources.map((source, index) => (
                    <article
                      className={`source-item ${expandedSource === source.id ? "is-expanded" : ""} ${citationLabels.has(source.id) ? "is-cited" : ""}`}
                      id={`source-${source.id}`}
                      key={source.id}
                    >
                      <button
                        className="source-summary"
                        type="button"
                        onClick={() => setExpandedSource(expandedSource === source.id ? null : source.id)}
                        aria-expanded={expandedSource === source.id}
                      >
                        <span className="source-number">[{citationLabels.get(source.id) ?? index + 1}]</span>
                        <span>
                          <small>{source.ticker ? `${source.ticker} / ` : ""}{source.kind} / {source.publisher}</small>
                          <strong>{source.title}</strong>
                        </span>
                      </button>
                      {expandedSource === source.id ? (
                        <div className="source-detail">
                          <p>{source.excerpt}</p>
                          <div>
                            <span>
                              {formatRelativeTime(source.publishedAt, clock) ?? source.dateLabel}
                            </span>
                            <a href={source.url} target="_blank" rel="noreferrer">Open source</a>
                          </div>
                        </div>
                      ) : null}
                    </article>
                  ))
                )}
              </div>
            ) : null}
          </section>
        </aside>
      </main>
      {tutorialOpen ? (
        <OnboardingDialog
          onClose={() => {
            window.localStorage.setItem(scopedStorageKey("artha-tutorial-seen", user), "1");
            setTutorialOpen(false);
            if (openMemoryAfterTutorial) {
              setPersonaOpen(true);
              setOpenMemoryAfterTutorial(false);
              setNotice("Start by setting the investor memory Artha should use for your research.");
            }
          }}
        />
      ) : null}
    </div>
  );
}

function initialAnswerEvidence(): AnswerEvidence | null {
  const latestAnswer = [...INITIAL_MESSAGES]
    .reverse()
    .find((message) => message.role === "assistant" && message.citations?.length);
  if (!latestAnswer?.citations) return null;
  return {
    citations: latestAnswer.citations,
    sources: sourcesForCitations(latestAnswer.citations, DEMO_SOURCES),
    scopeLabel: "Current answer / TCS",
  };
}

function sourcesForCitations(
  citations: Citation[],
  indexedSources: ResearchSource[],
): ResearchSource[] {
  const indexedById = new Map(indexedSources.map((source) => [source.id, source]));
  const seen = new Set<string>();
  return citations.flatMap((citation) => {
    if (seen.has(citation.sourceId)) return [];
    const source = indexedById.get(citation.sourceId) ?? citation.source;
    if (!source) return [];
    seen.add(citation.sourceId);
    return [{ ...source, id: citation.sourceId }];
  });
}

function answerEvidenceScope(
  question: string,
  requestedTicker: string | null,
  followedStocks: Stock[],
): string {
  const normalized = question.toUpperCase();
  const mentionedTickers = followedStocks
    .map((stock) => {
      const positions = [
        normalized.indexOf(stock.symbol.toUpperCase()),
        normalized.indexOf(stock.company.toUpperCase()),
      ].filter((position) => position >= 0);
      return {
        symbol: stock.symbol,
        position: positions.length ? Math.min(...positions) : -1,
      };
    })
    .filter((match) => match.position >= 0)
    .sort((left, right) => left.position - right.position)
    .map((match) => match.symbol);
  const uniqueTickers = [...new Set(mentionedTickers)];
  if (uniqueTickers.length > 0) return `Current answer / ${uniqueTickers.join(" + ")}`;
  if (requestedTicker) return `Current answer / ${requestedTicker}`;
  return "Current answer / followed equities";
}

function questionTicker(question: string, activeSymbol?: string): string | null {
  const normalized = question.toLowerCase();
  const broadResearch = [
    "compare",
    "which followed",
    "best fit",
    "best fits",
    "recommend",
    "shortlist",
    "my profile",
    "all my",
  ].some((phrase) => normalized.includes(phrase));
  return broadResearch ? null : activeSymbol ?? null;
}

function ConnectionBadge({ mode }: { mode: ConnectionMode }) {
  return (
    <span className={`connection-badge ${mode}`} aria-live="polite">
      <span aria-hidden="true" />
      {mode === "live"
        ? "Live data"
        : mode === "demo"
          ? "Sample data"
          : mode === "error"
            ? "Unavailable"
            : "Connecting"}
    </span>
  );
}

function AccountControl({
  state,
  user,
  onLogout,
}: {
  state: AuthState;
  user: AuthUser | null;
  onLogout: () => void;
}) {
  if (state === "guest") {
    return (
      <a className="sign-in-link" href={`${API_ORIGIN}/api/v1/auth/google/login`}>
        Sign in with Google
      </a>
    );
  }

  if (state === "checking") {
    return <span className="account-checking" aria-label="Checking account">Account</span>;
  }

  return (
    <details className="account-menu">
      <summary aria-label={`Open account menu for ${user?.name ?? "profile"}`}>
        {user?.initials ?? "AI"}
      </summary>
      <div className="account-popover">
        <strong>{user?.name ?? "Profile"}</strong>
        {state === "demo" ? (
          <span>Local sample profile</span>
        ) : (
          <>
            <span>{user?.email}</span>
            <button type="button" onClick={onLogout}>Sign out</button>
          </>
        )}
      </div>
    </details>
  );
}

function PersonaSummary({ persona }: { persona: Persona }) {
  return (
    <div className="persona-summary">
      <dl>
        <div><dt>Risk</dt><dd>{persona.risk}</dd></div>
        <div><dt>Horizon</dt><dd>{persona.horizon}</dd></div>
        <div><dt>Style</dt><dd>{persona.style}</dd></div>
      </dl>
      <div className="memory-group">
        <span>Prioritise</span>
        <div>{persona.focus.map((item) => <span key={item}>{item}</span>)}</div>
      </div>
      <div className="memory-group avoid">
        <span>Avoid</span>
        <div>{persona.avoid.map((item) => <span key={item}>{item}</span>)}</div>
      </div>
      <p className="memory-note">{persona.note}</p>
    </div>
  );
}

function PersonaEditor({
  value,
  onChange,
  onSubmit,
}: {
  value: Persona;
  onChange: (next: Persona) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const riskOptions = ["Conservative", "Moderate", "Aggressive"];
  const horizonOptions = ["Under 1 year", "1 to 3 years", "3 to 5 years", "5+ years"];
  const styleOptions = [
    "Quality at a fair price",
    "Growth",
    "Dividend and quality",
    "Value",
    "Special situations",
  ];
  const focusOptions = [
    "Durable cash flows",
    "Low leverage",
    "Governance",
    "Reliable dividends",
    "Pricing power",
    "Competitive moat",
    "Earnings growth",
  ];
  const avoidOptions = [
    "High debt",
    "Uncited momentum calls",
    "Weak governance",
    "Excessive valuation",
    "Cyclical earnings",
    "Small-cap volatility",
  ];

  function optionsWithCurrent(options: string[], current: string) {
    return options.includes(current) ? options : [current, ...options];
  }

  function togglePreference(key: "focus" | "avoid", option: string) {
    const current = value[key];
    const next = current.includes(option)
      ? current.filter((item) => item !== option)
      : [...current, option];
    onChange({ ...value, [key]: next });
  }

  return (
    <form className="persona-editor" id="persona-editor" onSubmit={onSubmit}>
      <p className="persona-editor-intro">
        Tune the context Artha uses when it ranks companies and explains trade-offs.
      </p>
      <label>
        <span>Risk appetite</span>
        <select value={value.risk} onChange={(event) => onChange({ ...value, risk: event.target.value })}>
          {optionsWithCurrent(riskOptions, value.risk).map((option) => <option key={option}>{option}</option>)}
        </select>
      </label>
      <label>
        <span>Investment horizon</span>
        <select value={value.horizon} onChange={(event) => onChange({ ...value, horizon: event.target.value })}>
          {optionsWithCurrent(horizonOptions, value.horizon).map((option) => <option key={option}>{option}</option>)}
        </select>
      </label>
      <label>
        <span>Investment style</span>
        <select value={value.style} onChange={(event) => onChange({ ...value, style: event.target.value })}>
          {optionsWithCurrent(styleOptions, value.style).map((option) => <option key={option}>{option}</option>)}
        </select>
      </label>
      <PreferencePicker
        legend="Prioritise"
        options={focusOptions}
        values={value.focus}
        onToggle={(option) => togglePreference("focus", option)}
      />
      <PreferencePicker
        legend="Avoid"
        options={avoidOptions}
        values={value.avoid}
        tone="avoid"
        onToggle={(option) => togglePreference("avoid", option)}
      />
      <button className="primary-button" type="submit">Save memory</button>
    </form>
  );
}

function PreferencePicker({
  legend,
  options,
  values,
  tone,
  onToggle,
}: {
  legend: string;
  options: string[];
  values: string[];
  tone?: "avoid";
  onToggle: (option: string) => void;
}) {
  const availableOptions = [...new Set([...values, ...options])];
  return (
    <fieldset className={`persona-choice-group ${tone === "avoid" ? "is-avoid" : ""}`}>
      <legend>{legend}</legend>
      <div className="persona-choice-list">
        {availableOptions.map((option) => {
          const selected = values.includes(option);
          return (
            <button
              className={`persona-choice ${selected ? "is-selected" : ""}`}
              type="button"
              key={option}
              aria-pressed={selected}
              onClick={() => onToggle(option)}
            >
              {option}
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <strong>{title}</strong>
      <p>{body}</p>
    </div>
  );
}

function ResearchStarter({
  activeStock,
  followedStocks,
  onAsk,
}: {
  activeStock?: Stock;
  followedStocks: Stock[];
  onAsk: (prompt: string) => void;
}) {
  const comparisonStock = followedStocks.find(
    (stock) => stock.symbol !== activeStock?.symbol,
  );
  const prompts = [
    activeStock && comparisonStock
      ? `Compare ${activeStock.symbol} and ${comparisonStock.symbol}`
      : activeStock
        ? `Summarise the latest evidence for ${activeStock.symbol}`
        : "Follow an equity to begin research",
    activeStock
      ? `What changed this week for ${activeStock.symbol}?`
      : "What changed this week for my followed equities?",
    "Find a fit for my profile",
  ];
  return (
    <div className="research-starter">
      <div className="starter-mark" aria-hidden="true">A</div>
      <p className="eyebrow">First research question</p>
      <h3>Start a research thread</h3>
      <p>
        Ask a specific question. Artha retrieves indexed fundamentals and news for your followed companies, then links every supported claim to a source.
      </p>
      <div className="starter-prompts" aria-label="Research question examples">
        {prompts.map((prompt) => (
          <button type="button" key={prompt} onClick={() => onAsk(prompt)} disabled={!activeStock}>
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}

function OnboardingDialog({ onClose }: { onClose: () => void }) {
  const steps = [
    ["Set your memory", "Choose your risk, time horizon, and what evidence matters to you."],
    ["Follow a company", "Add an NSE or BSE ticker such as TCS, INFY, or RELIANCE."],
    ["Refresh the evidence", "Refresh the ticker to ingest current fundamentals and recent Indian market news."],
    ["Ask a focused question", "Use the starters or ask about valuation, risks, results, sentiment, or profile fit."],
    ["Open the citations", "The [1], [2], and [3] markers in an answer open the exact retrieved source."],
    ["Compare before acting", "Use Artha as a research aid, verify the linked source, and never treat it as a buy order."],
  ] as const;
  const [step, setStep] = useState(0);
  const isLast = step === steps.length - 1;
  return (
    <div className="onboarding-backdrop" role="presentation">
      <section className="onboarding-dialog" role="dialog" aria-modal="true" aria-labelledby="onboarding-title">
        <div className="onboarding-header">
          <div>
            <p className="eyebrow">Quick start / {step + 1} of {steps.length}</p>
            <h2 id="onboarding-title">Your first research loop</h2>
          </div>
          <button className="text-button" type="button" onClick={onClose}>Skip</button>
        </div>
        <ol className="onboarding-steps">
          {steps.map(([title], index) => (
            <li className={index === step ? "is-current" : index < step ? "is-complete" : ""} key={title}>
              <button type="button" aria-label={`Go to step ${index + 1}: ${title}`} onClick={() => setStep(index)}>{index + 1}</button>
            </li>
          ))}
        </ol>
        <div className="onboarding-copy">
          <span className="onboarding-number">0{step + 1}</span>
          <h3>{steps[step][0]}</h3>
          <p>{steps[step][1]}</p>
        </div>
        <div className="onboarding-actions">
          <button className="text-button" type="button" onClick={() => setStep((current) => Math.max(0, current - 1))} disabled={step === 0}>Back</button>
          {isLast ? (
            <button className="primary-button" type="button" onClick={onClose}>Open my desk</button>
          ) : (
            <button className="primary-button" type="button" onClick={() => setStep((current) => Math.min(steps.length - 1, current + 1))}>Next step</button>
          )}
        </div>
      </section>
    </div>
  );
}

function AnswerSkeleton() {
  return (
    <div className="answer-skeleton" role="status" aria-label="Artha is researching">
      <span />
      <span />
      <span />
    </div>
  );
}

function applyTheme(theme: ThemePreference) {
  if (theme === "system") {
    delete document.documentElement.dataset.theme;
  } else {
    document.documentElement.dataset.theme = theme;
  }
}
