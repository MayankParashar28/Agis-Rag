"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/hooks";
import AuthShell from "@/components/AuthShell";
import { Alert, Spinner } from "@/components/ui";

export default function RegisterPage() {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password || !fullName) return;
    setError(null);
    setLoading(true);
    try {
      await api.signup({ email, password, full_name: fullName });
      setSuccess(true);
      setTimeout(() => router.push("/login"), 1200);
    } catch (err) {
      setError(errorMessage(err, "Could not create the account. Please try again."));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell
      title="Create your account"
      subtitle="Set up a workspace for your documents in a minute."
      footer={<>Already have an account? <Link href="/login" className="font-semibold text-foreground underline-offset-4 hover:underline">Sign in</Link></>}
    >
      {error && <div className="mb-5"><Alert tone="danger">{error}</Alert></div>}
      {success && <div className="mb-5"><Alert tone="success">Account created. Taking you to sign in…</Alert></div>}
      <form onSubmit={handleRegister} className="space-y-4">
        <div>
          <label htmlFor="full-name" className="label">Full name</label>
          <input id="full-name" required autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} placeholder="Jane Doe" className="input h-11" />
        </div>
        <div>
          <label htmlFor="email" className="label">Work email</label>
          <input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" className="input h-11" />
        </div>
        <div>
          <label htmlFor="password" className="label">Password</label>
          <div className="relative">
            <input id="password" type={showPassword ? "text" : "password"} required minLength={8} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} className="input h-11 pr-11" />
            <button type="button" onClick={() => setShowPassword(!showPassword)} className="icon-btn absolute right-1.5 top-1/2 -translate-y-1/2" aria-label={showPassword ? "Hide password" : "Show password"}>
              {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </div>
          <p className="mt-1.5 text-xs text-muted-foreground">At least 8 characters.</p>
        </div>
        <button type="submit" disabled={loading || success} className="btn btn-primary h-11 w-full">
          {loading && <Spinner />}{loading ? "Creating account…" : "Create account"}
        </button>
      </form>
    </AuthShell>
  );
}
