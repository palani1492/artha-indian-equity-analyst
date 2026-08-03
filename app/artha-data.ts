export type MarketTone = "Constructive" | "Watch" | "Cautious";

export type Stock = {
  symbol: string;
  exchange: "NSE" | "BSE";
  company: string;
  sector: string;
  price: number;
  changePct: number;
  tone: MarketTone;
  indexedDocuments: number;
  updatedLabel: string;
  updatedAt?: string;
};

export type Persona = {
  risk: string;
  horizon: string;
  style: string;
  focus: string[];
  avoid: string[];
  note: string;
};

export type ResearchSource = {
  id: string;
  ticker?: string;
  publisher: string;
  title: string;
  kind: "Fundamentals" | "News" | "Exchange filing" | "Cited document";
  dateLabel: string;
  publishedAt?: string;
  url: string;
  excerpt: string;
};

export type Citation = {
  sourceId: string;
  label: string;
  source?: ResearchSource;
};

export type ChatMessage = {
  id: string;
  role: "assistant" | "user";
  text: string;
  title?: string;
  citations?: Citation[];
  createdLabel: string;
  createdAt?: string;
};

export const DEMO_STOCKS: Stock[] = [
  {
    symbol: "TCS",
    exchange: "NSE",
    company: "Tata Consultancy Services",
    sector: "IT services",
    price: 3036.2,
    changePct: 0.74,
    tone: "Constructive",
    indexedDocuments: 18,
    updatedLabel: "12 min ago",
  },
  {
    symbol: "RELIANCE",
    exchange: "NSE",
    company: "Reliance Industries",
    sector: "Diversified",
    price: 1398.4,
    changePct: -0.38,
    tone: "Watch",
    indexedDocuments: 24,
    updatedLabel: "18 min ago",
  },
  {
    symbol: "HDFCBANK",
    exchange: "NSE",
    company: "HDFC Bank",
    sector: "Private bank",
    price: 1997.8,
    changePct: 1.12,
    tone: "Constructive",
    indexedDocuments: 21,
    updatedLabel: "26 min ago",
  },
  {
    symbol: "INFY",
    exchange: "NSE",
    company: "Infosys",
    sector: "IT services",
    price: 1432.6,
    changePct: -1.06,
    tone: "Cautious",
    indexedDocuments: 15,
    updatedLabel: "31 min ago",
  },
];

export const DEMO_PERSONA: Persona = {
  risk: "Moderate",
  horizon: "3 to 5 years",
  style: "Quality at a fair price",
  focus: ["Durable cash flows", "Low leverage", "Governance"],
  avoid: ["High debt", "Uncited momentum calls"],
  note: "Prefers established Indian businesses and wants evidence before acting.",
};

export const DEMO_SOURCES: ResearchSource[] = [
  {
    id: "tcs-fundamentals",
    ticker: "TCS",
    publisher: "Screener",
    title: "Tata Consultancy Services consolidated fundamentals",
    kind: "Fundamentals",
    dateLabel: "Latest available row",
    url: "https://www.screener.in/company/TCS/consolidated/",
    excerpt:
      "Reference row for revenue, return ratios, balance sheet leverage, and valuation context.",
  },
  {
    id: "tcs-results",
    ticker: "TCS",
    publisher: "TCS Investor Relations",
    title: "Quarterly earnings and investor update",
    kind: "Exchange filing",
    dateLabel: "Latest indexed release",
    url: "https://www.tcs.com/who-we-are/investor-relations/financial-statements",
    excerpt:
      "Company-reported operating performance, deal commentary, and management outlook.",
  },
  {
    id: "tcs-news",
    ticker: "TCS",
    publisher: "Moneycontrol",
    title: "TCS market and demand coverage",
    kind: "News",
    dateLabel: "Recent indexed coverage",
    url: "https://www.moneycontrol.com/india/stockpricequote/computers-software/tataconsultancyservices/TCS",
    excerpt:
      "Recent market context used to compare demand signals with the fundamental record.",
  },
];

export const INITIAL_MESSAGES: ChatMessage[] = [
  {
    id: "welcome",
    role: "assistant",
    title: "Your research desk is ready.",
    text:
      "I can compare followed NSE and BSE companies against your investor memory. Every factual claim will point to an indexed source.",
    createdLabel: "Now",
  },
  {
    id: "sample-question",
    role: "user",
    text: "Which followed stock best fits my low-debt quality preference?",
    createdLabel: "Now",
  },
  {
    id: "sample-answer",
    role: "assistant",
    title: "TCS is the closest fit in the indexed sample",
    text:
      "The fundamentals record supports TCS as a quality candidate with low balance-sheet leverage [1]. Company reporting adds operating context, while recent coverage shows that demand conditions still need monitoring [2][3]. Treat this as a research lead, not a buy instruction. I do not have a live valuation snapshot in the sample data.",
    citations: [
      { sourceId: "tcs-fundamentals", label: "1", source: DEMO_SOURCES[0] },
      { sourceId: "tcs-results", label: "2", source: DEMO_SOURCES[1] },
      { sourceId: "tcs-news", label: "3", source: DEMO_SOURCES[2] },
    ],
    createdLabel: "Now",
  },
];
