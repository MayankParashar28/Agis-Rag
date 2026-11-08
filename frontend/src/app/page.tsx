"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { authStorage } from "@/lib/api";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    if (!authStorage.getToken()) router.replace("/login");
    else router.replace(authStorage.getUser()?.role === "admin" ? "/dashboard" : "/chat");
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      <span className="font-serif text-2xl tracking-tight text-foreground">
        Agis <span className="italic text-accent">RAG</span>
      </span>
    </div>
  );
}
