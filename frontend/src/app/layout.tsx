import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import "./globals.css";
import LayoutWrapper from "@/components/layout/LayoutWrapper";
import Script from "next/script";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  display: "swap",
});

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Agis RAG | AI Search Platform",
  description: "Next-generation Agentic Retrieval-Augmented Generation platform.",
  keywords: [
    "RAG",
    "AI Search",
    "Agentic RAG",
    "Enterprise Search",
    "Retrieval-Augmented Generation",
    "Agis",
    "Vector Search",
    "LLM Search Agent"
  ],
  authors: [{ name: "Agis Team" }],
  creator: "Agis",
  publisher: "Agis",
  robots: {
    index: true,
    follow: true,
    googleBot: {
      index: true,
      follow: true,
      "max-video-preview": -1,
      "max-image-preview": "large",
      "max-snippet": -1,
    },
  },
  openGraph: {
    title: "Agis RAG | AI Search Platform",
    description: "Next-generation Agentic Retrieval-Augmented Generation platform.",
    url: "https://agisrag.vercel.app",
    siteName: "Agis RAG",
    locale: "en_US",
    type: "website",
    alternateLocale: ["en_GB", "es_ES", "fr_FR"],
  },
  twitter: {
    card: "summary_large_image",
    title: "Agis RAG | AI Search Platform",
    description: "Next-generation Agentic Retrieval-Augmented Generation platform.",
    creator: "@agis_rag",
  },
  alternates: {
    canonical: "https://agisrag.vercel.app",
    languages: {
      "en-US": "https://agisrag.vercel.app/en-US",
      "en-GB": "https://agisrag.vercel.app/en-GB",
      "es-ES": "https://agisrag.vercel.app/es-ES",
      "fr-FR": "https://agisrag.vercel.app/fr-FR",
      "x-default": "https://agisrag.vercel.app",
    },
  },
  other: {
    "geo.region": "US-CA",
    "geo.placename": "San Francisco",
    "geo.position": "37.7749;-122.4194",
    "ICBM": "37.7749, -122.4194",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className={`${inter.variable} ${playfair.variable} font-sans min-h-screen text-foreground bg-background antialiased`}>
        <Script
          src="https://www.googletagmanager.com/gtag/js?id=G-FVVHHM9J27"
          strategy="afterInteractive"
        />
        <Script id="google-analytics" strategy="afterInteractive">
          {`
            window.dataLayer = window.dataLayer || [];
            function gtag(){dataLayer.push(arguments);}
            gtag('js', new Date());

            gtag('config', 'G-FVVHHM9J27');
          `}
        </Script>
        {/* Global Paper Noise Overlay */}
        <div className="pointer-events-none fixed inset-0 z-50 bg-noise opacity-[0.03]" />
        
        {/* Architectural Grid Lines */}
        <div className="pointer-events-none fixed inset-0 z-0 flex justify-center overflow-hidden">
          <div className="w-full max-w-[1600px] h-full flex justify-between px-8 md:px-16">
            <div className="w-px h-full bg-[#1A1A1A] opacity-[0.06]" />
            <div className="w-px h-full bg-[#1A1A1A] opacity-[0.06] hidden md:block" />
            <div className="w-px h-full bg-[#1A1A1A] opacity-[0.06] hidden lg:block" />
            <div className="w-px h-full bg-[#1A1A1A] opacity-[0.06]" />
          </div>
        </div>

        <div className="relative z-10">
          <LayoutWrapper>{children}</LayoutWrapper>
        </div>
      </body>
    </html>
  );
}
