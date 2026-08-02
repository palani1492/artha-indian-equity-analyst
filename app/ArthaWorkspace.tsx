"use client";

import {
  FormEvent,
  KeyboardEvent,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  DEMO_PERSONA,
  DEMO_SOURCES,
  DEMO_STOCKS,
  INITIAL_MESSAGES,
  QUICK_PROMPTS,
  type ChatMessage,
  type Persona,
  type ResearchSource,
  type Stock,
} from "./artha-data";
import {
  API_ORIGIN,
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
  requestPersonaUpdate,
  sourceList,
  stockList,
  type AuthState,
  type AuthUser,
} from "./artha-api";

type ConnectionMode = "connecting" | "live" | "demo";
type ThemePreference = "system" | "light" | "dark";

export function ArthaWorkspace() {
  const [stocks, setStocks] = useState<Stock[]>(DEMO_STOCKS);
  const [activeSymbol, setActiveSymbol] = useState("TCS");
  const [persona, setPersona] = useState<Persona>(DEMO_PERSONA);
  const [sources, setSources] = useState<ResearchSource[]>(DEMO_SOURCES);
  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES);
  const [connection, setConnection] = useState<ConnectionMode>("connecting");
  const [notice, setNotice] = useState("");
  const [question, setQuestion] = useState("");
  const [isThinking, setIsThinking] = useState(false);
  const [followTicker, setFollowTicker] = useState("");
  const [exchange, setExchange] = useState<"NSE" | "BSE">("NSE");
  const [followStatus, setFollowStatus] = useState("");
  const [ingesting, setIngesting] = useState(false);
  const [personaOpen, setPersonaOpen] = useState(false);
  const [personaDraft, setPersonaDraft] = useState<Persona>(DEMO_PERSONA);
  const [sourcesOpen, setSourcesOpen] = useState(true);
  const [expandedSource, setExpandedSource] = useState<string | null>("tcs-fundamentals");
  const [theme, setTheme] = useState<ThemePreference>("system");
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const [welcomeTitle, setWelcomeTitle] = useState("Your research desk is ready.");

  const activeStock = useMemo(
    () => stocks.find((stock) => stock.symbol === activeSymbol) ?? stocks[0],
    [activeSymbol, stocks],
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
      setSources((current) =>
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
      const storedPersona = window.localStorage.getItem("artha-persona");
      if (storedPersona) {
        try {
          const parsed = personaValue(JSON.parse(storedPersona));
          if (parsed) {
            setPersona(parsed);
            setPersonaDraft(parsed);
          }
        } catch {
          window.localStorage.removeItem("artha-persona");
        }
      }
    });

    void Promise.allSettled([
      requestFirst(["/api/v1/stocks", "/api/stocks"]),
      requestFirst(["/api/v1/persona", "/api/persona"]),
      requestFirst(["/api/v1/sources", "/api/sources"]),
      requestAuth(),
    ]).then((results) => {
      if (!active) return;
      let successfulRequests = 0;
      const [stockResult, personaResult, sourceResult, authResult] = results;
      if (stockResult.status === "fulfilled") {
        successfulRequests += 1;
        const nextStocks = stockList(stockResult.value);
        if (nextStocks) setStocks(nextStocks);
      }
      if (personaResult.status === "fulfilled") {
        successfulRequests += 1;
        const nextPersona = personaValue(personaResult.value);
        if (nextPersona) {
          setPersona(nextPersona);
          setPersonaDraft(nextPersona);
        }
      }
      if (sourceResult.status === "fulfilled") {
        successfulRequests += 1;
        const nextSources = sourceList(sourceResult.value);
        if (nextSources) setSources(nextSources);
      }
      if (successfulRequests > 0) {
        setConnection("live");
      } else {
        setConnection("demo");
        setAuthState("demo");
        setUser({ name: "Sample profile", email: "", initials: "SP" });
        setNotice("Live API unavailable. Showing the deterministic sample dataset.");
      }
      if (authResult.status === "fulfilled") {
        const nextUser = authUser(authResult.value);
        setUser(nextUser);
        setAuthState(nextUser ? "authenticated" : "guest");
      } else if (successfulRequests > 0) {
        setAuthState("guest");
      }
    });

    return () => {
      active = false;
      window.cancelAnimationFrame(localStateFrame);
    };
  }, []);

  function persistPersona(nextPersona: Persona) {
    setPersona(nextPersona);
    setPersonaDraft(nextPersona);
    window.localStorage.setItem("artha-persona", JSON.stringify(nextPersona));
  }

  async function sendQuestion(input: string) {
    const cleanQuestion = input.trim();
    if (!cleanQuestion || isThinking) return;
    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      text: cleanQuestion,
      createdLabel: "Now",
      createdAt: new Date().toISOString(),
    };
    const nextPersona = inferPersona(cleanQuestion, persona);
    if (nextPersona !== persona) persistPersona(nextPersona);
    setMessages((current) => [...current, userMessage]);
    setQuestion("");
    setIsThinking(true);
    setNotice("");

    let answer: ChatMessage | null = null;
    if (connection !== "demo") {
      try {
        const payload = await requestFirst(["/api/v1/chat", "/api/chat"], {
          method: "POST",
          body: JSON.stringify({
            message: cleanQuestion,
            ticker: activeStock?.symbol ?? null,
            persona: nextPersona,
          }),
        });
        answer = apiAnswer(payload);
        const learnedPersona = isRecord(payload) ? personaValue(payload.persona) : null;
        if (learnedPersona) persistPersona(learnedPersona);
      } catch {
        setConnection("demo");
        setNotice("The live analyst did not respond. A deterministic sample answer is shown.");
      }
    }
    if (!answer) {
      await new Promise((resolve) => window.setTimeout(resolve, 420));
      answer = demoAnswer(cleanQuestion, nextPersona);
    }
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
      setActiveSymbol(symbol);
      setFollowTicker("");
      setFollowStatus(`${symbol} is already on your research list.`);
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
    setActiveSymbol(symbol);
    setFollowTicker("");
    setFollowStatus(`${symbol} added. Fundamentals and news are queued.`);
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
      } catch {
        setConnection("demo");
        setNotice("Refresh completed as a demo. No live source records were changed.");
      }
    } else {
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
    setStocks((current) =>
      current.map((stock) =>
        stock.symbol === activeStock.symbol
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
        setConnection("demo");
        setNotice("Memory is saved locally. Live profile sync was unavailable.");
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
        <nav className="primary-nav" aria-label="Primary navigation">
          <a href="#following">Following</a>
          <a href="#research-thread" aria-current="page">Research desk</a>
          <a href="#investor-memory">Memory</a>
        </nav>
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
            <EmptyState title="No equities followed" body="Add an NSE or BSE ticker to begin research." />
          ) : (
            <div className="stock-list" aria-label="Followed equities">
              {stocks.map((stock) => (
                <button
                  className={`stock-row ${activeStock?.symbol === stock.symbol ? "is-active" : ""}`}
                  key={`${stock.exchange}-${stock.symbol}`}
                  type="button"
                  onClick={() => setActiveSymbol(stock.symbol)}
                  aria-pressed={activeStock?.symbol === stock.symbol}
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
              ))}
            </div>
          )}

          <div className="ingestion-summary">
            <div>
              <span>Source refresh</span>
              <strong>
                {formatRelativeTime(activeStock?.updatedAt, clock) ??
                  activeStock?.updatedLabel ??
                  "No ticker selected"}
              </strong>
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
              <div className="active-quote" aria-label={`${activeStock.symbol} current sample quote`}>
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
              <EmptyState title="Start a research thread" body="Ask about a followed company, recent sentiment, or fit with your memory." />
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
            <div className="quick-prompts" aria-label="Suggested research prompts">
              {QUICK_PROMPTS.map((prompt) => (
                <button type="button" key={prompt} onClick={() => void sendQuestion(prompt)}>
                  {prompt}
                </button>
              ))}
            </div>
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
                <strong id="sources-title">Sources used</strong>
              </span>
              <span aria-hidden="true">{sourcesOpen ? "Hide" : "Show"}</span>
            </button>
            {sourcesOpen ? (
              <div id="source-list" className="source-list">
                {sources.length === 0 ? (
                  <EmptyState title="No sources retrieved" body="Refresh this ticker, then ask a grounded question." />
                ) : (
                  sources.map((source, index) => (
                    <article
                      className={`source-item ${expandedSource === source.id ? "is-expanded" : ""}`}
                      id={`source-${source.id}`}
                      key={source.id}
                    >
                      <button
                        className="source-summary"
                        type="button"
                        onClick={() => setExpandedSource(expandedSource === source.id ? null : source.id)}
                        aria-expanded={expandedSource === source.id}
                      >
                        <span className="source-number">[{index + 1}]</span>
                        <span>
                          <small>{source.kind} / {source.publisher}</small>
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
    </div>
  );
}

function ConnectionBadge({ mode }: { mode: ConnectionMode }) {
  return (
    <span className={`connection-badge ${mode}`} aria-live="polite">
      <span aria-hidden="true" />
      {mode === "live" ? "Live data" : mode === "demo" ? "Sample data" : "Connecting"}
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
