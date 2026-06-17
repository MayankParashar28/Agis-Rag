import type { Metadata } from "next";
import { Inter, Playfair_Display } from "next/font/google";
import "./globals.css";
import LayoutWrapper from "@/components/layout/LayoutWrapper";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const playfair = Playfair_Display({
  variable: "--font-playfair",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Aegis RAG | Enterprise AI Search Platform",
  description: "Next-generation Agentic Retrieval-Augmented Generation platform.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full">
      <body className={`${inter.variable} ${playfair.variable} font-sans min-h-screen text-foreground bg-background antialiased`}>
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
