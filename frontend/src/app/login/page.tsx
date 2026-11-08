"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import AuthShell from "@/components/AuthShell";
import { Alert, Spinner } from "@/components/ui";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) return;
    setError(null);
    setLoading(true);
    try {
      const res = await api.login({ email, password });
      // Members go straight to their workspace; the dashboard is admin-only.
      router.push(res.user.role === "admin" ? "/dashboard" : "/chat");
    } catch (err) {
      setError(errorMessage(err, "Sign-in failed. Check your email and password."));
      setLoading(false);
    }
  };

  return (
    <AuthShell
      title="Sign in"
      subtitle="Welcome back. Pick up where you left off."
      footer={<>New here? <Link href="/register" className="font-semibold text-foreground underline-offset-4 hover:underline">Create an account</Link></>}
    >
      {error && <div className="mb-5"><Alert tone="danger">{error}</Alert></div>}
      <form onSubmit={handleLogin} className="space-y-4">
        <div>
          <label htmlFor="email" className="label">Email</label>
          <input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" className="input h-11" />
        </div>
        <div>
          <label htmlFor="password" className="label">Password</label>
          <div className="relative">
            <input id="password" type={showPassword ? "text" : "password"} required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className="input h-11 pr-11" />
            <button type="button" onClick={() => setShowPassword(!showPassword)} className="icon-btn absolute right-1.5 top-1/2 -translate-y-1/2" aria-label={showPassword ? "Hide password" : "Show password"}>
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
        </div>
        <button type="submit" disabled={loading} className="btn btn-primary h-11 w-full">
          {loading && <Spinner />}{loading ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </AuthShell>
  );
}
