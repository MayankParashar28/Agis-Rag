"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { api } from "@/lib/api";

function VerifyEmailContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("Invalid verification link.");
      return;
    }

    api.verifyEmail(token)
      .then((res) => {
        setStatus("success");
        setMessage(res.msg || "Your email has been verified successfully!");
      })
      .catch((err) => {
        setStatus("error");
        setMessage(err.message || "Failed to verify email. The link may have expired.");
      });
  }, [token]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-6">
      <div className="max-w-md w-full bg-card/50 border border-card-border rounded-2xl p-8 text-center shadow-xl">
        <h2 className="text-2xl font-bold text-foreground mb-6">Email Verification</h2>
        
        {status === "loading" && (
          <div className="flex flex-col items-center space-y-4">
            <Loader2 className="w-10 h-10 text-primary animate-spin" />
            <p className="text-text-muted">Verifying your email address...</p>
          </div>
        )}

        {status === "success" && (
          <div className="flex flex-col items-center space-y-4 animate-in zoom-in duration-300">
            <CheckCircle2 className="w-16 h-16 text-green-500" />
            <p className="text-lg text-green-400 font-medium">{message}</p>
            <Link 
              href="/login"
              className="mt-6 px-8 py-3 bg-primary hover:bg-primary-hover text-background rounded-xl font-bold transition-all shadow-[0_0_15px_rgba(var(--primary),0.3)]"
            >
              Sign In Now
            </Link>
          </div>
        )}

        {status === "error" && (
          <div className="flex flex-col items-center space-y-4 animate-in zoom-in duration-300">
            <XCircle className="w-16 h-16 text-red-500" />
            <p className="text-lg text-red-400 font-medium">{message}</p>
            <Link 
              href="/login"
              className="mt-6 px-8 py-3 bg-secondary hover:bg-secondary/80 text-foreground rounded-xl font-bold transition-all"
            >
              Back to Login
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-background" />}>
      <VerifyEmailContent />
    </Suspense>
  );
}
