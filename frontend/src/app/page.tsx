"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { authStorage } from "@/lib/api";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const token = authStorage.getToken();
    if (token) {
      router.push("/dashboard");
    } else {
      router.push("/login");
    }
  }, [router]);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-background text-foreground p-6">
      <div className="flex flex-col items-center space-y-8 animate-pulse duration-[3000ms]">
        <div className="w-12 h-px bg-foreground" />
        <h1 className="text-4xl font-serif tracking-widest uppercase">Agis</h1>
        <p className="text-sm text-muted-foreground italic font-serif">Authenticating sequence...</p>
      </div>
    </div>
  );
}
