import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useJobPoller } from "../../hooks/useJobPoller";
import JobStatusBadge from "./JobStatusBadge";
import Spinner from "../ui/Spinner";
import Alert from "../ui/Alert";
import { Clock, FileText, Hash, Layers, Check, Loader2 } from "lucide-react";
import { formatTimestamp } from "../../utils/formatters";

const TERMINAL_STATUSES = ["COMPLETED", "FAILED", "REVIEW_REQUIRED"];

export default function JobStatusPoller({ jobId }) {
  const { job, isPolling, error } = useJobPoller(jobId);
  const navigate = useNavigate();

  // Auto-navigate to results when processing completes
  useEffect(() => {
    if (!job) return;
    if (
      job.status === "COMPLETED" ||
      job.status === "REVIEW_REQUIRED"
    ) {
      // Small delay so user sees the completed state
      const timer = setTimeout(() => {
        navigate(`/results/${jobId}`);
      }, 1200);
      return () => clearTimeout(timer);
    }
  }, [job, jobId, navigate]);

  if (error) {
    return <Alert variant="error" title="Polling error">{error}</Alert>;
  }

  if (!job) {
    return (
      <div className="flex items-center justify-center py-20 gap-3 text-gray-400">
        <Spinner />
        <span className="text-sm font-medium">Chargement du statut en cours…</span>
      </div>
    );
  }

  const isTerminal = TERMINAL_STATUSES.includes(job.status);

  return (
    <div
      className="bg-white rounded-2xl overflow-hidden"
      style={{
        border: "1px solid #e5e7eb",
        boxShadow:
          "0 1px 2px rgba(0,0,0,0.04), 0 4px 16px rgba(0,0,0,0.04)",
      }}
    >
      {/* ── Header ── */}
      <div className="px-7 py-6 flex items-center justify-between gap-4 border-b border-gray-100">
        <div className="flex items-center gap-3.5 min-w-0">
          <div
            className="flex-shrink-0 flex items-center justify-center rounded-xl"
            style={{
              width: 40,
              height: 40,
              background: "#f9fafb",
              border: "1px solid #e5e7eb",
            }}
          >
            <FileText size={17} className="text-gray-400" />
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-widest mb-0.5">
              Document
            </p>
            <p className="text-sm font-semibold text-gray-900 truncate max-w-xs sm:max-w-sm">
              {job.filename}
            </p>
          </div>
        </div>
        <div className="flex-shrink-0">
          <JobStatusBadge status={job.status} />
        </div>
      </div>

      {/* ── Meta strip ── */}
      <div
        className="px-7 py-4 grid gap-6 border-b border-gray-100"
        style={{
          background: "#fafafa",
          gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))",
        }}
      >
        <MetaItem icon={Hash} label="Job ID" value={job.job_id.slice(0, 8) + "…"} mono />
        <MetaItem icon={Layers} label="Pages" value={job.page_count ?? "—"} />
        <MetaItem
          icon={Clock}
          label="Started"
          value={formatTimestamp(job.processing_started_at)}
        />
      </div>

      {/* ── Active processing ── */}
      {!isTerminal && (
        <div className="px-7 py-7">
          {/* Status banner */}
          <div
            className="flex items-center gap-4 rounded-xl mb-6 px-5 py-4"
            style={{ background: "#f0f6ff", border: "1px solid #dbeafe" }}
          >
            <Spinner size="md" />
            <div>
              <p className="text-sm font-semibold text-blue-900">
                Traitement de votre document
              </p>
              <p className="text-xs text-blue-400 mt-0.5">
                  Le traitement prend généralement 2 à 5 minutes selon la complexité du PDF
              </p>
            </div>
          </div>

          <ProcessingSteps currentStatus={job.status} />
        </div>
      )}

      {/* ── Failed ── */}
      {job.status === "FAILED" && job.error && (
        <div className="px-7 pb-7">
          <Alert variant="error" title="Processing failed">
            {job.error}
          </Alert>
        </div>
      )}

      {/* ── Completed — redirecting ── */}
      {isTerminal && job.status !== "FAILED" && (
        <div className="px-7 py-5 border-t border-gray-100">
          <div className="flex items-center gap-2 text-sm font-semibold text-emerald-600">
            <Spinner size="sm" />
            Redirection vers les résultats…
          </div>
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────── */
/*  MetaItem                               */
/* ─────────────────────────────────────── */

function MetaItem({ icon: Icon, label, value, mono }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <Icon size={11} className="text-gray-400" />
        <span className="text-[10px] font-semibold uppercase tracking-widest text-gray-400">
          {label}
        </span>
      </div>
      <p
        className={`text-sm font-semibold text-gray-800 ${
          mono ? "font-mono tracking-tight" : ""
        }`}
      >
        {value}
      </p>
    </div>
  );
}

/* ─────────────────────────────────────── */
/*  ProcessingSteps                        */
/* ─────────────────────────────────────── */

const STEPS = [
  { status: "CLASSIFYING", label: "Classifying pages" },
  { status: "EXTRACTING", label: "Extracting data" },
  { status: "VALIDATING", label: "Validating fields" },
  { status: "MATCHING", label: "Matching documents" },
];

function ProcessingSteps({ currentStatus }) {
  const currentIdx = STEPS.findIndex((s) => s.status === currentStatus);
  const completedCount = currentIdx === -1 ? 0 : currentIdx;
  const overallPct = (completedCount / STEPS.length) * 100;

  return (
    <div>
      {/* ── Overall progress bar ── */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-gray-500">
            Progression globale
          </span>
          <span className="text-xs font-semibold text-gray-600 tabular-nums">
            {completedCount} / {STEPS.length} étapes
          </span>
        </div>
        <div
          className="w-full rounded-full overflow-hidden"
          style={{ height: 6, background: "#f3f4f6" }}
        >
          <div
            className="h-full rounded-full transition-all duration-700 ease-out"
            style={{
              width: `${overallPct}%`,
              background: "linear-gradient(90deg, #3b82f6, #6366f1)",
            }}
          />
        </div>
      </div>

      {/* ── Individual step rows ── */}
      <div className="space-y-2.5">
        {STEPS.map((step, i) => {
          const done = i < currentIdx;
          const active = i === currentIdx;
          const pending = !done && !active;

          return (
            <StepRow
              key={step.status}
              label={step.label}
              done={done}
              active={active}
              pending={pending}
            />
          );
        })}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────── */
/*  StepRow                                */
/* ─────────────────────────────────────── */

function StepRow({ label, done, active, pending }) {
  /* Border / background per state */
  const wrapStyle = done
    ? { border: "1px solid #d1fae5", background: "#f0fdf9" }
    : active
    ? { border: "1px solid #bfdbfe", background: "#eff6ff" }
    : { border: "1px solid #f3f4f6", background: "#fafafa" };

  /* Icon circle */
  const iconBg = done
    ? { background: "#d1fae5" }
    : active
    ? { background: "#dbeafe" }
    : { background: "#f3f4f6" };

  const iconColor = done
    ? "#059669"
    : active
    ? "#3b82f6"
    : "#d1d5db";

  /* Label colour */
  const labelColor = done
    ? "#065f46"
    : active
    ? "#1e3a8a"
    : "#9ca3af";

  /* Status pill */
  const pillBg = done
    ? "#d1fae5"
    : active
    ? "#dbeafe"
    : "transparent";

  const pillColor = done ? "#065f46" : active ? "#1d4ed8" : "#d1d5db";
  const pillText = done ? "Done" : active ? "In progress" : "Pending";

  return (
    <div
      className="relative rounded-xl overflow-hidden transition-all duration-300"
      style={wrapStyle}
    >
      {/* Active shimmer bar at top */}
      {active && (
        <div
          className="absolute top-0 left-0 right-0"
          style={{ height: 3, background: "#eff6ff" }}
        >
          <div
            style={{
              height: "100%",
              width: "55%",
              background: "linear-gradient(90deg, #93c5fd, #6366f1)",
              borderRadius: 9999,
              animation: "shimmer 1.8s ease-in-out infinite alternate",
            }}
          />
        </div>
      )}

      <div className="flex items-center gap-4 px-4 py-3.5">
        {/* State icon */}
        <div
          className="flex-shrink-0 flex items-center justify-center rounded-full transition-colors duration-300"
          style={{ width: 30, height: 30, ...iconBg }}
        >
          {done ? (
            <Check size={14} color={iconColor} strokeWidth={2.5} />
          ) : active ? (
            <Loader2
              size={14}
              color={iconColor}
              strokeWidth={2.5}
              className="animate-spin"
            />
          ) : (
            <span
              style={{
                display: "block",
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: iconColor,
              }}
            />
          )}
        </div>

        {/* Label + per-step progress bar */}
        <div className="flex-1 min-w-0">
          <p
            className="text-sm font-semibold leading-tight truncate"
            style={{ color: labelColor }}
          >
            {label}
          </p>

          {/* Step-level progress bar — only when active */}
          {active && (
            <div
              className="mt-2 rounded-full overflow-hidden"
              style={{ height: 4, background: "#bfdbfe" }}
            >
              <div
                style={{
                  height: "100%",
                  width: "60%",
                  background: "linear-gradient(90deg, #60a5fa, #818cf8)",
                  borderRadius: 9999,
                  animation: "shimmer 2.2s ease-in-out infinite alternate",
                }}
              />
            </div>
          )}

          {/* Completed bar — full green */}
          {done && (
            <div
              className="mt-2 rounded-full overflow-hidden"
              style={{ height: 4, background: "#a7f3d0" }}
            >
              <div
                style={{
                  height: "100%",
                  width: "100%",
                  background: "#10b981",
                  borderRadius: 9999,
                }}
              />
            </div>
          )}
        </div>

        {/* Pill badge */}
        <div className="flex-shrink-0">
          <span
            className="text-[11px] font-semibold px-2.5 py-1 rounded-full"
            style={{ background: pillBg, color: pillColor }}
          >
            {pillText}
          </span>
        </div>
      </div>

      {/* Keyframes injected once */}
      <style>{`
        @keyframes shimmer {
          from { width: 30%; }
          to { width: 75%; }
        }
      `}</style>
    </div>
  );
}