import { useEffect, useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, CheckCircle2, Clock, FileText, RefreshCw, Search, ChevronLeft, ChevronRight, X } from "lucide-react";
import { getRecentJobs } from "../api/jobs";
import PageWrapper from "../components/layout/PageWrapper";
import Spinner from "../components/ui/Spinner";
import Alert from "../components/ui/Alert";

const PAGE_SIZE = 20;

const STATUS_STYLE = {
  COMPLETED:       { label: "Terminé",        color: "#047857", bg: "#ecfdf5", Icon: CheckCircle2 },
  FAILED:          { label: "Échec",           color: "#b91c1c", bg: "#fef2f2", Icon: AlertCircle  },
  PENDING:         { label: "En attente",      color: "#92400e", bg: "#fffbeb", Icon: Clock        },
  PROCESSING:      { label: "Traitement",      color: "#1d4ed8", bg: "#eff6ff", Icon: RefreshCw    },
  CLASSIFYING:     { label: "Classification",  color: "#1d4ed8", bg: "#eff6ff", Icon: RefreshCw    },
  EXTRACTING:      { label: "Extraction",      color: "#1d4ed8", bg: "#eff6ff", Icon: RefreshCw    },
  VALIDATING:      { label: "Validation",      color: "#1d4ed8", bg: "#eff6ff", Icon: RefreshCw    },
  MATCHING:        { label: "Matching",        color: "#1d4ed8", bg: "#eff6ff", Icon: RefreshCw    },
  REVIEW_REQUIRED: { label: "À réviser",       color: "#92400e", bg: "#fffbeb", Icon: AlertCircle  },
};

function formatDate(value) {
  if (!value) return "-";
  return new Intl.DateTimeFormat("fr-TN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function StatusBadge({ status }) {
  const cfg = STATUS_STYLE[status] || { label: status || "-", color: "#475569", bg: "#f1f5f9", Icon: Clock };
  const Icon = cfg.Icon;
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "5px 9px",
        borderRadius: 999,
        background: cfg.bg,
        color: cfg.color,
        fontSize: "0.75rem",
        fontWeight: 700,
        whiteSpace: "nowrap",
      }}
    >
      <Icon size={13} strokeWidth={2.2} />
      {cfg.label}
    </span>
  );
}

/** Returns true if the job matches the search query across all fields */
function jobMatchesQuery(job, query) {
  if (!query.trim()) return true;
  const q = query.toLowerCase().trim();

  const statusLabel = (STATUS_STYLE[job.status]?.label || job.status || "").toLowerCase();
  const fields = [
    job.filename,
    job.id,
    job.job_id,
    job.status,
    statusLabel,
    formatDate(job.created_at),
    formatDate(job.updated_at),
  ];

  return fields.some((f) => f && String(f).toLowerCase().includes(q));
}

function Pagination({ page, totalPages, onChange }) {
  if (totalPages <= 1) return null;

  const pages = [];
  const delta = 2;
  const left  = page - delta;
  const right = page + delta;

  for (let i = 1; i <= totalPages; i++) {
    if (i === 1 || i === totalPages || (i >= left && i <= right)) {
      pages.push(i);
    } else if (i === left - 1 || i === right + 1) {
      pages.push("...");
    }
  }

  return (
    <div className="flex items-center justify-between px-5 py-3 border-t border-slate-100 bg-slate-50">
      <span className="text-xs text-slate-500">
        Page <strong>{page}</strong> sur <strong>{totalPages}</strong>
      </span>

      <div className="flex items-center gap-1">
        <button
          onClick={() => onChange(page - 1)}
          disabled={page === 1}
          className="p-1.5 rounded-md text-slate-500 hover:bg-slate-200 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          aria-label="Page précédente"
        >
          <ChevronLeft size={16} />
        </button>

        {pages.map((p, i) =>
          p === "..." ? (
            <span key={`ellipsis-${i}`} className="px-1 text-slate-400 text-sm select-none">
              …
            </span>
          ) : (
            <button
              key={p}
              onClick={() => onChange(p)}
              className={`min-w-[30px] h-[30px] rounded-md text-xs font-semibold transition-colors ${
                p === page
                  ? "bg-blue-700 text-white shadow-sm"
                  : "text-slate-600 hover:bg-slate-200"
              }`}
            >
              {p}
            </button>
          )
        )}

        <button
          onClick={() => onChange(page + 1)}
          disabled={page === totalPages}
          className="p-1.5 rounded-md text-slate-500 hover:bg-slate-200 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          aria-label="Page suivante"
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}

export default function JobsListPage() {
  const [jobs,    setJobs]    = useState([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");
  const [query,   setQuery]   = useState("");
  const [page,    setPage]    = useState(1);

  useEffect(() => {
    let mounted = true;
    async function loadJobs() {
      setLoading(true);
      setError("");
      try {
        const data = await getRecentJobs(50);
        if (mounted) setJobs(Array.isArray(data) ? data : []);
      } catch (err) {
        if (mounted)
          setError(err.response?.data?.detail || err.message || "Impossible de charger les travaux.");
      } finally {
        if (mounted) setLoading(false);
      }
    }
    loadJobs();
    return () => { mounted = false; };
  }, []);

  // Reset to page 1 whenever search query changes
  useEffect(() => { setPage(1); }, [query]);

  const filtered = useMemo(
    () => jobs.filter((job) => jobMatchesQuery(job, query)),
    [jobs, query]
  );

  const totalPages  = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage    = Math.min(page, totalPages);
  const pageSlice   = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  return (
    <PageWrapper title="Mes Travaux" subtitle="Historique des documents traités">
      <div className="max-w-5xl mx-auto">

        {/* ── Search bar ── */}
        {!loading && !error && jobs.length > 0 && (
          <div className="relative mb-4">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none"
            />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Rechercher par nom, statut, identifiant, date…"
              className="w-full pl-9 pr-9 py-2.5 rounded-xl border border-slate-200 bg-white text-sm text-slate-800 placeholder-slate-400 shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"
            />
            {query && (
              <button
                onClick={() => setQuery("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                aria-label="Effacer la recherche"
              >
                <X size={15} />
              </button>
            )}
          </div>
        )}

        {/* ── Loading ── */}
        {loading && (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        )}

        {/* ── Error ── */}
        {!loading && error && <Alert variant="error">{error}</Alert>}

        {/* ── Empty (no jobs at all) ── */}
        {!loading && !error && jobs.length === 0 && (
          <div className="bg-white border border-slate-200 rounded-xl p-8 text-center">
            <FileText size={32} className="mx-auto text-slate-300 mb-3" />
            <p className="text-sm font-semibold text-slate-700">Aucun travail pour le moment</p>
            <p className="text-xs text-slate-400 mt-1">Téléversez un document pour démarrer le traitement.</p>
            <Link
              to="/"
              className="inline-flex items-center justify-center mt-5 px-4 py-2 rounded-lg bg-blue-700 text-white text-sm font-semibold hover:bg-blue-800 transition-colors"
            >
              Nouveau document
            </Link>
          </div>
        )}

        {/* ── No search results ── */}
        {!loading && !error && jobs.length > 0 && filtered.length === 0 && (
          <div className="bg-white border border-slate-200 rounded-xl p-8 text-center">
            <Search size={28} className="mx-auto text-slate-300 mb-3" />
            <p className="text-sm font-semibold text-slate-700">Aucun résultat pour « {query} »</p>
            <p className="text-xs text-slate-400 mt-1">Essayez un autre terme de recherche.</p>
            <button
              onClick={() => setQuery("")}
              className="mt-4 text-sm text-blue-700 font-semibold hover:underline"
            >
              Effacer la recherche
            </button>
          </div>
        )}

        {/* ── Table ── */}
        {!loading && !error && pageSlice.length > 0 && (
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">

            {/* Results count */}
            <div className="px-5 py-2.5 border-b border-slate-100 flex items-center justify-between">
              <span className="text-xs text-slate-500">
                {filtered.length} résultat{filtered.length !== 1 ? "s" : ""}
                {query && (
                  <span className="ml-1">
                    pour <strong className="text-slate-700">« {query} »</strong>
                  </span>
                )}
              </span>
              <span className="text-xs text-slate-400">
                {PAGE_SIZE} par page
              </span>
            </div>

            {/* Header */}
            <div className="grid grid-cols-[1fr_150px_150px_110px] gap-4 px-5 py-3 bg-slate-50 border-b border-slate-200 text-xs font-bold uppercase tracking-wide text-slate-500">
              <span>Document</span>
              <span>Statut</span>
              <span>Date</span>
              <span className="text-right">Action</span>
            </div>

            {/* Rows */}
            <div className="divide-y divide-slate-100">
              {pageSlice.map((job) => (
                <div
                  key={job.id || job.job_id}
                  className="grid grid-cols-[1fr_150px_150px_110px] gap-4 px-5 py-4 items-center hover:bg-slate-50 transition-colors"
                >
                  <div className="min-w-0 flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg bg-blue-50 border border-blue-100 flex items-center justify-center flex-shrink-0">
                      <FileText size={16} className="text-blue-700" />
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm font-semibold text-slate-800 truncate">
                        {job.filename || `Job ${job.id || job.job_id}`}
                      </p>
                      <p className="text-xs text-slate-400 font-mono truncate">
                        {job.id || job.job_id}
                      </p>
                    </div>
                  </div>

                  <StatusBadge status={job.status} />

                  <span className="text-xs text-slate-500">
                    {formatDate(job.created_at)}
                  </span>

                  <div className="text-right">
                    <Link
                      to={`/jobs/${job.id || job.job_id}`}
                      className="text-sm font-semibold text-blue-700 hover:text-blue-900"
                    >
                      Ouvrir
                    </Link>
                  </div>
                </div>
              ))}
            </div>

            {/* Pagination */}
            <Pagination
              page={safePage}
              totalPages={totalPages}
              onChange={(p) => setPage(p)}
            />
          </div>
        )}
      </div>
    </PageWrapper>
  );
}