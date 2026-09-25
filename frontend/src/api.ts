export type Lot = {
  lot_id: string;
  auction_id: string;
  lot_number: string;
  vehicle: string;
  title: string;
  registration: string;
  year: number | null;
  mileage_km: number | null;
  status: string;
  technical_state: string;
  selected: boolean;
  current_bid_gbp: string | null;
  market_floor: string | null;
  pre_tax_ceiling: string | null;
  final_safe_hammer: string | null;
  headroom_status: string;
  market_confidence: string | null;
  dealer_diversity: string | null;
  provenance: string;
  provenance_plain: string;
  blockers: string[];
  buy_ready: boolean;
  evaluation?: Record<string, unknown>;
  evidence?: { evidence_id: string; kind: string; filename: string }[];
  request_pack?: string;
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  return response.json();
}

export const cv = {
  overview: () => api<{ auctions: Auction[]; counts: Counts; attention: Lot[] }>("/api/cv/v1/overview"),
  auctions: () => api<{ auctions: Auction[] }>("/api/cv/v1/auctions"),
  auction: (id: string) => api<Auction & { vehicles: Lot[] }>(`/api/cv/v1/auctions/${id}`),
  lot: (id: string) => api<Lot>(`/api/cv/v1/lots/${id}`),
  select: (id: string, selected: boolean) => api<Lot>(`/api/cv/v1/lots/${id}/selection`, { method: "POST", body: JSON.stringify({ selected }) }),
  bid: (id: string, bid_gbp: string) => api<Lot>(`/api/cv/v1/lots/${id}/bid`, { method: "POST", body: JSON.stringify({ bid_gbp }) }),
  shortlist: () => api<{ lots: Lot[] }>("/api/cv/v1/shortlist"),
  diligence: () => api<{ tasks: { lot_id: string; lot: string; vehicle: string; blocker: string; pre_tax_ceiling: string | null }[] }>("/api/cv/v1/diligence"),
  sources: () => api<{ sources: unknown }>("/api/cv/v1/sources"),
  market: () => api<{ priced: number; lots: number; vehicles: Lot[] }>("/api/cv/v1/market"),
  refresh: (id: string) => api<{ queued: boolean }>(`/api/cv/v1/auctions/${id}/refresh`, { method: "POST" }),
  importText: (catalogue: string) => api<Auction>("/api/cv/v1/auctions/import", { method: "POST", body: JSON.stringify({ catalogue }) }),
};

export type Auction = {
  auction_id: string;
  sale_code: string;
  title: string;
  source: string;
  currency: string;
  fx: string;
  status: string;
  lots: number;
  priced: number;
  selected: number;
  tax_diligence: number;
  market_insufficient: number;
  hard_reject: number;
  market_ready: number;
};

export type Counts = {
  lots: number;
  priced: number;
  selected: number;
  tax_diligence: number;
  market_insufficient: number;
  hard_reject: number;
  market_ready: number;
};

export function money(value: string | null | undefined, currency = "EUR") {
  if (!value) return "—";
  const amount = Number(value);
  if (Number.isNaN(amount)) return value;
  return new Intl.NumberFormat("en-IE", { style: "currency", currency, maximumFractionDigits: 0 }).format(amount);
}
