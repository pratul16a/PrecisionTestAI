import { useState, useEffect, useRef, useCallback, useMemo } from "react";

// ============================================================
// ICE CLIENT MANAGEMENT PORTAL — Sample Test Harness App
// ============================================================

const CLIENTS = Array.from({ length: 200 }, (_, i) => ({
  sid: String(900000 + i),
  name: [
    "JPMorgan Chase (Default)", "Goldman Sachs Group", "Morgan Stanley Corp",
    "Bank of America NA", "Citigroup Global", "Wells Fargo Securities",
    "Deutsche Bank AG", "Barclays Capital", "UBS Securities LLC",
    "Credit Suisse Intl", "HSBC Holdings PLC", "BNP Paribas SA",
    "Nomura Securities", "Mizuho Financial", "Sumitomo Mitsui Banking",
    "RBC Capital Markets", "TD Securities Inc", "Macquarie Group Ltd",
    "Societe Generale SA", "Standard Chartered",
  ][i % 20],
  status: ["Active", "Pending Review", "Suspended", "Under Investigation", "Active"][i % 5],
  region: ["AMER", "EMEA", "APAC", "LATAM"][i % 4],
  riskRating: ["Low", "Medium", "High", "Critical"][i % 4],
  aum: (Math.random() * 500 + 10).toFixed(1) + "M",
  lastReview: `2026-0${(i % 9) + 1}-${String((i % 28) + 1).padStart(2, "0")}`,
  analyst: ["R. Sharma", "J. Chen", "M. Williams", "A. Patel", "S. Kim"][i % 5],
  docCount: Math.floor(Math.random() * 15),
  feedbackCount: Math.floor(Math.random() * 5),
  tradeCount: Math.floor(Math.random() * 50 + 5),
}));

const FEEDBACK_DATA = [
  { id: "FB-001", date: "2026-03-15", type: "Complaint", subject: "Settlement delay on FX trade", priority: "High", status: "Open", assignee: "R. Sharma" },
  { id: "FB-002", date: "2026-03-02", type: "Inquiry", subject: "Account statement discrepancy", priority: "Medium", status: "Resolved", assignee: "J. Chen" },
  { id: "FB-003", date: "2026-02-18", type: "Complaint", subject: "Unauthorized margin call", priority: "Critical", status: "Escalated", assignee: "M. Williams" },
];

const DOCUMENTS = [
  { id: "DOC-2201", name: "KYC Verification Form", type: "PDF", uploaded: "2026-03-20", size: "2.4 MB", status: "Verified" },
  { id: "DOC-2202", name: "Annual Risk Assessment", type: "XLSX", uploaded: "2026-03-18", size: "890 KB", status: "Pending Review" },
  { id: "DOC-2203", name: "Trade Authorization Letter", type: "PDF", uploaded: "2026-03-10", size: "156 KB", status: "Verified" },
  { id: "DOC-2204", name: "Compliance Attestation Q1", type: "DOCX", uploaded: "2026-02-28", size: "340 KB", status: "Expired" },
];

const TRADES = Array.from({ length: 80 }, (_, i) => ({
  tradeId: `TRD-${String(100000 + i)}`,
  date: `2026-0${(i % 3) + 1}-${String((i % 28) + 1).padStart(2, "0")}`,
  instrument: ["FX Forward", "IR Swap", "Credit Default Swap", "Equity Option", "Bond Future", "FX Spot"][i % 6],
  notional: `$${(Math.random() * 100 + 1).toFixed(1)}M`,
  counterparty: CLIENTS[i % 20].name,
  status: ["Confirmed", "Pending", "Settled", "Failed", "Cancelled"][i % 5],
  book: ["NY-FX-01", "LDN-IR-03", "TKY-CR-02", "HK-EQ-01"][i % 4],
}));

const CLS = {
  wrapper: "sc-bczRLJ dJHfKj",
  inner: "sc-gsnTZi fUOAEq",
  cellVal: "ag-cell-value",
  cellWrap: "ag-cell ag-cell-not-inline-editing ag-cell-auto-height",
  row: "ag-row ag-row-no-focus ag-row-level-0",
  rowOdd: "ag-row ag-row-odd ag-row-no-focus ag-row-level-0",
  headerCell: "ag-header-cell ag-header-cell-sortable",
  gridRoot: "ag-root-wrapper ag-layout-normal",
  gridBody: "ag-body-viewport ag-layout-normal",
  sideNav: "css-1x7q8p",
  navItem: "css-9kq3wm",
  navActive: "css-9kq3wm css-active-2j8f",
  tabBar: "css-htk29s",
  tabItem: "css-p3r9fq",
  tabActive: "css-p3r9fq css-sel-8dk2",
  contentPanel: "css-mz84us",
  searchWrap: "css-fj39dk",
  badge: "css-bq72ls",
  cardWrap: "css-kw9c3e",
  modalOverlay: "css-overlay-x8dk2",
  modalContent: "css-modal-fj29s",
  formField: "css-field-2k9sl",
  btnPrimary: "css-btn-3kd92",
  btnSecondary: "css-btn-7js3k",
  statusDot: "css-dot-9kd2s",
  filterBar: "css-filter-2jk9",
  dropdownWrap: "css-dd-8sk29",
  dropdownList: "css-dd-list-3jk2",
  dropdownItem: "css-dd-item-9dk3",
};

function ShadowStatusBadge({ status }) {
  const ref = useRef(null);
  const shadowRef = useRef(null);
  useEffect(() => {
    if (ref.current && !shadowRef.current) {
      shadowRef.current = ref.current.attachShadow({ mode: "open" });
    }
    if (shadowRef.current) {
      const colors = {
        Active: "#16a34a", "Pending Review": "#d97706", Suspended: "#dc2626",
        "Under Investigation": "#9333ea", Verified: "#16a34a", "Pending": "#d97706",
        Open: "#dc2626", Resolved: "#16a34a", Escalated: "#9333ea",
        Confirmed: "#16a34a", Settled: "#3b82f6", Failed: "#dc2626",
        Cancelled: "#6b7280", Expired: "#dc2626", Low: "#16a34a",
        Medium: "#d97706", High: "#dc2626", Critical: "#9333ea",
      };
      const c = colors[status] || "#6b7280";
      shadowRef.current.innerHTML = `
        <style>
          .badge-wrap { display:inline-flex; align-items:center; gap:5px; padding:2px 8px; border-radius:4px; background:${c}15; border:1px solid ${c}30; }
          .dot { width:6px; height:6px; border-radius:50%; background:${c}; }
          .label { font-size:11px; color:${c}; font-weight:600; font-family:monospace; letter-spacing:0.02em; }
        </style>
        <div class="badge-wrap"><span class="dot"></span><span class="label">${status}</span></div>
      `;
    }
  }, [status]);
  return <div ref={ref} className={CLS.badge}></div>;
}

function ShadowDateDisplay({ date }) {
  const ref = useRef(null);
  const shadowRef = useRef(null);
  useEffect(() => {
    if (ref.current && !shadowRef.current) {
      shadowRef.current = ref.current.attachShadow({ mode: "open" });
    }
    if (shadowRef.current) {
      const d = new Date(date);
      const formatted = d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
      const daysAgo = Math.floor((Date.now() - d.getTime()) / 86400000);
      shadowRef.current.innerHTML = `
        <style>
          .date-wrap { display:flex; flex-direction:column; }
          .date-main { font-size:12px; color:#c8d6e5; font-family:monospace; }
          .date-ago { font-size:9px; color:#636e72; margin-top:1px; }
        </style>
        <div class="date-wrap"><span class="date-main">${formatted}</span><span class="date-ago">${daysAgo}d ago</span></div>
      `;
    }
  }, [date]);
  return <div ref={ref}></div>;
}

function ShadowPriority({ level }) {
  const ref = useRef(null);
  const shadowRef = useRef(null);
  useEffect(() => {
    if (ref.current && !shadowRef.current) {
      shadowRef.current = ref.current.attachShadow({ mode: "open" });
    }
    if (shadowRef.current) {
      const bars = { Low: 1, Medium: 2, High: 3, Critical: 4 };
      const colors = { Low: "#16a34a", Medium: "#d97706", High: "#dc2626", Critical: "#9333ea" };
      const n = bars[level] || 1;
      const c = colors[level] || "#6b7280";
      let barsHtml = "";
      for (let i = 0; i < 4; i++) {
        barsHtml += `<div class="bar" style="height:${8 + i * 3}px; background:${i < n ? c : '#2d3436'}"></div>`;
      }
      shadowRef.current.innerHTML = `
        <style>
          .priority-wrap { display:flex; align-items:flex-end; gap:2px; }
          .bar { width:4px; border-radius:1px; transition:background 0.2s; }
          .label { font-size:10px; color:${c}; margin-left:5px; font-weight:600; }
        </style>
        <div class="priority-wrap">${barsHtml}<span class="label">${level}</span></div>
      `;
    }
  }, [level]);
  return <div ref={ref}></div>;
}

function ShadowDropdown({ options, value, onChange, placeholder }) {
  const ref = useRef(null);
  const shadowRef = useRef(null);
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    if (ref.current && !shadowRef.current) {
      shadowRef.current = ref.current.attachShadow({ mode: "open" });
      const container = document.createElement("div");
      container.className = "dropdown-host";
      shadowRef.current.appendChild(document.createElement("style"));
      shadowRef.current.appendChild(container);
    }
    if (shadowRef.current) {
      const styleEl = shadowRef.current.querySelector("style");
      styleEl.textContent = `
        .dropdown-host { position:relative; font-family:monospace; }
        .trigger { display:flex; align-items:center; justify-content:space-between; padding:6px 10px; background:#1a1e2e; border:1px solid #2d3436; border-radius:4px; color:#dfe6e9; font-size:12px; cursor:pointer; min-width:140px; }
        .trigger:hover { border-color:#4a69bd; }
        .arrow { font-size:8px; color:#636e72; }
        .options { position:absolute; top:100%; left:0; right:0; background:#1a1e2e; border:1px solid #2d3436; border-radius:0 0 4px 4px; z-index:100; display:${isOpen ? "block" : "none"}; max-height:160px; overflow-y:auto; }
        .option { padding:6px 10px; color:#b2bec3; font-size:11px; cursor:pointer; }
        .option:hover { background:#2d3436; color:#dfe6e9; }
        .option.selected { color:#4a69bd; font-weight:bold; }
      `;
      const container = shadowRef.current.querySelector(".dropdown-host");
      container.innerHTML = `
        <div class="trigger">${value || placeholder || "Select..."}<span class="arrow">▼</span></div>
        <div class="options">${options.map(o => `<div class="option ${o === value ? "selected" : ""}" data-val="${o}">${o}</div>`).join("")}</div>
      `;
      container.querySelector(".trigger").onclick = () => setIsOpen(!isOpen);
      container.querySelectorAll(".option").forEach(el => {
        el.onclick = () => { onChange(el.dataset.val); setIsOpen(false); };
      });
    }
  }, [isOpen, value, options, onChange, placeholder]);

  return <div ref={ref} className={CLS.dropdownWrap}></div>;
}

function VirtualGrid({ data, columns, rowHeight = 32, onRowClick, selectedId }) {
  const containerRef = useRef(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [containerHeight, setContainerHeight] = useState(400);

  useEffect(() => {
    if (containerRef.current) setContainerHeight(containerRef.current.clientHeight);
  }, []);

  const handleScroll = useCallback((e) => setScrollTop(e.target.scrollTop), []);

  const totalHeight = data.length * rowHeight;
  const startIdx = Math.floor(scrollTop / rowHeight);
  const visibleCount = Math.ceil(containerHeight / rowHeight) + 2;
  const endIdx = Math.min(startIdx + visibleCount, data.length);
  const visibleData = data.slice(startIdx, endIdx);
  const offsetY = startIdx * rowHeight;

  return (
    <div className={CLS.gridRoot}>
      <div className="ag-header ag-header-row" style={{ display: "flex", borderBottom: "1px solid #2d3436", background: "#141821" }}>
        {columns.map((col, ci) => (
          <div key={ci} className={CLS.headerCell} style={{
            width: col.width || 120, padding: "8px 10px", fontSize: "11px",
            color: "#636e72", fontWeight: 700, textTransform: "uppercase",
            letterSpacing: "0.05em", fontFamily: "monospace", flexShrink: 0,
            borderRight: "1px solid #1a1e2e", cursor: "pointer", userSelect: "none",
          }}>
            <div className="ag-header-cell-label"><span className="ag-header-cell-text">{col.header}</span></div>
          </div>
        ))}
      </div>
      <div ref={containerRef} className={CLS.gridBody} onScroll={handleScroll}
        style={{ height: 380, overflowY: "auto", position: "relative" }}>
        <div style={{ height: totalHeight, position: "relative" }}>
          <div style={{ position: "absolute", top: offsetY, left: 0, right: 0 }}>
            {visibleData.map((row, ri) => {
              const actualIdx = startIdx + ri;
              const isSelected = selectedId && row[columns[0]?.field] === selectedId;
              return (
                <div key={actualIdx}
                  className={actualIdx % 2 === 0 ? CLS.row : CLS.rowOdd}
                  data-row-index={actualIdx}
                  onClick={() => onRowClick && onRowClick(row)}
                  style={{
                    display: "flex", height: rowHeight, alignItems: "center",
                    cursor: onRowClick ? "pointer" : "default",
                    background: isSelected ? "#1a2744" : actualIdx % 2 === 0 ? "#0f1219" : "#111622",
                    borderBottom: "1px solid #1a1e2e",
                  }}>
                  {columns.map((col, ci) => (
                    <div key={ci} className={CLS.cellWrap} style={{
                      width: col.width || 120, padding: "0 10px", flexShrink: 0,
                      borderRight: "1px solid #0d1017",
                    }}>
                      <div className={CLS.cellVal}>
                        {col.renderer ? col.renderer(row[col.field], row) : (
                          <span style={{ fontSize: "12px", color: "#b2bec3", fontFamily: "monospace" }}>
                            {row[col.field]}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 10px",
        background: "#141821", borderTop: "1px solid #2d3436", fontSize: "11px", color: "#636e72" }}>
        <span>Rows: {data.length}</span>
        <span>Showing {startIdx + 1}-{endIdx} of {data.length}</span>
      </div>
    </div>
  );
}

export default function ICEPortal() {
  const [page, setPage] = useState("dashboard");
  const [searchTerm, setSearchTerm] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [hasSearched, setHasSearched] = useState(false);
  const [selectedClient, setSelectedClient] = useState(null);
  const [activeTab, setActiveTab] = useState("overview");
  const [regionFilter, setRegionFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [modalType, setModalType] = useState("");
  const [tradeSearch, setTradeSearch] = useState("");
  const [complianceTab, setComplianceTab] = useState("reports");

  const handleSearch = () => {
    if (!searchTerm.trim()) return;
    const results = CLIENTS.filter(c =>
      c.sid.includes(searchTerm) ||
      c.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      c.analyst.toLowerCase().includes(searchTerm.toLowerCase())
    );
    setSearchResults(results);
    setHasSearched(true);
    setSelectedClient(null);
  };

  const filteredTrades = useMemo(() => {
    if (!tradeSearch) return TRADES;
    return TRADES.filter(t =>
      t.tradeId.includes(tradeSearch) ||
      t.instrument.toLowerCase().includes(tradeSearch.toLowerCase()) ||
      t.counterparty.toLowerCase().includes(tradeSearch.toLowerCase())
    );
  }, [tradeSearch]);

  const clientColumns = [
    { field: "sid", header: "SID", width: 80 },
    { field: "name", header: "Client Name", width: 200,
      renderer: (val) => <span style={{ color: "#dfe6e9", fontWeight: 500, fontFamily: "monospace", fontSize: 12 }}>{val}</span> },
    { field: "status", header: "Status", width: 130, renderer: (val) => <ShadowStatusBadge status={val} /> },
    { field: "region", header: "Region", width: 70 },
    { field: "riskRating", header: "Risk", width: 100, renderer: (val) => <ShadowPriority level={val} /> },
    { field: "aum", header: "AUM", width: 80 },
    { field: "lastReview", header: "Last Review", width: 120, renderer: (val) => <ShadowDateDisplay date={val} /> },
    { field: "analyst", header: "Analyst", width: 100 },
  ];

  const tradeColumns = [
    { field: "tradeId", header: "Trade ID", width: 110 },
    { field: "date", header: "Date", width: 110, renderer: (val) => <ShadowDateDisplay date={val} /> },
    { field: "instrument", header: "Instrument", width: 150 },
    { field: "notional", header: "Notional", width: 100,
      renderer: (val) => <span style={{ color: "#4a69bd", fontSize: 12, fontFamily: "monospace", fontWeight: 600 }}>{val}</span> },
    { field: "counterparty", header: "Counterparty", width: 180 },
    { field: "status", header: "Status", width: 120, renderer: (val) => <ShadowStatusBadge status={val} /> },
    { field: "book", header: "Book", width: 100 },
  ];

  const renderDashboard = () => (
    <div className={CLS.contentPanel}>
      <div className={CLS.inner}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 20, fontWeight: 700, color: "#dfe6e9", fontFamily: "'DM Mono', monospace" }}>Dashboard</div>
            <div style={{ fontSize: 11, color: "#636e72", marginTop: 2 }}>ICE Client Management — Overview</div>
          </div>
          <div style={{ fontSize: 11, color: "#636e72", fontFamily: "monospace" }}>Last Updated: {new Date().toLocaleString()}</div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 24 }}>
          {[
            { label: "Total Clients", value: "1,247", change: "+12", color: "#4a69bd" },
            { label: "Pending Reviews", value: "38", change: "+5", color: "#d97706" },
            { label: "Active Investigations", value: "7", change: "-2", color: "#dc2626" },
            { label: "Documents Due", value: "23", change: "+8", color: "#9333ea" },
          ].map((card, i) => (
            <div key={i} className={CLS.cardWrap} style={{ background: "#141821", borderRadius: 6, padding: 16, border: "1px solid #1a1e2e" }}>
              <div className={CLS.wrapper}><div className={CLS.inner}>
                <div style={{ fontSize: 11, color: "#636e72", textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>{card.label}</div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 8 }}>
                  <span style={{ fontSize: 28, fontWeight: 700, color: card.color, fontFamily: "'DM Mono', monospace" }}>{card.value}</span>
                  <span style={{ fontSize: 11, color: card.change.startsWith("+") ? "#16a34a" : "#dc2626", fontWeight: 600 }}>{card.change}</span>
                </div>
              </div></div>
            </div>
          ))}
        </div>
        <div style={{ background: "#141821", borderRadius: 6, border: "1px solid #1a1e2e", padding: 16 }}>
          <div className={CLS.wrapper}><div className={CLS.inner}>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#dfe6e9", marginBottom: 12 }}>Recent Activity</div>
            {[
              { action: "KYC Review completed", client: "Goldman Sachs Group", time: "2 min ago", type: "review" },
              { action: "New document uploaded", client: "Deutsche Bank AG", time: "15 min ago", type: "upload" },
              { action: "Risk rating changed to High", client: "Credit Suisse Intl", time: "1 hour ago", type: "risk" },
              { action: "Trade settlement failed", client: "Barclays Capital", time: "2 hours ago", type: "trade" },
              { action: "Compliance attestation expired", client: "Nomura Securities", time: "3 hours ago", type: "compliance" },
            ].map((item, i) => (
              <div key={i} className={CLS.wrapper} style={{ display: "flex", alignItems: "center", padding: "10px 0", borderBottom: i < 4 ? "1px solid #1a1e2e" : "none", gap: 12 }}>
                <div className={CLS.statusDot} style={{ width: 8, height: 8, borderRadius: "50%",
                  background: { review: "#16a34a", upload: "#3b82f6", risk: "#dc2626", trade: "#d97706", compliance: "#9333ea" }[item.type] }}></div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 12, color: "#dfe6e9" }}>{item.action}</div>
                  <div style={{ fontSize: 11, color: "#636e72" }}>{item.client}</div>
                </div>
                <div style={{ fontSize: 10, color: "#636e72", fontFamily: "monospace" }}>{item.time}</div>
              </div>
            ))}
          </div></div>
        </div>
      </div>
    </div>
  );

  const renderClientSearch = () => (
    <div className={CLS.contentPanel}>
      <div style={{ fontSize: 20, fontWeight: 700, color: "#dfe6e9", marginBottom: 16, fontFamily: "'DM Mono', monospace" }}>Client Search</div>
      <div className={CLS.searchWrap} style={{ display: "flex", gap: 8, marginBottom: 16, alignItems: "center" }}>
        <div className={CLS.formField} style={{ flex: 1 }}>
          <input type="text" value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSearch()}
            placeholder="Enter Client SID, Name, or Analyst..."
            style={{ width: "100%", padding: "8px 12px", background: "#1a1e2e", border: "1px solid #2d3436",
              borderRadius: 4, color: "#dfe6e9", fontSize: 13, fontFamily: "monospace", outline: "none" }} />
        </div>
        <button className={CLS.btnPrimary} onClick={handleSearch}
          style={{ padding: "8px 20px", background: "#4a69bd", border: "none", borderRadius: 4,
            color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "monospace" }}>Search</button>
      </div>
      <div className={CLS.filterBar} style={{ display: "flex", gap: 12, marginBottom: 16, alignItems: "center" }}>
        <span style={{ fontSize: 11, color: "#636e72", marginRight: 6 }}>Region:</span>
        <ShadowDropdown options={["", "AMER", "EMEA", "APAC", "LATAM"]} value={regionFilter} onChange={setRegionFilter} placeholder="All Regions" />
        <span style={{ fontSize: 11, color: "#636e72", marginRight: 6 }}>Status:</span>
        <ShadowDropdown options={["", "Active", "Pending Review", "Suspended", "Under Investigation"]}
          value={statusFilter} onChange={setStatusFilter} placeholder="All Statuses" />
        <div style={{ flex: 1 }}></div>
        <div style={{ fontSize: 11, color: "#636e72" }}>
          {hasSearched ? `${searchResults.length} results found` : "Enter search criteria above"}
        </div>
      </div>
      {hasSearched && (
        <VirtualGrid
          data={searchResults.filter(c => (!regionFilter || c.region === regionFilter) && (!statusFilter || c.status === statusFilter))}
          columns={clientColumns}
          onRowClick={(row) => { setSelectedClient(row); setPage("clientDetail"); setActiveTab("overview"); }}
          selectedId={selectedClient?.sid}
        />
      )}
      {!hasSearched && (
        <div style={{ textAlign: "center", padding: 60, color: "#636e72", fontSize: 13 }}>
          Enter a Client SID, Name, or Analyst to search
        </div>
      )}
    </div>
  );

  const renderClientDetail = () => {
    if (!selectedClient) return <div style={{ padding: 40, color: "#636e72" }}>No client selected. Go to Client Search first.</div>;
    const c = selectedClient;
    const tabs = [
      { id: "overview", label: "Overview" },
      { id: "feedback", label: "Client Feedback" },
      { id: "documents", label: "Documents" },
      { id: "trades", label: "Trades" },
      { id: "kyc", label: "KYC Status" },
    ];
    return (
      <div className={CLS.contentPanel}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 11, color: "#636e72", textTransform: "uppercase", letterSpacing: "0.05em" }}>Client Detail</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: "#dfe6e9", fontFamily: "'DM Mono', monospace", marginTop: 4 }}>{c.name}</div>
            <div style={{ display: "flex", gap: 16, marginTop: 6, fontSize: 12, color: "#636e72" }}>
              <span>SID: <span style={{ color: "#4a69bd", fontWeight: 600 }}>{c.sid}</span></span>
              <span>Region: {c.region}</span>
              <span>Analyst: {c.analyst}</span>
            </div>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <ShadowStatusBadge status={c.status} />
            <ShadowPriority level={c.riskRating} />
          </div>
        </div>
        <div className={CLS.tabBar} style={{ display: "flex", gap: 0, borderBottom: "1px solid #2d3436", marginBottom: 20 }}>
          {tabs.map(tab => (
            <div key={tab.id} className={activeTab === tab.id ? CLS.tabActive : CLS.tabItem}
              onClick={() => setActiveTab(tab.id)}
              style={{ padding: "10px 20px", fontSize: 12, fontWeight: activeTab === tab.id ? 700 : 400,
                color: activeTab === tab.id ? "#4a69bd" : "#636e72",
                borderBottom: activeTab === tab.id ? "2px solid #4a69bd" : "2px solid transparent",
                cursor: "pointer", fontFamily: "monospace" }}>{tab.label}</div>
          ))}
        </div>
        <div>
          {activeTab === "overview" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <div style={{ background: "#141821", borderRadius: 6, padding: 16, border: "1px solid #1a1e2e" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#dfe6e9", marginBottom: 12 }}>Client Information</div>
                {[["Client Name", c.name], ["SID", c.sid], ["Status", c.status], ["Region", c.region],
                  ["Risk Rating", c.riskRating], ["AUM", c.aum], ["Assigned Analyst", c.analyst]].map(([label, val], i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid #1a1e2e", fontSize: 12 }}>
                    <span style={{ color: "#636e72" }}>{label}</span>
                    <span style={{ color: "#dfe6e9", fontFamily: "monospace" }}>{val}</span>
                  </div>
                ))}
              </div>
              <div style={{ background: "#141821", borderRadius: 6, padding: 16, border: "1px solid #1a1e2e" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#dfe6e9", marginBottom: 12 }}>Activity Summary</div>
                {[["Documents", c.docCount], ["Feedback Items", c.feedbackCount],
                  ["Trades (30d)", c.tradeCount], ["Last Review", c.lastReview]].map(([label, val], i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "6px 0", borderBottom: "1px solid #1a1e2e", fontSize: 12 }}>
                    <span style={{ color: "#636e72" }}>{label}</span>
                    <span style={{ color: "#4a69bd", fontWeight: 600, fontFamily: "monospace" }}>{val}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {activeTab === "feedback" && (
            <div>
              {c.feedbackCount === 0 ? (
                <div style={{ textAlign: "center", padding: 40, color: "#636e72" }}>
                  <div style={{ fontSize: 16, marginBottom: 8 }}>No Client Feedback</div>
                  <div style={{ fontSize: 12 }}>No feedback records found for this client</div>
                </div>
              ) : (
                <div>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "#dfe6e9" }}>Feedback Records ({FEEDBACK_DATA.length})</div>
                    <button className={CLS.btnPrimary} onClick={() => { setModalType("feedback"); setShowModal(true); }}
                      style={{ padding: "5px 14px", background: "#4a69bd", border: "none", borderRadius: 4,
                        color: "#fff", fontSize: 11, cursor: "pointer", fontFamily: "monospace" }}>+ New Feedback</button>
                  </div>
                  {FEEDBACK_DATA.map((fb, i) => (
                    <div key={i} className={CLS.cardWrap} style={{ background: "#141821", borderRadius: 6, padding: 14, marginBottom: 8, border: "1px solid #1a1e2e" }}>
                      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 4 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: "#dfe6e9", fontFamily: "monospace" }}>{fb.id}</span>
                        <ShadowStatusBadge status={fb.status} />
                        <ShadowPriority level={fb.priority} />
                      </div>
                      <div style={{ fontSize: 13, color: "#b2bec3", marginBottom: 4 }}>{fb.subject}</div>
                      <div style={{ fontSize: 11, color: "#636e72" }}>Type: {fb.type} | Assignee: {fb.assignee} | Date: {fb.date}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
          {activeTab === "documents" && (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
                <div style={{ fontSize: 13, fontWeight: 600, color: "#dfe6e9" }}>Documents ({DOCUMENTS.length})</div>
                <button className={CLS.btnPrimary} onClick={() => { setModalType("upload"); setShowModal(true); }}
                  style={{ padding: "5px 14px", background: "#4a69bd", border: "none", borderRadius: 4,
                    color: "#fff", fontSize: 11, cursor: "pointer", fontFamily: "monospace" }}>Upload Document</button>
              </div>
              <div style={{ background: "#141821", borderRadius: 6, border: "1px solid #1a1e2e", overflow: "hidden" }}>
                <div style={{ display: "flex", background: "#0f1219", padding: "8px 12px", borderBottom: "1px solid #1a1e2e" }}>
                  {["ID", "Document Name", "Type", "Uploaded", "Size", "Status"].map((h, i) => (
                    <div key={i} style={{ flex: i === 1 ? 2 : 1, fontSize: 11, color: "#636e72", fontWeight: 700, textTransform: "uppercase", fontFamily: "monospace" }}>{h}</div>
                  ))}
                </div>
                {DOCUMENTS.map((doc, i) => (
                  <div key={i} style={{ display: "flex", padding: "10px 12px", borderBottom: "1px solid #1a1e2e", alignItems: "center" }}>
                    <div style={{ flex: 1, fontSize: 12, color: "#4a69bd", fontFamily: "monospace" }}>{doc.id}</div>
                    <div style={{ flex: 2, fontSize: 12, color: "#dfe6e9" }}>{doc.name}</div>
                    <div style={{ flex: 1, fontSize: 11, color: "#636e72" }}>{doc.type}</div>
                    <div style={{ flex: 1 }}><ShadowDateDisplay date={doc.uploaded} /></div>
                    <div style={{ flex: 1, fontSize: 11, color: "#636e72", fontFamily: "monospace" }}>{doc.size}</div>
                    <div style={{ flex: 1 }}><ShadowStatusBadge status={doc.status} /></div>
                  </div>
                ))}
              </div>
            </div>
          )}
          {activeTab === "trades" && (
            <div>
              <div style={{ display: "flex", gap: 8, marginBottom: 12, alignItems: "center" }}>
                <input type="text" value={tradeSearch} onChange={e => setTradeSearch(e.target.value)}
                  placeholder="Filter trades by ID, instrument, counterparty..."
                  style={{ flex: 1, padding: "6px 10px", background: "#1a1e2e", border: "1px solid #2d3436",
                    borderRadius: 4, color: "#dfe6e9", fontSize: 12, fontFamily: "monospace", outline: "none" }} />
                <span style={{ fontSize: 11, color: "#636e72" }}>{filteredTrades.length} trades</span>
              </div>
              <VirtualGrid data={filteredTrades} columns={tradeColumns} rowHeight={34} />
            </div>
          )}
          {activeTab === "kyc" && (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <div style={{ background: "#141821", borderRadius: 6, padding: 16, border: "1px solid #1a1e2e" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#dfe6e9", marginBottom: 12 }}>KYC Verification Status</div>
                {[["Identity Verification", "Completed"], ["Address Verification", "Completed"],
                  ["Source of Funds", "Pending"], ["PEP Screening", "Completed"],
                  ["Sanctions Check", "Completed"], ["Enhanced Due Diligence", "Required"]].map(([item, stat], i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid #1a1e2e" }}>
                    <span style={{ fontSize: 12, color: "#b2bec3" }}>{item}</span>
                    <ShadowStatusBadge status={stat} />
                  </div>
                ))}
              </div>
              <div style={{ background: "#141821", borderRadius: 6, padding: 16, border: "1px solid #1a1e2e" }}>
                <div style={{ fontSize: 13, fontWeight: 700, color: "#dfe6e9", marginBottom: 12 }}>Risk Assessment</div>
                <div style={{ fontSize: 11, color: "#636e72", marginBottom: 4 }}>Overall Risk Score</div>
                <div style={{ fontSize: 36, fontWeight: 700, color: "#d97706", fontFamily: "'DM Mono', monospace" }}>67</div>
                <div style={{ fontSize: 11, color: "#636e72", marginTop: 2 }}>Medium Risk - Requires periodic review</div>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderCompliance = () => (
    <div className={CLS.contentPanel}>
      <div style={{ fontSize: 20, fontWeight: 700, color: "#dfe6e9", marginBottom: 16, fontFamily: "'DM Mono', monospace" }}>Compliance</div>
      <div className={CLS.tabBar} style={{ display: "flex", gap: 0, borderBottom: "1px solid #2d3436", marginBottom: 20 }}>
        {[{ id: "reports", label: "Reports" }, { id: "attestations", label: "Attestations" }, { id: "embedded", label: "Regulatory Feed" }].map(tab => (
          <div key={tab.id} className={complianceTab === tab.id ? CLS.tabActive : CLS.tabItem}
            onClick={() => setComplianceTab(tab.id)}
            style={{ padding: "10px 20px", fontSize: 12, cursor: "pointer", fontFamily: "monospace",
              fontWeight: complianceTab === tab.id ? 700 : 400,
              color: complianceTab === tab.id ? "#4a69bd" : "#636e72",
              borderBottom: complianceTab === tab.id ? "2px solid #4a69bd" : "2px solid transparent" }}>{tab.label}</div>
        ))}
      </div>
      {complianceTab === "reports" && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
          {[
            { title: "Q1 2026 Compliance Summary", date: "2026-03-31", status: "Published" },
            { title: "SAR Filing Report - March", date: "2026-03-28", status: "Under Review" },
            { title: "AML Transaction Monitoring", date: "2026-03-25", status: "Published" },
            { title: "FATCA Reporting Status", date: "2026-03-20", status: "Draft" },
            { title: "Sanctions Screening Log", date: "2026-03-15", status: "Published" },
            { title: "Risk Appetite Framework", date: "2026-03-10", status: "Expired" },
          ].map((report, i) => (
            <div key={i} className={CLS.cardWrap} style={{ background: "#141821", borderRadius: 6, padding: 14, border: "1px solid #1a1e2e", cursor: "pointer" }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#dfe6e9", marginBottom: 6 }}>{report.title}</div>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <ShadowDateDisplay date={report.date} />
                <ShadowStatusBadge status={report.status} />
              </div>
            </div>
          ))}
        </div>
      )}
      {complianceTab === "attestations" && (
        <div style={{ background: "#141821", borderRadius: 6, padding: 16, border: "1px solid #1a1e2e" }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "#dfe6e9", marginBottom: 12 }}>Pending Attestations</div>
          {[
            { item: "Annual AML Training Completion", due: "2026-04-15", assignee: "All Staff" },
            { item: "Code of Conduct Acknowledgment", due: "2026-04-30", assignee: "All Staff" },
            { item: "Conflict of Interest Disclosure", due: "2026-05-01", assignee: "Senior Officers" },
          ].map((att, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "10px 0", borderBottom: "1px solid #1a1e2e", alignItems: "center" }}>
              <div>
                <div style={{ fontSize: 12, color: "#dfe6e9" }}>{att.item}</div>
                <div style={{ fontSize: 11, color: "#636e72" }}>Assignee: {att.assignee}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 11, color: "#d97706", fontFamily: "monospace" }}>Due: {att.due}</div>
                <button className={CLS.btnSecondary} style={{ padding: "3px 10px", background: "transparent", border: "1px solid #4a69bd",
                  borderRadius: 3, color: "#4a69bd", fontSize: 10, cursor: "pointer", fontFamily: "monospace", marginTop: 4 }}>Complete</button>
              </div>
            </div>
          ))}
        </div>
      )}
      {complianceTab === "embedded" && (
        <div style={{ background: "#141821", borderRadius: 6, border: "1px solid #1a1e2e", overflow: "hidden" }}>
          <div style={{ padding: "10px 14px", borderBottom: "1px solid #1a1e2e", fontSize: 12, color: "#636e72" }}>Embedded Regulatory Feed (iframe)</div>
          <iframe src="https://www.ecb.europa.eu/home/html/index.en.html" title="Regulatory Feed"
            style={{ width: "100%", height: 450, border: "none", background: "#0a0e17" }}
            sandbox="allow-scripts allow-same-origin" />
        </div>
      )}
    </div>
  );

  const renderTrades = () => (
    <div className={CLS.contentPanel}>
      <div style={{ fontSize: 20, fontWeight: 700, color: "#dfe6e9", marginBottom: 16, fontFamily: "'DM Mono', monospace" }}>Trade Blotter</div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16, alignItems: "center" }}>
        <input type="text" value={tradeSearch} onChange={e => setTradeSearch(e.target.value)}
          placeholder="Search trades..."
          style={{ flex: 1, padding: "8px 12px", background: "#1a1e2e", border: "1px solid #2d3436",
            borderRadius: 4, color: "#dfe6e9", fontSize: 13, fontFamily: "monospace", outline: "none" }} />
        <ShadowDropdown options={["", "FX Forward", "IR Swap", "Credit Default Swap", "Equity Option"]} value="" onChange={() => {}} placeholder="Instrument" />
        <ShadowDropdown options={["", "Confirmed", "Pending", "Settled", "Failed"]} value="" onChange={() => {}} placeholder="Status" />
      </div>
      <VirtualGrid data={filteredTrades} columns={tradeColumns} rowHeight={34} />
    </div>
  );

  const renderModal = () => {
    if (!showModal) return null;
    return (
      <div className={CLS.modalOverlay} onClick={() => setShowModal(false)}
        style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }}>
        <div className={CLS.modalContent} onClick={e => e.stopPropagation()}
          style={{ background: "#141821", borderRadius: 8, padding: 24, width: 480, border: "1px solid #2d3436" }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: "#dfe6e9", marginBottom: 16 }}>
            {modalType === "upload" ? "Upload Document" : "New Feedback"}
          </div>
          <input type="text" placeholder={modalType === "upload" ? "Document title..." : "Subject..."}
            style={{ width: "100%", padding: "8px 12px", background: "#1a1e2e", border: "1px solid #2d3436",
              borderRadius: 4, color: "#dfe6e9", fontSize: 12, fontFamily: "monospace", outline: "none", marginBottom: 12 }} />
          {modalType === "feedback" && (
            <>
              <div style={{ marginBottom: 12 }}>
                <ShadowDropdown options={["Complaint", "Inquiry", "Suggestion", "Escalation"]} value="" onChange={() => {}} placeholder="Select type..." />
              </div>
              <div style={{ marginBottom: 12 }}>
                <ShadowDropdown options={["Low", "Medium", "High", "Critical"]} value="" onChange={() => {}} placeholder="Priority..." />
              </div>
              <textarea placeholder="Description..."
                style={{ width: "100%", height: 80, padding: "8px 12px", background: "#1a1e2e", border: "1px solid #2d3436",
                  borderRadius: 4, color: "#dfe6e9", fontSize: 12, fontFamily: "monospace", outline: "none", resize: "vertical", marginBottom: 12 }} />
            </>
          )}
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
            <button className={CLS.btnSecondary} onClick={() => setShowModal(false)}
              style={{ padding: "8px 16px", background: "transparent", border: "1px solid #2d3436", borderRadius: 4, color: "#636e72", fontSize: 12, cursor: "pointer", fontFamily: "monospace" }}>Cancel</button>
            <button className={CLS.btnPrimary} onClick={() => setShowModal(false)}
              style={{ padding: "8px 16px", background: "#4a69bd", border: "none", borderRadius: 4, color: "#fff", fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "monospace" }}>Submit</button>
          </div>
        </div>
      </div>
    );
  };

  const navItems = [
    { id: "dashboard", label: "Dashboard" },
    { id: "clients", label: "Clients" },
    { id: "clientDetail", label: "Client Detail", hidden: !selectedClient },
    { id: "trades", label: "Trade Blotter" },
    { id: "compliance", label: "Compliance" },
  ];

  return (
    <div style={{ display: "flex", height: "100vh", background: "#0a0e17", color: "#dfe6e9", fontFamily: "'DM Mono', 'IBM Plex Mono', monospace" }}>
      <div className={CLS.sideNav} style={{ width: 220, background: "#0f1219", borderRight: "1px solid #1a1e2e", display: "flex", flexDirection: "column" }}>
        <div style={{ padding: "16px 14px", borderBottom: "1px solid #1a1e2e" }}>
          <div style={{ fontSize: 15, fontWeight: 800, color: "#4a69bd", letterSpacing: "0.08em" }}>ICE</div>
          <div style={{ fontSize: 9, color: "#636e72", marginTop: 2, letterSpacing: "0.05em" }}>CLIENT MANAGEMENT PORTAL</div>
        </div>
        <div style={{ flex: 1, padding: "8px 0" }}>
          {navItems.filter(n => !n.hidden).map(item => (
            <div key={item.id} className={page === item.id ? CLS.navActive : CLS.navItem}
              onClick={() => setPage(item.id)}
              style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 16px", cursor: "pointer", fontSize: 12,
                color: page === item.id ? "#4a69bd" : "#636e72",
                background: page === item.id ? "#1a1e2e" : "transparent",
                borderLeft: page === item.id ? "3px solid #4a69bd" : "3px solid transparent" }}>
              <span>{item.label}</span>
            </div>
          ))}
        </div>
        <div style={{ padding: "12px 16px", borderTop: "1px solid #1a1e2e", fontSize: 10, color: "#636e72" }}>
          <div>Logged in as: R. Sharma</div>
          <div style={{ marginTop: 2 }}>Role: Senior Analyst</div>
        </div>
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: 20 }}>
        {page === "dashboard" && renderDashboard()}
        {page === "clients" && renderClientSearch()}
        {page === "clientDetail" && renderClientDetail()}
        {page === "trades" && renderTrades()}
        {page === "compliance" && renderCompliance()}
      </div>
      {renderModal()}
    </div>
  );
}
