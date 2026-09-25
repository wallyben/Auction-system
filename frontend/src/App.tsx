import { useQuery } from "@tanstack/react-query";
import { ClipboardList, Gavel, LayoutDashboard, LineChart, Radio, Star } from "lucide-react";
import { NavLink, Route, Routes } from "react-router-dom";
import { AuctionPage, AuctionsPage, ComparePage, DiligencePage, MarketPage, OverviewPage, SourcesPage, VehiclePage } from "./pages";

const links = [
  ["/", "Overview", LayoutDashboard],
  ["/auctions", "Auctions", Gavel],
  ["/shortlist", "Shortlist", Star],
  ["/diligence", "Diligence", ClipboardList],
  ["/market", "Market", LineChart],
  ["/sources", "Sources", Radio],
] as const;

export function App() {
  const online = useQuery({ queryKey: ["overview"], queryFn: async () => true, retry: false });
  return (
    <div className="min-h-screen md:grid md:grid-cols-[220px_1fr]">
      <aside className="hidden md:flex md:flex-col gap-1 border-r border-stone-800 bg-[#0c1014] p-4">
        <p className="mb-6 px-2 text-lg tracking-wide text-emerald-100">ARIE-CV</p>
        {links.map(([to, label, Icon]) => (
          <NavLink key={label} to={to} className={({ isActive }) => `flex items-center gap-2 rounded-lg px-3 py-2 text-sm ${isActive ? "bg-emerald-950 text-emerald-100" : "text-stone-400 hover:bg-stone-900"}`}>
            <Icon size={16} /> {label}
          </NavLink>
        ))}
      </aside>
      <main className="pb-24 md:pb-0">
        {!online.isError ? null : <p className="bg-amber-950 px-4 py-2 text-sm">Connection unavailable.</p>}
        <Routes>
          <Route path="/" element={<OverviewPage />} />
          <Route path="/auctions" element={<AuctionsPage />} />
          <Route path="/auctions/:id" element={<AuctionPage />} />
          <Route path="/lots/:id" element={<VehiclePage />} />
          <Route path="/shortlist" element={<ComparePage />} />
          <Route path="/diligence" element={<DiligencePage />} />
          <Route path="/market" element={<MarketPage />} />
          <Route path="/sources" element={<SourcesPage />} />
        </Routes>
      </main>
      <nav className="fixed inset-x-0 bottom-0 flex justify-around border-t border-stone-800 bg-[#0c1014] p-2 md:hidden">
        {links.slice(0, 5).map(([to, label, Icon]) => (
          <NavLink key={label} to={to} className="flex flex-col items-center text-[10px] text-stone-400">
            <Icon size={16} /> {label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
