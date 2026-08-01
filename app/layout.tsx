import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const baseUrl = siteUrl(requestHeaders);
  const title = "Artha | Indian Equity Research";
  const description =
    "A grounded, contextual research workspace for NSE and BSE equities.";
  const imageUrl = new URL("/og.png", baseUrl).toString();

  return {
    metadataBase: baseUrl,
    title: {
      default: title,
      template: "%s | Artha",
    },
    description,
    applicationName: "Artha",
    icons: {
      icon: "/favicon.svg",
      shortcut: "/favicon.svg",
    },
    openGraph: {
      type: "website",
      title,
      description,
      url: baseUrl,
      siteName: "Artha",
      images: [
        {
          url: imageUrl,
          width: 1200,
          height: 630,
          alt: "Artha Indian equity research workspace",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [imageUrl],
    },
  };
}

export const viewport: Viewport = {
  colorScheme: "light dark",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f2f4f1" },
    { media: "(prefers-color-scheme: dark)", color: "#101412" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}

function siteUrl(requestHeaders: Headers): URL {
  const configured = safeUrl(process.env.NEXT_PUBLIC_SITE_URL);
  const forwardedHost = requestHeaders.get("x-forwarded-host")?.split(",")[0]?.trim();
  const directHost = requestHeaders.get("host")?.trim();
  const host = forwardedHost || directHost;
  const forwardedProtocol = requestHeaders.get("x-forwarded-proto")?.split(",")[0]?.trim();
  const protocol = forwardedProtocol === "http" ? "http" : "https";

  if (host && /^[a-z0-9.-]+(?::\d{1,5})?$/i.test(host)) {
    const derived = safeUrl(`${protocol}://${host}`);
    if (derived) return derived;
  }
  return configured ?? new URL("http://localhost:3000");
}

function safeUrl(value: string | undefined): URL | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}
