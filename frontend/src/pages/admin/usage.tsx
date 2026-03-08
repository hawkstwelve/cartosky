import { useEffect, useState } from "react";
import { BarChart3 } from "lucide-react";

import { fetchAdminUsageSummary, fetchTwfStatus, type TwfStatus } from "@/lib/admin-api";

export default function AdminUsagePage() {
  const [status, setStatus] = useState<TwfStatus | null>(null);
  const [events, setEvents] = useState<Array<{ event_name: string; count: number }>>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const authStatus = await fetchTwfStatus();
        if (cancelled) return;
        setStatus(authStatus);
        if (!authStatus.linked || !authStatus.admin) {
          return;
        }
        const summary = await fetchAdminUsageSummary("30d");
        if (cancelled) return;
        setEvents(summary.events);
      } catch (nextError) {
        if (cancelled) return;
        setError(nextError instanceof Error ? nextError.message : "Failed to load usage summary");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!status?.linked || !status.admin) {
    return (
      <section className="rounded-[28px] border border-white/12 bg-black/28 p-6 text-white shadow-[0_16px_42px_rgba(0,0,0,0.3)] backdrop-blur-xl">
        Usage analytics will appear here after admin access is available and events begin flowing.
      </section>
    );
  }

  return (
    <section className="rounded-[32px] border border-white/12 bg-black/28 p-6 text-white shadow-[0_16px_42px_rgba(0,0,0,0.3)] backdrop-blur-xl">
      <div className="flex items-start gap-3">
        <div className="rounded-2xl border border-white/12 bg-white/[0.05] p-3">
          <BarChart3 className="h-5 w-5 text-[#9dd5bf]" />
        </div>
        <div>
          <div className="text-2xl font-semibold tracking-tight">Usage groundwork</div>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-white/62">
            Phase 1 wires low-cost usage events now so the schema is in place before real traffic arrives. This page is intentionally light for now.
          </p>
        </div>
      </div>

      {error ? (
        <div className="mt-5 rounded-2xl border border-red-400/20 bg-red-500/10 px-4 py-3 text-sm text-red-100">
          {error}
        </div>
      ) : null}

      <div className="mt-6 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {events.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.03] px-4 py-8 text-sm text-white/48">
            No usage events recorded yet.
          </div>
        ) : (
          events.map((event) => (
            <div key={event.event_name} className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-4">
              <div className="text-sm font-semibold text-white">{event.event_name}</div>
              <div className="mt-3 text-3xl font-semibold tracking-tight text-[#9dd5bf]">{event.count}</div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}
