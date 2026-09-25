import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { toast } from "sonner";
import { Auction, Lot, cv, money } from "./api";

function badge(status: string) {
  const tone = status === "HARD REJECT" ? "bg-red-950 text-red-200" : status === "TAX DILIGENCE" ? "bg-amber-950 text-amber-100" : status === "MARKET READY" || status === "BUY READY" ? "bg-emerald-950 text-emerald-100" : "bg-stone-800 text-stone-300";
  return <span className={`rounded-full px-2 py-1 text-xs ${tone}`}>{status}</span>;
}

function Shell({ title, children }: { title: string; children: ReactNode }) {
  return <section className="mx-auto max-w-6xl px-4 py-6"><h1 className="mb-4 text-2xl text-stone-100">{title}</h1>{children}</section>;
}

export function OverviewPage() {
  const query = useQuery({ queryKey: ["overview"], queryFn: cv.overview });
  if (query.isLoading) return <Shell title="Overview"><p>Loading the auction book…</p></Shell>;
  if (query.isError) return <Shell title="Overview"><p>Could not reach ARIE. Refresh when the connection is back.</p></Shell>;
  const data = query.data!;
  const counts = data.counts;
  return (
    <Shell title="What needs attention">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Market priced" value={counts.priced} />
        <Stat label="Need documents" value={counts.tax_diligence} />
        <Stat label="Hard rejected" value={counts.hard_reject} />
      </div>
      <div className="mt-6 grid gap-3">
        {data.auctions.map((auction) => <AuctionCard key={auction.auction_id} auction={auction} />)}
        {data.auctions.length === 0 && <p>No auctions yet. Import one from the Auctions page.</p>}
      </div>
      <h2 className="mb-3 mt-8 text-lg">Vehicles that need a decision</h2>
      <div className="grid gap-2">{data.attention.map((lot) => <VehicleRow key={lot.lot_id} lot={lot} />)}</div>
    </Shell>
  );
}

export function AuctionsPage() {
  const query = useQuery({ queryKey: ["auctions"], queryFn: cv.auctions });
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const importAuction = useMutation({
    mutationFn: () => cv.importText(text),
    onSuccess: () => { toast.success("Auction imported"); setOpen(false); client.invalidateQueries(); },
    onError: (error: Error) => toast.error(error.message),
  });
  return (
    <Shell title="Auctions">
      <button className="mb-4 rounded-lg bg-emerald-800 px-3 py-2 text-sm" onClick={() => setOpen(true)}>Import auction</button>
      {open && (
        <div className="mb-4 rounded-xl border border-stone-700 bg-stone-900 p-4">
          <p className="mb-2 text-sm text-stone-400">Paste a catalogue, or drop a text file.</p>
          <input type="file" accept=".txt,text/plain" className="mb-2 block text-sm" onChange={async (event) => setText(await event.target.files?.[0]?.text() || "")} />
          <textarea className="h-32 w-full rounded-lg bg-stone-950 p-2 text-sm" value={text} onChange={(event) => setText(event.target.value)} placeholder="Paste catalogue text" />
          <button className="mt-2 rounded-lg bg-emerald-800 px-3 py-2 text-sm" onClick={() => importAuction.mutate()}>Import</button>
        </div>
      )}
      <div className="grid gap-3">{query.data?.auctions.map((auction) => <AuctionCard key={auction.auction_id} auction={auction} />)}</div>
    </Shell>
  );
}

function AuctionCard({ auction }: { auction: Auction }) {
  return (
    <Link to={`/auctions/${auction.auction_id}`} className="block rounded-xl border border-stone-800 bg-stone-900/70 p-4">
      <div className="flex items-baseline justify-between gap-3"><h2 className="text-lg">{auction.title}</h2><span className="text-sm text-stone-400">{auction.sale_code}</span></div>
      <p className="mt-2 text-sm text-stone-400">{auction.lots} vans · {auction.priced} priced · {auction.selected} selected · {auction.tax_diligence} need documents · {auction.hard_reject} rejected</p>
    </Link>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div className="rounded-xl border border-stone-800 bg-stone-900/70 p-4"><p className="text-sm text-stone-400">{label}</p><p className="text-3xl">{value}</p></div>;
}

export function AuctionPage() {
  const { id = "" } = useParams();
  const query = useQuery({ queryKey: ["auction", id], queryFn: () => cv.auction(id) });
  const [filter, setFilter] = useState("All");
  const [sort, setSort] = useState("lot");
  const refresh = useMutation({ mutationFn: () => cv.refresh(id), onSuccess: (result) => toast.success(result.queued ? "Market refresh queued" : "Refresh was not queued") });
  const lots = useMemo(() => {
    const rows = query.data?.vehicles || [];
    const filtered = rows.filter((lot) => filter === "All" || lot.status === filter.toUpperCase() || (filter === "Selected" && lot.selected));
    return [...filtered].sort((a, b) => sort === "floor" ? Number(b.market_floor || 0) - Number(a.market_floor || 0) : Number(a.lot_number) - Number(b.lot_number));
  }, [query.data, filter, sort]);
  if (!query.data) return <Shell title="Auction"><p>Loading…</p></Shell>;
  const auction = query.data;
  return (
    <Shell title={auction.title}>
      <div className="mb-4 flex flex-wrap gap-2 text-sm text-stone-400">
        <span>{auction.currency} · FX {auction.fx || "—"}</span>
        <button className="rounded-lg border border-stone-700 px-2 py-1" onClick={() => refresh.mutate()}>Refresh market</button>
      </div>
      <div className="mb-4 grid gap-3 sm:grid-cols-4">
        <Stat label="Relevant" value={auction.lots} />
        <Stat label="Priced" value={auction.priced} />
        <Stat label="Documents" value={auction.tax_diligence} />
        <Stat label="Rejected" value={auction.hard_reject} />
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        {["All", "Selected", "TAX DILIGENCE", "MARKET INSUFFICIENT", "HARD REJECT", "MARKET READY"].map((item) => (
          <button key={item} className={`rounded-full px-3 py-1 text-xs ${filter === item ? "bg-emerald-900" : "bg-stone-800"}`} onClick={() => setFilter(item)}>{item}</button>
        ))}
        <select className="rounded-lg bg-stone-900 px-2" value={sort} onChange={(event) => setSort(event.target.value)}>
          <option value="lot">Lot</option>
          <option value="floor">Market floor</option>
        </select>
      </div>
      <div className="grid gap-2">{lots.map((lot) => <VehicleRow key={lot.lot_id} lot={lot} />)}</div>
    </Shell>
  );
}

function VehicleRow({ lot }: { lot: Lot }) {
  const client = useQueryClient();
  const select = useMutation({
    mutationFn: () => cv.select(lot.lot_id, !lot.selected),
    onSuccess: () => client.invalidateQueries(),
  });
  return (
    <article className="grid gap-2 rounded-xl border border-stone-800 bg-stone-900/60 p-3 sm:grid-cols-[auto_1fr_auto]">
      <button aria-label={lot.selected ? "Unselect" : "Select"} onClick={() => select.mutate()} className={lot.selected ? "text-amber-300" : "text-stone-500"}><Star size={18} /></button>
      <Link to={`/lots/${lot.lot_id}`}>
        <p className="text-sm text-stone-400">Lot {lot.lot_number} · {lot.registration || "no plate"} · {lot.year || "—"} · {lot.mileage_km ? `${lot.mileage_km.toLocaleString()} km` : "mileage unknown"}</p>
        <p>{lot.vehicle}</p>
      </Link>
      <div className="text-sm">
        {badge(lot.status)}
        <p className="mt-1">Floor {money(lot.market_floor)}</p>
        <p>Pre-tax {money(lot.pre_tax_ceiling)}</p>
        <p>Safe hammer {lot.final_safe_hammer ? money(lot.final_safe_hammer) : "Awaiting tax evidence"}</p>
      </div>
    </article>
  );
}

export function VehiclePage() {
  const { id = "" } = useParams();
  const query = useQuery({ queryKey: ["lot", id], queryFn: () => cv.lot(id) });
  const [tab, setTab] = useState("Overview");
  const [bid, setBid] = useState("");
  const client = useQueryClient();
  const saveBid = useMutation({
    mutationFn: () => cv.bid(id, bid),
    onSuccess: () => { toast.success("Bid saved"); client.invalidateQueries(); },
  });
  if (!query.data) return <Shell title="Vehicle"><p>Loading…</p></Shell>;
  const lot = query.data;
  const economics = (lot.evaluation?.economics || {}) as Record<string, string | null>;
  return (
    <Shell title={`Lot ${lot.lot_number}`}>
      <p className="text-stone-400">{lot.vehicle}</p>
      <p className="mb-4 text-sm">{badge(lot.status)} <span className="ml-2 text-stone-400">{lot.provenance_plain}</span></p>
      <div className="mb-4 grid gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-stone-800 p-4"><p className="text-sm text-stone-400">Current bid</p><p className="text-2xl">{lot.current_bid_gbp ? `£${lot.current_bid_gbp}` : "—"}</p></div>
        <div className="rounded-xl border border-stone-800 p-4"><p className="text-sm text-stone-400">Market floor</p><p className="text-2xl">{money(lot.market_floor)}</p></div>
        <div className="rounded-xl border border-stone-800 p-4"><p className="text-sm text-stone-400">Pre-tax ceiling</p><p className="text-2xl">{money(lot.pre_tax_ceiling)}</p></div>
        <div className="rounded-xl border border-stone-800 p-4"><p className="text-sm text-stone-400">Final safe hammer</p><p className="text-2xl">{lot.final_safe_hammer ? money(lot.final_safe_hammer) : "Awaiting tax evidence"}</p><p className="text-xs text-stone-500">Headroom {lot.headroom_status === "KNOWN" ? "known" : "unknown"}</p></div>
      </div>
      <form className="mb-4 flex gap-2" onSubmit={(event) => { event.preventDefault(); saveBid.mutate(); }}>
        <input aria-label="Current bid GBP" className="rounded-lg bg-stone-900 px-3 py-2" placeholder="Current bid GBP" value={bid} onChange={(event) => setBid(event.target.value)} />
        <button className="rounded-lg bg-stone-700 px-3">Save bid</button>
      </form>
      <div className="mb-3 flex flex-wrap gap-3 text-sm">{["Overview", "Market", "Costs", "Diligence", "Evidence", "Audit"].map((item) => <button key={item} className={tab === item ? "text-emerald-200" : "text-stone-500"} onClick={() => setTab(item)}>{item}</button>)}</div>
      {tab === "Overview" && <div className="space-y-2 text-sm"><p>{lot.provenance_plain}</p><p>Market confidence {lot.market_confidence || "—"} · {plainDiversity(lot.dealer_diversity)}</p><p>What would change this: {(lot.blockers || []).join("; ") || "Nothing further is blocking a market view."}</p></div>}
      {tab === "Market" && <MarketChart lot={lot} />}
      {tab === "Costs" && <CostList economics={economics} lot={lot} />}
      {tab === "Diligence" && <ul className="space-y-2">{(lot.blockers || []).map((blocker) => <li key={blocker} className="rounded-lg border border-stone-800 p-3 text-sm"><strong>{blocker}</strong><p className="text-stone-400">Missing. This blocks a final safe hammer. Add evidence when you have it. Marking a task requested does not prove it.</p></li>)}{!(lot.blockers || []).length && <p>No open diligence.</p>}</ul>}
      {tab === "Evidence" && <EvidenceForm lot={lot} />}
      {tab === "Audit" && <pre className="overflow-auto rounded-lg bg-stone-950 p-3 text-xs">{JSON.stringify({ state: lot.technical_state, provenance: lot.provenance, blockers: lot.blockers }, null, 2)}</pre>}
      <button className="mt-4 text-sm text-stone-400" onClick={() => navigator.clipboard.writeText(lot.request_pack || "")}>Copy request</button>
    </Shell>
  );
}

function plainDiversity(value: string | null) {
  if (value === "DIVERSE_PROVEN") return "Several named dealers";
  if (value === "DIVERSITY_LIKELY") return "Several sources, named dealers incomplete";
  if (value === "CONCENTRATED") return "One dealer dominates the evidence";
  return "Dealer mix not proven";
}

const COST_LABELS: Record<string, string> = {
  customs_status: "Customs duty",
  import_vat_status: "Import VAT",
  vrt_status: "VRT",
  pre_tax_hammer_ceiling_eur: "Pre-tax ceiling",
  final_max_safe_hammer_eur: "Final safe hammer",
};

function MarketChart({ lot }: { lot: Lot }) {
  const valuation = (lot.evaluation?.valuation || {}) as { comps?: { mileage_km?: number; price_eur?: string }[] };
  const data = (valuation.comps || []).filter((comp) => comp.mileage_km && comp.price_eur).map((comp) => ({ x: comp.mileage_km, y: Number(comp.price_eur) }));
  if (!data.length) return <p className="text-sm text-stone-400">No comparable points are stored on this snapshot.</p>;
  return (
    <div className="h-72 w-full">
      <ResponsiveContainer>
        <ScatterChart>
          <XAxis dataKey="x" name="km" tick={{ fill: "#a8a29e", fontSize: 12 }} />
          <YAxis dataKey="y" name="EUR" tick={{ fill: "#a8a29e", fontSize: 12 }} width={64} />
          <Tooltip />
          <Scatter data={data} fill="#86efac" r={6} />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}

function CostList({ economics, lot }: { economics: Record<string, string | null>; lot: Lot }) {
  const lines = Object.keys(COST_LABELS);
  return <ul className="space-y-1 text-sm">{lines.map((key) => <li key={key} className="flex justify-between gap-4 border-b border-stone-800 py-2"><span>{COST_LABELS[key]}</span><span className="text-right">{economics[key] ? (key.endsWith("_eur") ? money(economics[key]) : plainCost(economics[key])) : "UNKNOWN"}</span></li>)}<li className="pt-2">Safe headroom {lot.headroom_status === "KNOWN" ? "shown above" : "UNKNOWN — not calculated from the pre-tax ceiling"}</li></ul>;
}

function plainCost(value: string) {
  if (value === "UNKNOWN") return "UNKNOWN";
  if (value === "TARIFF_CLASSIFICATION_REQUIRED") return "Customs duty not confirmed";
  if (value === "BLOCKED_DUTY_UNKNOWN") return "Waiting on the duty rate";
  return value.replaceAll("_", " ");
}

function EvidenceForm({ lot }: { lot: Lot }) {
  const client = useQueryClient();
  const [kind, setKind] = useState("V5C");
  const [reference, setReference] = useState("");
  const send = useMutation({
    mutationFn: async () => {
      const body = new FormData();
      body.set("kind", kind);
      body.set("reference", reference);
      const response = await fetch(`/api/cv/v1/lots/${lot.lot_id}/evidence`, { method: "POST", body });
      if (!response.ok) throw new Error("Evidence was not accepted");
      return response.json();
    },
    onSuccess: () => { toast.success("Evidence recorded and the vehicle was re-evaluated"); client.invalidateQueries(); },
  });
  return (
    <form className="grid max-w-md gap-2" onSubmit={(event) => { event.preventDefault(); send.mutate(); }}>
      <label>Kind<select className="ml-2 rounded bg-stone-900" value={kind} onChange={(event) => setKind(event.target.value)}>{["V5C", "VIN", "COC", "NI_IMPORT_DECLARATION", "SERVICE_RECORD", "WEIGHT_PLATE"].map((item) => <option key={item}>{item}</option>)}</select></label>
      <input aria-label="Reference" className="rounded bg-stone-900 px-2 py-1" placeholder="Reference" value={reference} onChange={(event) => setReference(event.target.value)} />
      <button className="rounded bg-emerald-800 px-3 py-2 text-sm">Save evidence</button>
      <ul className="text-sm text-stone-400">{(lot.evidence || []).map((item) => <li key={item.evidence_id}>{item.kind} {item.filename}</li>)}</ul>
    </form>
  );
}

export function ComparePage() {
  const query = useQuery({ queryKey: ["shortlist"], queryFn: cv.shortlist });
  const lots = query.data?.lots || [];
  return (
    <Shell title="Shortlist">
      {lots.length === 0 && <p>Select a star on a vehicle. The choice is stored in the database.</p>}
      <div className="grid gap-3 md:grid-cols-2">{lots.slice(0, 4).map((lot) => <VehicleRow key={lot.lot_id} lot={lot} />)}</div>
      {lots.length > 1 && (
        <table className="mt-4 w-full text-left text-sm">
          <thead><tr>{lots.slice(0, 4).map((lot) => <th key={lot.lot_id} className="p-2">Lot {lot.lot_number}</th>)}</tr></thead>
          <tbody>
            <tr>{lots.slice(0, 4).map((lot) => <td key={lot.lot_id} className="p-2">Floor {money(lot.market_floor)}<br />Pre-tax {money(lot.pre_tax_ceiling)}<br />Safe {lot.final_safe_hammer ? money(lot.final_safe_hammer) : "UNKNOWN"}<br />{lot.provenance_plain}</td>)}</tr>
          </tbody>
        </table>
      )}
    </Shell>
  );
}

export function DiligencePage() {
  const query = useQuery({ queryKey: ["diligence"], queryFn: cv.diligence });
  return (
    <Shell title="Diligence">
      <p className="mb-3 text-sm text-stone-400">Ordered by the vehicles already on the book. This is not a purchase recommendation.</p>
      <div className="grid gap-2">{(query.data?.tasks || []).map((task) => <Link key={`${task.lot_id}-${task.blocker}`} to={`/lots/${task.lot_id}`} className="rounded-lg border border-stone-800 p-3 text-sm"><strong>Lot {task.lot}</strong> {task.vehicle}<br />{task.blocker}</Link>)}</div>
    </Shell>
  );
}

export function MarketPage() {
  const query = useQuery({ queryKey: ["market"], queryFn: cv.market });
  return <Shell title="Market"><p>{query.data?.priced ?? 0} of {query.data?.lots ?? 0} vans have a conservative floor.</p><div className="mt-4 grid gap-2">{(query.data?.vehicles || []).filter((lot) => lot.market_floor).map((lot) => <VehicleRow key={lot.lot_id} lot={lot} />)}</div></Shell>;
}

export function SourcesPage() {
  const query = useQuery({ queryKey: ["sources"], queryFn: cv.sources });
  const sources = (query.data?.sources || {}) as Record<string, { name?: string; status?: string }>;
  return (
    <Shell title="Sources">
      <div className="grid gap-3 sm:grid-cols-2">
        {Object.entries(sources).map(([key, source]) => (
          <article key={key} className="rounded-xl border border-stone-800 p-4">
            <p>{source.name || key}</p>
            <p className="text-sm text-stone-400">{source.status || "Unknown"}</p>
          </article>
        ))}
      </div>
    </Shell>
  );
}
