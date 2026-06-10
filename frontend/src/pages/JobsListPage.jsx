import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, CheckCircle2, Clock, FileText, RefreshCw } from "lucide-react";
import { getRecentJobs } from "../api/jobs";
import PageWrapper from "../components/layout/PageWrapper";
import Spinner from "../components/ui/Spinner";
import Alert from "../components/ui/Alert";

const STATUS_STYLE = {
  COMPLETED: { label: "Termine", color: "#047857", bg: "#ecfdf5", Icon: CheckCircle2 },
  FAILED: { label: "Echec", color: "#b91c1c", bg: "#fef2f2", Icon: AlertCircle },
  PENDING: { label: "En attente", color: "#92400e", bg: "#fffbeb", Icon: Clock },
  PROCESSING: { label: "Traitement", color: "#1d4ed8", bg: "#eff6ff", Icon: RefreshCw },
  CLASSIFYING: { label: "Classification", color: "#1d4ed8", bg: "#eff6ff", Icon: RefreshCw },
  EXTRACTING: { label: "Extraction", color: "#1d4ed8", bg: "#eff6ff", Icon: RefreshCw },
  VALIDATING: { label: "Validation", color: "#1d4ed8", bg: "#eff6ff", Icon: RefreshCw },
  MATCHING: { label: "Matching", color: "#1d4ed8", bg: "#eff6ff", Icon: RefreshCw },
  REVIEW_REQUIRED: { label: "A reviser", color: "#92400e", bg: "#fffbeb", Icon: AlertCircle },
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

export default function JobsListPage() {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let mounted = true;

    async function loadJobs() {
      setLoading(true);
      setError("");
      try {
        const data = await getRecentJobs(50);
        if (mounted) setJobs(Array.isArray(data) ? data : []);
      } catch (err) {
        if (mounted) setError(err.response?.data?.detail || err.message || "Impossible de charger les travaux.");
      } finally {
        if (mounted) setLoading(false);
      }
    }

    loadJobs();
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <PageWrapper title="Mes Travaux" subtitle="Historique des documents traites">
      <div className="max-w-5xl mx-auto">
        {loading && (
          <div className="flex justify-center py-16">
            <Spinner size="lg" />
          </div>
        )}

        {!loading && error && <Alert variant="error">{error}</Alert>}

        {!loading && !error && jobs.length === 0 && (
          <div className="bg-white border border-slate-200 rounded-xl p-8 text-center">
            <FileText size={32} className="mx-auto text-slate-300 mb-3" />
            <p className="text-sm font-semibold text-slate-700">Aucun travail pour le moment</p>
            <p className="text-xs text-slate-400 mt-1">Televersez un document pour demarrer le traitement.</p>
            <Link
              to="/"
              className="inline-flex items-center justify-center mt-5 px-4 py-2 rounded-lg bg-blue-700 text-white text-sm font-semibold hover:bg-blue-800 transition-colors"
            >
              Nouveau document
            </Link>
          </div>
        )}

        {!loading && !error && jobs.length > 0 && (
          <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
            <div className="grid grid-cols-[1fr_150px_150px_110px] gap-4 px-5 py-3 bg-slate-50 border-b border-slate-200 text-xs font-bold uppercase tracking-wide text-slate-500">
              <span>Document</span>
              <span>Statut</span>
              <span>Date</span>
              <span className="text-right">Action</span>
            </div>

            <div className="divide-y divide-slate-100">
              {jobs.map((job) => (
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
          </div>
        )}
      </div>
    </PageWrapper>
  );
}
