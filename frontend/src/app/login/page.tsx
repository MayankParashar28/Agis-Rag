"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Eye, EyeOff } from "lucide-react";
import { api } from "@/lib/api";

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
      await api.login({ email, password });
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Failed to log in. Please check your credentials.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-screen overflow-hidden flex flex-col md:flex-row bg-background">
      {/* Left Section - Editorial Imagery / Branding */}
      <div className="md:w-5/12 lg:w-1/2 relative hidden md:flex flex-col justify-end p-16 overflow-hidden bg-muted-background">
        <div className="absolute inset-0 bg-[url('https://images.unsplash.com/photo-1600585154340-be6161a56a0c?q=80&w=2070&auto=format&fit=crop')] bg-cover bg-center grayscale opacity-80 mix-blend-multiply transition-all duration-[2000ms] hover:grayscale-0 animate-slow-zoom" />
        
        <div className="relative z-10">
          <div className="w-12 h-px bg-foreground mb-6" />
          <h1 className="text-6xl lg:text-8xl font-serif text-foreground leading-[0.9] tracking-tight mb-4">
            Agis <br /><span className="italic text-accent">RAG</span>
          </h1>
          <p className="text-lg text-foreground font-sans max-w-sm mt-6">
            Secure, Intelligent Enterprise Retrieval. Chat with your organizational knowledge effortlessly.
          </p>
        </div>
        
        {/* Vertical Decorative Label */}
        <div className="absolute top-16 right-16 writing-mode-vertical text-xs tracking-[0.3em] uppercase text-foreground">
          Vol. 01 / Authentication
        </div>
      </div>

      {/* Right Section - Minimalist Form */}
      <div className="flex-1 flex items-center justify-center p-8 md:p-16 lg:p-24 relative bg-background">
        <div className="w-full max-w-[400px]">
          <div className="mb-16">
            <h2 className="text-4xl lg:text-5xl font-serif text-foreground mb-4">Sign In</h2>
            <p className="text-muted-foreground text-sm tracking-wide">Enter your credentials to access your workspace.</p>
          </div>

          {error && (
            <div className="mb-8 p-4 border border-foreground text-foreground text-sm font-medium">
              {error}
            </div>
          )}

          <form onSubmit={handleLogin} className="space-y-12">
            <div className="space-y-2">
              <label className="block text-xs font-medium text-foreground uppercase tracking-[0.2em]">
                Email Address
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@company.com"
                className="w-full py-3 bg-transparent border-b border-foreground text-foreground placeholder:text-muted-foreground placeholder:italic placeholder:font-serif focus:outline-none focus:border-accent transition-colors duration-500 rounded-none"
              />
            </div>

            <div className="space-y-2">
              <div className="flex justify-between items-end">
                <label className="block text-xs font-medium text-foreground uppercase tracking-[0.2em]">
                  Password
                </label>
                <a href="#" className="text-xs text-muted-foreground hover:text-accent transition-colors duration-500 underline decoration-1 underline-offset-4">
                  Forgot?
                </a>
              </div>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Password"
                  className="w-full py-3 pr-10 bg-transparent border-b border-foreground text-foreground placeholder:text-muted-foreground placeholder:italic placeholder:font-serif focus:outline-none focus:border-accent transition-colors duration-500 rounded-none"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-0 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors p-2"
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              className="group relative w-full h-14 overflow-hidden bg-foreground text-background font-medium text-xs uppercase tracking-[0.2em] transition-all duration-500 disabled:opacity-50"
            >
              <span className="absolute inset-0 w-full h-full bg-accent translate-x-[-100%] group-hover:translate-x-0 transition-transform duration-500 ease-[cubic-bezier(0.25,0.46,0.45,0.94)] z-0" />
              <span className="relative z-10 flex items-center justify-center w-full h-full transition-colors duration-500 group-hover:text-foreground">
                {loading ? "Authenticating..." : "Sign In"}
              </span>
            </button>
          </form>

          <div className="mt-16 pt-8 border-t border-foreground/10 flex justify-between items-center text-xs text-muted-foreground tracking-widest uppercase">
            <span>New here?</span>
            <Link href="/register" className="text-foreground hover:text-accent transition-colors duration-500 border-b border-transparent hover:border-accent">
              Create Account
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
