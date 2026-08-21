"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { readSession } from "@/lib/auth";

export default function HomePage() {
  const router = useRouter();
  useEffect(() => {
    router.replace(readSession() ? "/dashboard" : "/login");
  }, [router]);
  return <p className="p-8 text-sm text-slate-400">Opening supervisor workspace…</p>;
}
