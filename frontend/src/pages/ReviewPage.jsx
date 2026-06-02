function LegacyReviewPage() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const { results, loading, error, refetch } = useJobResults(jobId);

  const [reviewerId, setReviewerId] = useState("");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState(null);
  const [submitted, setSubmitted] = useState(false);
  const [aliasSaving, setAliasSaving] = useState({});
  const [aliasSaved, setAliasSaved] = useState({});

  // Keep aliasSaved in sync with server-side applied aliases so refresh
  // shows approved state without needing to click again.
  useEffect(() => {
    try {
      const applied = (results?.match_result?.line_verdicts || []).reduce((acc, line) => {
        if (line.reference_alias_applied) {
          const externalRef = line.ref_produit_facture || line.ref_produit_bl;
          const internalRef = line.ref_produit;
          if (externalRef && internalRef) acc[`${externalRef}:${internalRef}`] = true;
        }
        return acc;
      }, {});
      if (Object.keys(applied).length) {
        setAliasSaved((prev) => ({ ...prev, ...applied }));
      }
    } catch (e) {
      // ignore
    }
  }, [results]);

  const handleSubmit = async (approved) => {
    if (!reviewerId.trim()) {
      setSubmitError("Veuillez saisir votre nom ou identifiant.");
      return;
    }

    setSubmitting(true);
    setSubmitError(null);

    try {
      await submitReview(jobId, { reviewerId, approved, notes });
      setSubmitted(true);
      setTimeout(() => navigate(`/results/${jobId}`), 1500);
    } catch (err) {
      setSubmitError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const supplierName =
    results?.documents?.find((doc) => doc.doc_type === "FACTURE")?.supplier_name ||
    results?.documents?.find((doc) => doc.doc_type === "BL")?.supplier_name ||
    null;

  const aliasCandidates = (results?.match_result?.line_verdicts || []).filter((line) => {
    const externalRef = line.ref_produit_facture || line.ref_produit_bl;
    const internalRef = line.ref_produit;
    const qtyMatches =
      line.qty_bc != null &&
      (line.ref_produit_facture ? line.qty_facture != null : line.qty_bl != null) &&
      Number(line.qty_bc) === Number(line.ref_produit_facture ? line.qty_facture : line.qty_bl);
    const invoicePriceMatches =
      line.ref_produit_facture &&
      line.prix_bc != null &&
      line.prix_facture != null &&
      Math.abs(Number(line.prix_bc) - Number(line.prix_facture)) <= 0.100;
    return (
      externalRef &&
      internalRef &&
      externalRef !== internalRef &&
      ["LOW_CONFIDENCE", "PARTIAL_MATCH", "MATCH"].includes(line.verdict) &&
      (!line.mismatch_fields || line.mismatch_fields.length === 0) &&
      !line.reference_alias_applied &&
      (line.ref_produit_facture ? (qtyMatches && invoicePriceMatches) : qtyMatches)
    );
  });

  const handleApproveAlias = async (line) => {
    if (!reviewerId.trim()) {
      setSubmitError("Veuillez saisir votre nom ou identifiant avant d'approuver un alias.");
      return;
    }

    const externalRef = line.ref_produit_facture || line.ref_produit_bl;
    const internalRef = line.ref_produit;
    const key = `${externalRef}:${internalRef}`;

    setAliasSaving((prev) => ({ ...prev, [key]: true }));
    setSubmitError(null);
    try {
      await approveReferenceAlias(jobId, {
        reviewerId,
        externalRef,
        internalRef,
        supplierName,
        notes: notes || undefined,
      });
      // Trigger rematch so the saved alias is applied to the current job
      try {
        await rerunMatch(jobId);
      } catch (e) {
        // ignore rematch failure but continue to mark saved
      }
      // Refresh displayed results
      try { await refetch(); } catch (e) {}
      setAliasSaved((prev) => ({ ...prev, [key]: true }));
    } catch (err) {
      setSubmitError(err.message);
    } finally {
      setAliasSaving((prev) => ({ ...prev, [key]: false }));
    }
  };

  if (loading) {
    return (
      <PageWrapper title="Loading…">
        <div className="flex justify-center py-20"><Spinner size="lg" /></div>
      </PageWrapper>
    );
  }

  if (error) {
    return (
      <PageWrapper title="Erreur">
        <Alert variant="error">{error}</Alert>
      </PageWrapper>
    );
  }

  if (!results) return null;

  if (submitted) {
    return (
      <PageWrapper title="Révision soumise">
        <Alert variant="success" title="Décision enregistrée">
          Votre révision a été enregistrée dans le journal d'audit. Redirection…
        </Alert>
      </PageWrapper>
    );
  }

  return (
    <PageWrapper
      title="Révision humaine"
      subtitle="Vérifiez les données extraites et les résultats de correspondance, puis approuvez ou rejetez."
    >
      <div className="space-y-6">
        {/* Back button */}
        <button
          onClick={() => navigate(`/results/${jobId}`)}
          className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft size={14} />
          Retour aux résultats
        </button>

        {/* Verdict */}
        <VerdictBanner
          verdict={results.verdict}
          matchResult={results.match_result}
        />

        {/* Documents */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {results.documents?.map((doc, i) => (
            <DocumentSummary key={i} document={doc} />
          ))}
        </div>

        {/* Line table */}
        {results.match_result?.line_verdicts?.length > 0 && (
          <LineItemTable lineVerdicts={results.match_result.line_verdicts} />
        )}

        {aliasCandidates.length > 0 && (
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <h3 className="text-base font-semibold text-gray-900 mb-4">
              Alias de références à mémoriser
            </h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-xs text-gray-500 uppercase tracking-wide">
                    <th className="text-left py-2 pr-4 font-semibold">Ref fournisseur</th>
                    <th className="text-left py-2 pr-4 font-semibold">Ref interne</th>
                    <th className="text-left py-2 pr-4 font-semibold">Designation</th>
                    <th className="text-right py-2 font-semibold">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {aliasCandidates.map((line) => {
                    const externalRef = line.ref_produit_facture || line.ref_produit_bl;
                    const internalRef = line.ref_produit;
                    const key = `${externalRef}:${internalRef}`;
                    const saved = aliasSaved[key];
                    return (
                      <tr key={key}>
                        <td className="py-3 pr-4 font-mono text-xs text-gray-700 whitespace-nowrap">
                          {externalRef}
                        </td>
                        <td className="py-3 pr-4 font-mono text-xs text-gray-700 whitespace-nowrap">
                          {internalRef}
                        </td>
                        <td className="py-3 pr-4 text-xs text-gray-500 max-w-[340px] truncate">
                          {line.designation || "-"}
                        </td>
                        <td className="py-3 text-right">
                          <button
                            onClick={() => handleApproveAlias(line)}
                            disabled={saved || aliasSaving[key] || line.reference_alias_applied}
                            className="inline-flex items-center justify-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-xs font-semibold text-white transition-colors hover:bg-blue-700 disabled:bg-gray-300"
                          >
                            {aliasSaving[key] ? <Spinner size="sm" /> : <CheckCircle size={14} />}
                            {saved || line.reference_alias_applied ? "Enregistré" : "Approuver alias"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Review form */}
        <div className="bg-white border border-gray-200 rounded-xl p-6">
          <h3 className="text-base font-semibold text-gray-900 mb-4">
            Soumettre la décision de révision
          </h3>

          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Votre nom / ID évaluateur *
              </label>
              <input
                type="text"
                value={reviewerId}
                onChange={(e) => setReviewerId(e.target.value)}
                placeholder="ex. Ahmed Benali"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Notes (optionnelles)
              </label>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Ajoutez des commentaires sur cette décision…"
                rows={3}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
            </div>

            {submitError && (
              <Alert variant="error">{submitError}</Alert>
            )}

            <div className="flex gap-3 pt-2">
              <button
                onClick={() => handleSubmit(true)}
                disabled={submitting}
                className="flex-1 flex items-center justify-center gap-2 bg-green-600 hover:bg-green-700 disabled:bg-green-300 text-white font-semibold py-3 rounded-xl transition-colors"
              >
                {submitting ? <Spinner size="sm" /> : <CheckCircle size={18} />}
                Approuver
              </button>

              <button
                onClick={() => handleSubmit(false)}
                disabled={submitting}
                className="flex-1 flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 disabled:bg-red-300 text-white font-semibold py-3 rounded-xl transition-colors"
              >
                {submitting ? <Spinner size="sm" /> : <XCircle size={18} />}
                Rejeter
              </button>
            </div>

            <p className="text-xs text-gray-400 text-center">
              Cette décision est définitive et sera enregistrée dans le journal d'audit immuable.
            </p>
          </div>
        </div>
      </div>
    </PageWrapper>
  );
}
// src/pages/ReviewPage.jsx
import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useJobResults } from "../hooks/useJobResults";
import {
  approveReferenceAlias,
  submitReview,
  saveLineEdits,
  saveDocumentHeader,
  rerunMatch,
  getPdfViewUrl,
} from "../api/admin";
import PageWrapper from "../components/layout/PageWrapper";
import Spinner from "../components/ui/Spinner";
import Alert from "../components/ui/Alert";
import { formatMismatchField } from "../utils/mismatchFields";
import {
  CheckCircle2, XCircle, AlertTriangle, ArrowLeft, Edit3,
  Save, X, ChevronDown, ChevronUp, FileText, ClipboardList,
  Building2, Calendar, Layers, TrendingUp, Info, Plus, Trash2,
  RefreshCw, Eye, EyeOff, CheckCircle, ArrowRight, BookOpen,
  Zap, Shield, FileSearch,
} from "lucide-react";

// ─── Verdict config ───────────────────────────────────────────────────────────
const LINE_VERDICT_CFG = {
  MATCH:          { label: "Concordant",          colors: "bg-emerald-50 text-emerald-700 ring-emerald-200", row: "border-l-emerald-400", rowBg: "" },
  MISMATCH:       { label: "Écart",               colors: "bg-red-50 text-red-700 ring-red-200",            row: "border-l-red-400",     rowBg: "bg-red-50/40" },
  MISSING:        { label: "Manquant",            colors: "bg-amber-50 text-amber-700 ring-amber-200",      row: "border-l-amber-400",   rowBg: "bg-amber-50/30" },
  EXTRA:          { label: "Supplémentaire",      colors: "bg-sky-50 text-sky-700 ring-sky-200",            row: "border-l-sky-400",     rowBg: "bg-sky-50/20" },
  PARTIAL_DATA:   { label: "Données partielles",  colors: "bg-slate-100 text-slate-500 ring-slate-200",     row: "border-l-slate-300",   rowBg: "" },
  LOW_CONFIDENCE: { label: "Faible confiance",    colors: "bg-violet-50 text-violet-700 ring-violet-200",   row: "border-l-violet-400",  rowBg: "bg-violet-50/20" },
  PARTIAL_MATCH:  { label: "Concordance partielle", colors: "bg-orange-50 text-orange-700 ring-orange-200", row: "border-l-orange-400",  rowBg: "bg-orange-50/20" },
};

const GLOBAL_VERDICT_CFG = {
  VALIDATED:       { label: "Validé",     gradient: "from-emerald-600 to-emerald-700", Icon: CheckCircle2, desc: "Toutes les lignes concordent." },
  REJECTED:        { label: "Rejeté",     gradient: "from-red-600 to-red-700",         Icon: XCircle,      desc: "Écarts critiques détectés." },
  REVIEW_REQUIRED: { label: "À réviser",  gradient: "from-amber-500 to-amber-600",     Icon: AlertTriangle, desc: "Vérification humaine requise." },
  REVIEW:          { label: "À réviser",  gradient: "from-amber-500 to-amber-600",     Icon: AlertTriangle, desc: "Vérification humaine requise." },
  PARTIAL:         { label: "Partiel",    gradient: "from-blue-500 to-blue-600",        Icon: Info,         desc: "Livraison partielle détectée." },
  INCOMPLETE:      { label: "Incomplet",  gradient: "from-slate-500 to-slate-600",      Icon: Info,         desc: "Documents manquants." },
};

const DOC_TYPE_CFG = {
  FACTURE: { border: "border-l-blue-400",   badge: "bg-blue-50 text-blue-700",     label: "Facture",          headerBg: "bg-blue-50/40" },
  BC:      { border: "border-l-violet-400", badge: "bg-violet-50 text-violet-700", label: "Bon de Commande",  headerBg: "bg-violet-50/40" },
  BL:      { border: "border-l-teal-400",   badge: "bg-teal-50 text-teal-700",     label: "Bon de Livraison", headerBg: "bg-teal-50/40" },
};

// ─── Tiny helpers ─────────────────────────────────────────────────────────────
const fmtNum  = (v, dec = 3) => v != null ? Number(v).toLocaleString("fr-TN", { minimumFractionDigits: dec, maximumFractionDigits: dec }) : "—";
const fmtQty  = (v)          => v != null ? Number(v).toLocaleString("fr-TN", { maximumFractionDigits: 0 }) : "—";
const pct     = (v)          => v != null ? Math.round(Number(v) <= 1 ? Number(v) * 100 : Number(v)) : null;

function VerdictBadge({ verdict }) {
  const cfg = LINE_VERDICT_CFG[verdict] ?? { label: verdict ?? "—", colors: "bg-slate-100 text-slate-500 ring-slate-200" };
  return (
    <span className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset whitespace-nowrap ${cfg.colors}`}>
      {cfg.label}
    </span>
  );
}

function ConfPill({ value }) {
  if (value == null) return <span className="text-xs text-slate-300">—</span>;
  const p = Math.round(Number(value) * 100);
  const cls = p >= 85 ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
    : p >= 65 ? "bg-amber-50 text-amber-700 ring-amber-200"
    : "bg-red-50 text-red-700 ring-red-200";
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${cls}`}>
      {p}%
    </span>
  );
}

// ─── PDF Viewer Panel ─────────────────────────────────────────────────────────
function PdfViewer({ jobId }) {
  const [url, setUrl]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    getPdfViewUrl(jobId)
      .then(setUrl)
      .catch(() => setError("Impossible de charger le PDF."))
      .finally(() => setLoading(false));
  }, [jobId]);

  if (hidden) {
    return (
      <div className="flex items-center justify-center h-12 bg-slate-100 rounded-xl border border-slate-200 cursor-pointer hover:bg-slate-200 transition-colors" onClick={() => setHidden(false)}>
        <Eye size={14} className="text-slate-500 mr-1.5" />
        <span className="text-xs text-slate-500 font-medium">Afficher le PDF</span>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2.5 bg-slate-50 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <FileText size={13} className="text-slate-500" />
          <span className="text-xs font-semibold text-slate-600">Document source — PDF</span>
        </div>
        <button onClick={() => setHidden(true)} className="text-slate-400 hover:text-slate-600 transition-colors">
          <EyeOff size={13} />
        </button>
      </div>
      <div className="h-[calc(100vh-200px)] min-h-[500px]">
        {loading && (
          <div className="flex items-center justify-center h-full">
            <Spinner size="lg" />
          </div>
        )}
        {error && (
          <div className="flex items-center justify-center h-full text-sm text-slate-400">{error}</div>
        )}
        {url && !loading && (
          <iframe
            src={url}
            className="w-full h-full border-none"
            title="Document source PDF"
          />
        )}
      </div>
    </div>
  );
}

// ─── Editable line row ────────────────────────────────────────────────────────
function EditableLineRow({ line, lineIndex, isEditing, onChange, onDelete }) {
  const handleField = (field, value) => onChange(lineIndex, field, value);

  if (!isEditing) {
    return (
      <tr className="border-b border-slate-50 hover:bg-slate-50/60 last:border-none">
        <td className="px-3 py-1.5 font-mono text-xs text-slate-600 whitespace-nowrap align-top">{line.ref_produit || "—"}</td>
        <td className="px-3 py-1.5 text-xs text-slate-600 align-top max-w-[200px]">{line.designation || "—"}</td>
        <td className="px-3 py-1.5 text-right font-mono text-xs text-slate-700 align-top whitespace-nowrap">{line.qty != null ? Number(line.qty) : "—"}</td>
        <td className="px-3 py-1.5 text-right font-mono text-xs text-slate-700 align-top whitespace-nowrap">{fmtNum(line.prix_unitaire)}</td>
        <td className="px-3 py-1.5 text-right font-mono text-xs text-slate-400 align-top whitespace-nowrap">{line.tva_rate != null ? `${line.tva_rate}%` : "—"}</td>
        <td className="px-3 py-1.5 text-right font-mono text-xs text-slate-700 align-top whitespace-nowrap">{fmtNum(line.total_ligne_ht)}</td>
        <td className="px-3 py-1.5 align-top"><ConfPill value={line.extraction_confidence} /></td>
      </tr>
    );
  }

  const inputCls = "w-full border border-slate-300 rounded px-1.5 py-1 text-xs font-mono focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white";
  return (
    <tr className="border-b border-blue-100 bg-blue-50/30">
      <td className="px-2 py-1.5 align-top">
        <input className={inputCls} value={line.ref_produit || ""} onChange={e => handleField("ref_produit", e.target.value)} placeholder="Réf" />
      </td>
      <td className="px-2 py-1.5 align-top">
        <input className={`${inputCls} min-w-[160px]`} value={line.designation || ""} onChange={e => handleField("designation", e.target.value)} placeholder="Désignation" />
      </td>
      <td className="px-2 py-1.5 align-top">
        <input className={`${inputCls} w-16 text-right`} type="number" value={line.qty ?? ""} onChange={e => handleField("qty", e.target.value)} placeholder="Qté" />
      </td>
      <td className="px-2 py-1.5 align-top">
        <input className={`${inputCls} w-20 text-right`} type="number" step="0.001" value={line.prix_unitaire ?? ""} onChange={e => handleField("prix_unitaire", e.target.value)} placeholder="P.U." />
      </td>
      <td className="px-2 py-1.5 align-top">
        <input className={`${inputCls} w-14 text-right`} type="number" value={line.tva_rate ?? ""} onChange={e => handleField("tva_rate", e.target.value)} placeholder="TVA" />
      </td>
      <td className="px-2 py-1.5 align-top">
        <input className={`${inputCls} w-20 text-right`} type="number" step="0.001" value={line.total_ligne_ht ?? ""} onChange={e => handleField("total_ligne_ht", e.target.value)} placeholder="Total" />
      </td>
      <td className="px-2 py-1.5 align-top text-center">
        <button onClick={() => onDelete(lineIndex)} className="text-red-400 hover:text-red-600 transition-colors" title="Supprimer cette ligne">
          <Trash2 size={13} />
        </button>
      </td>
    </tr>
  );
}

// ─── Editable Document Card ───────────────────────────────────────────────────
function EditableDocCard({ doc, jobId, onSaved }) {
  const tc          = DOC_TYPE_CFG[doc.doc_type] ?? DOC_TYPE_CFG.BL;
  const [open, setOpen]         = useState(true);
  const [editing, setEditing]   = useState(false);
  const [saving, setSaving]     = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [saved, setSaved]       = useState(false);

  // Local editable copies
  const [header, setHeader]     = useState({
    ref_document:  doc.ref_document  || "",
    document_date: doc.document_date || "",
    supplier_name: doc.supplier_name || "",
    total_ht:      doc.total_ht      ?? "",
    total_ttc:     doc.total_ttc     ?? "",
  });
  const [lines, setLines] = useState(
    (doc.lines || []).map(l => ({ ...l }))
  );

  const handleLineChange = (idx, field, value) => {
    setLines(prev => prev.map((l, i) => i === idx ? { ...l, [field]: value } : l));
  };
  const handleDeleteLine = (idx) => {
    setLines(prev => prev.filter((_, i) => i !== idx));
  };
  const handleAddLine = () => {
    setLines(prev => [...prev, {
      line_number: prev.length + 1,
      ref_produit: "", designation: "", qty: null,
      prix_unitaire: null, tva_rate: null, total_ligne_ht: null,
      extraction_confidence: 1.0,
    }]);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await saveDocumentHeader(jobId, doc.id, header);
      const editPayload = lines.map((l, i) => ({
        line_id: l.id,
        line_number: i + 1,
        ref_produit:     l.ref_produit    || null,
        designation:     l.designation    || null,
        qty:             l.qty    != null ? Number(l.qty)             : null,
        prix_unitaire:   l.prix_unitaire  != null ? Number(l.prix_unitaire)  : null,
        tva_rate:        l.tva_rate       != null ? Number(l.tva_rate)       : null,
        total_ligne_ht:  l.total_ligne_ht != null ? Number(l.total_ligne_ht) : null,
      }));
      await saveLineEdits(jobId, doc.id, editPayload);
      setSaved(true);
      setEditing(false);
      onSaved?.();
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setSaveError(err.message || "Erreur lors de la sauvegarde.");
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setHeader({
      ref_document:  doc.ref_document  || "",
      document_date: doc.document_date || "",
      supplier_name: doc.supplier_name || "",
      total_ht:      doc.total_ht      ?? "",
      total_ttc:     doc.total_ttc     ?? "",
    });
    setLines((doc.lines || []).map(l => ({ ...l })));
    setEditing(false);
    setSaveError(null);
  };

  const inputCls = "border border-slate-300 rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white w-full";

  return (
    <div className={`bg-white rounded-xl border border-slate-200 border-l-4 ${tc.border} shadow-sm overflow-hidden`}>
      {/* Header */}
      <div className={`px-4 py-3 ${tc.headerBg}`}>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className={`text-[11px] font-semibold px-2 py-0.5 rounded shrink-0 ${tc.badge}`}>{tc.label}</span>
            {editing ? (
              <input
                className="border border-blue-300 rounded px-2 py-0.5 text-sm font-mono font-semibold focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
                value={header.ref_document}
                onChange={e => setHeader(h => ({ ...h, ref_document: e.target.value }))}
                placeholder="Référence"
              />
            ) : (
              <span className="font-mono text-sm font-semibold text-slate-800 truncate">{header.ref_document || "—"}</span>
            )}
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            {saved && (
              <span className="text-[11px] text-emerald-600 font-medium flex items-center gap-1">
                <CheckCircle size={11} /> Sauvegardé
              </span>
            )}
            {!editing ? (
              <button
                onClick={() => setEditing(true)}
                className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-blue-600 border border-slate-200 hover:border-blue-300 rounded-lg px-2.5 py-1 transition-colors font-medium"
              >
                <Edit3 size={11} /> Modifier
              </button>
            ) : (
              <>
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="flex items-center gap-1 text-[11px] text-white bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 rounded-lg px-2.5 py-1 transition-colors font-semibold"
                >
                  {saving ? <Spinner size="sm" /> : <Save size={11} />}
                  Sauvegarder
                </button>
                <button
                  onClick={handleCancel}
                  className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-700 border border-slate-200 rounded-lg px-2.5 py-1 transition-colors"
                >
                  <X size={11} /> Annuler
                </button>
              </>
            )}
            <button onClick={() => setOpen(o => !o)} className="text-slate-400 hover:text-slate-600 ml-1">
              {open ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            </button>
          </div>
        </div>

        {/* Meta fields */}
        {open && (
          <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-3">
            <div className="flex items-start gap-2">
              <Calendar size={11} className="text-slate-400 mt-1 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-[10px] text-slate-400 uppercase tracking-wide mb-0.5">Date</div>
                {editing
                  ? <input className={inputCls} value={header.document_date} onChange={e => setHeader(h => ({ ...h, document_date: e.target.value }))} placeholder="JJ/MM/AAAA" />
                  : <span className="text-xs text-slate-700 font-medium">{header.document_date || "—"}</span>
                }
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Building2 size={11} className="text-slate-400 mt-1 shrink-0" />
              <div className="min-w-0 flex-1">
                <div className="text-[10px] text-slate-400 uppercase tracking-wide mb-0.5">Fournisseur</div>
                {editing
                  ? <input className={inputCls} value={header.supplier_name} onChange={e => setHeader(h => ({ ...h, supplier_name: e.target.value }))} placeholder="Nom fournisseur" />
                  : <span className="text-xs text-slate-700 font-medium">{header.supplier_name || "—"}</span>
                }
              </div>
            </div>
            {(doc.total_ht != null || doc.doc_type === "FACTURE") && (
              <div className="flex items-start gap-2">
                <TrendingUp size={11} className="text-slate-400 mt-1 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wide mb-0.5">Total HT</div>
                  {editing
                    ? <input className={`${inputCls} font-mono`} type="number" step="0.01" value={header.total_ht} onChange={e => setHeader(h => ({ ...h, total_ht: e.target.value }))} placeholder="0.00" />
                    : <span className="text-xs font-mono font-semibold text-slate-800">{fmtNum(header.total_ht, 2)} DT</span>
                  }
                </div>
              </div>
            )}
            {(doc.total_ttc != null || doc.doc_type === "FACTURE") && (
              <div className="flex items-start gap-2">
                <TrendingUp size={11} className="text-slate-400 mt-1 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="text-[10px] text-slate-400 uppercase tracking-wide mb-0.5">Total TTC</div>
                  {editing
                    ? <input className={`${inputCls} font-mono`} type="number" step="0.01" value={header.total_ttc} onChange={e => setHeader(h => ({ ...h, total_ttc: e.target.value }))} placeholder="0.00" />
                    : <span className="text-xs font-mono font-semibold text-slate-900">{fmtNum(header.total_ttc, 2)} DT</span>
                  }
                </div>
              </div>
            )}
          </div>
        )}

        {saveError && open && (
          <div className="mt-2 text-[11px] text-red-600 bg-red-50 border border-red-200 rounded px-2.5 py-1.5">{saveError}</div>
        )}
      </div>

      {/* Lines table */}
      {open && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-100">
                <th className="text-left px-3 py-2 text-slate-400 font-medium whitespace-nowrap">Réf</th>
                <th className="text-left px-3 py-2 text-slate-400 font-medium">Désignation</th>
                <th className="text-right px-3 py-2 text-slate-400 font-medium">Qté</th>
                <th className="text-right px-3 py-2 text-slate-400 font-medium whitespace-nowrap">Prix UN HT</th>
                <th className="text-right px-3 py-2 text-slate-400 font-medium">TVA</th>
                <th className="text-right px-3 py-2 text-slate-400 font-medium whitespace-nowrap">Total HT</th>
                <th className="px-3 py-2 text-slate-400 font-medium text-center">{editing ? "Suppr." : "Conf."}</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((line, i) => (
                <EditableLineRow
                  key={line.id ?? i}
                  line={line}
                  lineIndex={i}
                  isEditing={editing}
                  onChange={handleLineChange}
                  onDelete={handleDeleteLine}
                />
              ))}
            </tbody>
          </table>
          {editing && (
            <button
              onClick={handleAddLine}
              className="w-full flex items-center justify-center gap-1.5 py-2 text-[11px] text-blue-600 hover:bg-blue-50 border-t border-slate-100 transition-colors font-medium"
            >
              <Plus size={12} /> Ajouter une ligne
            </button>
          )}
          {lines.length === 0 && !editing && (
            <div className="px-4 py-4 text-center text-xs text-slate-400">Aucune ligne extraite</div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Full comparison row ──────────────────────────────────────────────────────
function CompareRow({ lv }) {
  const [expanded, setExpanded] = useState(false);
  const cfg = LINE_VERDICT_CFG[lv.verdict] ?? LINE_VERDICT_CFG.PARTIAL_DATA;
  const qtyBC   = lv.qty_bc       != null ? Number(lv.qty_bc)      : null;
  const qtyFAC  = lv.qty_facture  != null ? Number(lv.qty_facture) : null;
  const qtyBL   = lv.qty_bl       != null ? Number(lv.qty_bl)      : null;
  const pBC     = lv.prix_bc      != null ? Number(lv.prix_bc)     : null;
  const pFAC    = lv.prix_facture != null ? Number(lv.prix_facture) : null;
  const qtyMismatch   = qtyBC != null && qtyFAC != null && qtyBC !== qtyFAC;
  const priceMismatch = pBC   != null && pFAC   != null && Math.abs(pBC - pFAC) >= 0.015;
  const hasDetail     = lv.mismatch_fields?.length > 0 || lv.notes;

  return (
    <>
      <tr
        className={`border-l-4 ${cfg.row} ${cfg.rowBg} ${hasDetail ? "cursor-pointer hover:brightness-[0.98]" : ""}`}
        onClick={() => hasDetail && setExpanded(!expanded)}
      >
        <td className="px-3 py-2.5 align-top whitespace-nowrap">
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-xs font-semibold text-slate-700">{lv.ref_produit || "—"}</span>
            {lv.ref_produit_facture && lv.ref_produit_facture !== lv.ref_produit && (
              <span className="font-mono text-[10px] text-blue-500">{lv.ref_produit_facture}</span>
            )}
          </div>
        </td>
        <td className="px-3 py-2.5 align-top">
          <span className="text-xs text-slate-700 leading-snug block max-w-[200px]">{lv.designation || "—"}</span>
        </td>
        <td className="px-3 py-2.5 align-top">
          <div className="flex flex-col gap-0.5">
            {qtyBC  != null && <div className="flex items-center gap-1"><span className="text-[10px] text-slate-400 w-6">BC</span><span className={`font-mono text-xs ${qtyMismatch ? "text-red-600 font-semibold" : "text-slate-600"}`}>{fmtQty(qtyBC)}</span></div>}
            {qtyBL  != null && <div className="flex items-center gap-1"><span className="text-[10px] text-slate-400 w-6">BL</span><span className="font-mono text-xs text-slate-600">{fmtQty(qtyBL)}</span></div>}
            {qtyFAC != null && <div className="flex items-center gap-1"><span className="text-[10px] text-slate-400 w-6">FAC</span><span className={`font-mono text-xs ${qtyMismatch ? "text-red-600 font-semibold" : "text-slate-600"}`}>{fmtQty(qtyFAC)}</span></div>}
          </div>
        </td>
        <td className="px-3 py-2.5 align-top">
          <div className="flex flex-col gap-0.5">
            {pBC  != null && <div className="flex items-center gap-1"><span className="text-[10px] text-slate-400 w-6">BC</span><span className={`font-mono text-xs ${priceMismatch ? "text-red-600 font-semibold" : "text-slate-600"}`}>{fmtNum(pBC)}</span></div>}
            {pFAC != null && <div className="flex items-center gap-1"><span className="text-[10px] text-slate-400 w-6">FAC</span><span className={`font-mono text-xs ${priceMismatch ? "text-red-600 font-semibold" : "text-slate-600"}`}>{fmtNum(pFAC)}</span></div>}
          </div>
        </td>
        <td className="px-3 py-2.5 align-top">
          <span className="font-mono text-xs text-slate-500">{(lv.tva_bc ?? lv.tva_facture) != null ? `${lv.tva_bc ?? lv.tva_facture}%` : "—"}</span>
        </td>
        <td className="px-3 py-2.5 align-top"><ConfPill value={lv.confidence} /></td>
        <td className="px-3 py-2.5 align-top">
          <div className="flex items-center gap-1">
            <VerdictBadge verdict={lv.verdict} />
            {hasDetail && <span className="text-slate-300">{expanded ? <ChevronUp size={11}/> : <ChevronDown size={11}/>}</span>}
          </div>
        </td>
      </tr>
      {expanded && hasDetail && (
        <tr className={`border-l-4 ${cfg.row} bg-red-50/60`}>
          <td colSpan={7} className="px-4 py-2.5 border-b border-slate-100">
            <div className="flex items-start gap-3 flex-wrap">
              {lv.mismatch_fields?.length > 0 && (
                <>
                  <div className="flex items-center gap-1.5">
                    <AlertTriangle size={11} className="text-red-500 shrink-0" />
                    <span className="text-[11px] text-red-600 font-medium">Champs en écart :</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {lv.mismatch_fields.map((f) => (
                      <code key={f} className="text-[11px] bg-red-100 text-red-700 px-2 py-0.5 rounded font-mono">{formatMismatchField(f)}</code>
                    ))}
                  </div>
                </>
              )}
              {lv.notes && <span className="text-[11px] text-slate-500 italic">{lv.notes}</span>}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ─── Alias section ────────────────────────────────────────────────────────────
function AliasSection({ results, jobId, reviewerId, setSubmitError }) {
  const [aliasSaving, setAliasSaving] = useState({});
  const [aliasSaved,  setAliasSaved]  = useState({});

  const supplierName =
    results?.documents?.find((d) => d.doc_type === "FACTURE")?.supplier_name ||
    results?.documents?.find((d) => d.doc_type === "BL")?.supplier_name || null;

  const candidates = (results?.match_result?.line_verdicts || []).filter((line) => {
    const extRef = line.ref_produit_facture || line.ref_produit_bl;
    const intRef = line.ref_produit;
    const qtyOk  = line.qty_bc != null && (
      line.ref_produit_facture ? line.qty_facture != null : line.qty_bl != null
    ) && Number(line.qty_bc) === Number(line.ref_produit_facture ? line.qty_facture : line.qty_bl);
    const priceOk = line.ref_produit_facture && line.prix_bc != null && line.prix_facture != null
      && Math.abs(Number(line.prix_bc) - Number(line.prix_facture)) <= 0.100;
    return (
      extRef && intRef && extRef !== intRef &&
      ["LOW_CONFIDENCE", "PARTIAL_MATCH", "MATCH"].includes(line.verdict) &&
      (!line.mismatch_fields || line.mismatch_fields.length === 0) &&
      !line.reference_alias_applied &&
      (line.ref_produit_facture ? (qtyOk && priceOk) : qtyOk)
    );
  });

  if (candidates.length === 0) return null;

  const handleApprove = async (line) => {
    if (!reviewerId.trim()) {
      setSubmitError("Entrez votre nom avant d'approuver un alias.");
      return;
    }
    const extRef = line.ref_produit_facture || line.ref_produit_bl;
    const intRef = line.ref_produit;
    const key    = `${extRef}:${intRef}`;
    setAliasSaving(p => ({ ...p, [key]: true }));
    setSubmitError(null);
    try {
      await approveReferenceAlias(jobId, { reviewerId, externalRef: extRef, internalRef: intRef, supplierName });
      setAliasSaved(p => ({ ...p, [key]: true }));
    } catch (err) {
      setSubmitError(err.message);
    } finally {
      setAliasSaving(p => ({ ...p, [key]: false }));
    }
  };

  return (
    <div className="bg-white border border-blue-200 rounded-xl overflow-hidden shadow-sm">
      <div className="flex items-center gap-2 px-5 py-3.5 bg-blue-50 border-b border-blue-100">
        <BookOpen size={13} className="text-blue-500" />
        <span className="text-xs font-semibold text-blue-700 uppercase tracking-wide">Alias de références à mémoriser</span>
        <span className="ml-auto text-[10px] text-blue-400 font-mono bg-blue-100 px-2 py-0.5 rounded">{candidates.length}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-xs text-slate-400 uppercase tracking-wide">
              <th className="text-left py-2.5 px-4 font-semibold">Réf fournisseur</th>
              <th className="text-left py-2.5 px-4 font-semibold">Réf interne</th>
              <th className="text-left py-2.5 px-4 font-semibold">Désignation</th>
              <th className="text-right py-2.5 px-4 font-semibold">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {candidates.map((line) => {
              const extRef = line.ref_produit_facture || line.ref_produit_bl;
              const intRef = line.ref_produit;
              const key    = `${extRef}:${intRef}`;
              const saved  = aliasSaved[key];
              return (
                <tr key={key}>
                  <td className="py-3 px-4 font-mono text-xs text-slate-700 whitespace-nowrap">{extRef}</td>
                  <td className="py-3 px-4 font-mono text-xs text-slate-700 whitespace-nowrap">{intRef}</td>
                  <td className="py-3 px-4 text-xs text-slate-500 max-w-[280px] truncate">{line.designation || "—"}</td>
                  <td className="py-3 px-4 text-right">
                    <button
                      onClick={() => handleApprove(line)}
                      disabled={saved || aliasSaving[key]}
                      className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-blue-700 disabled:bg-gray-200 disabled:text-gray-400"
                    >
                      {aliasSaving[key] ? <Spinner size="sm" /> : <CheckCircle size={12} />}
                      {saved ? "Enregistré ✓" : "Approuver alias"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── Discrepancy summary ──────────────────────────────────────────────────────
function DiscrepancySection({ lineVerdicts }) {
  const missing  = lineVerdicts.filter(l => l.verdict === "MISSING");
  const extra    = lineVerdicts.filter(l => l.verdict === "EXTRA");
  const mismatch = lineVerdicts.filter(l => l.verdict === "MISMATCH");
  const partial  = lineVerdicts.filter(l => l.verdict === "PARTIAL_MATCH");
  const lowConf  = lineVerdicts.filter(l => l.verdict === "LOW_CONFIDENCE");

  if (!missing.length && !extra.length && !mismatch.length && !partial.length && !lowConf.length) {
    return (
      <div className="flex items-center gap-2.5 bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-3">
        <CheckCircle2 size={16} className="text-emerald-500 shrink-0" />
        <span className="text-sm text-emerald-700 font-medium">Aucun écart détecté — toutes les lignes concordent.</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {mismatch.length > 0 && (
        <div className="rounded-xl border border-red-200 bg-red-50/40 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-red-100">
            <XCircle size={13} className="text-red-500" />
            <span className="text-xs font-semibold text-red-600 uppercase tracking-wide">Écarts de prix / quantité ({mismatch.length})</span>
          </div>
          {mismatch.map((lv, i) => {
            const pBC = lv.prix_bc != null ? Number(lv.prix_bc) : null;
            const pFAC = lv.prix_facture != null ? Number(lv.prix_facture) : null;
            const diff = pBC != null && pFAC != null ? Math.abs(pBC - pFAC) : null;
            return (
              <div key={i} className={`flex items-start justify-between gap-4 px-4 py-3 text-xs ${i > 0 ? "border-t border-red-100" : ""}`}>
                <div>
                  <span className="font-mono font-semibold text-slate-700 mr-2">{lv.ref_produit}</span>
                  <span className="text-slate-500">{lv.designation}</span>
                </div>
                <div className="flex items-center gap-3 shrink-0 flex-wrap justify-end">
                  {lv.mismatch_fields?.includes("qty_bc_vs_facture") && (
                    <div className="flex items-center gap-2">
                      <span className="text-slate-500">Qté BC <span className="font-mono font-semibold text-slate-700">{fmtQty(lv.qty_bc)}</span></span>
                      <ArrowRight size={11} className="text-slate-300" />
                      <span className="text-slate-500">Qté FAC <span className="font-mono font-semibold text-red-600">{fmtQty(lv.qty_facture)}</span></span>
                      <span className="bg-red-100 text-red-700 rounded px-2 py-0.5 font-mono text-[11px]">Δ {Math.abs((lv.qty_bc ?? 0) - (lv.qty_facture ?? 0))} unités</span>
                    </div>
                  )}
                  {diff != null && diff > 0 && lv.mismatch_fields?.includes("prix_unitaire") && (
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-slate-700">{fmtNum(pBC)}</span>
                      <ArrowRight size={11} className="text-slate-300" />
                      <span className="font-mono text-red-600">{fmtNum(pFAC)}</span>
                      <span className="bg-red-100 text-red-700 rounded px-2 py-0.5 font-mono text-[11px]">Δ {fmtNum(diff)} DT</span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {partial.length > 0 && (
        <div className="rounded-xl border border-orange-200 bg-orange-50/40 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-orange-100">
            <Info size={13} className="text-orange-500" />
            <span className="text-xs font-semibold text-orange-600 uppercase tracking-wide">Livraisons partielles ({partial.length})</span>
          </div>
          {partial.map((lv, i) => (
            <div key={i} className={`flex items-start justify-between gap-4 px-4 py-3 text-xs ${i > 0 ? "border-t border-orange-100" : ""}`}>
              <div>
                <span className="font-mono font-semibold text-slate-700 mr-2">{lv.ref_produit}</span>
                <span className="text-slate-500">{lv.designation}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <span className="text-slate-500">BC <span className="font-mono font-semibold text-slate-700">{fmtQty(lv.qty_bc)}</span></span>
                <ArrowRight size={11} className="text-slate-300" />
                <span className="text-slate-500">FAC <span className="font-mono font-semibold text-orange-700">{fmtQty(lv.qty_facture)}</span></span>
                <span className="bg-orange-100 text-orange-700 rounded px-2 py-0.5 text-[11px] font-medium">Partiel</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {missing.length > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50/40 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-amber-100">
            <AlertTriangle size={13} className="text-amber-500" />
            <span className="text-xs font-semibold text-amber-600 uppercase tracking-wide">Articles commandés non facturés ({missing.length})</span>
          </div>
          {missing.map((lv, i) => (
            <div key={i} className={`flex items-start justify-between gap-4 px-4 py-3 text-xs ${i > 0 ? "border-t border-amber-100" : ""}`}>
              <div>
                <span className="font-mono font-semibold text-slate-700 mr-2">{lv.ref_produit}</span>
                <span className="text-slate-500">{lv.designation}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {lv.qty_bc != null && <span className="text-slate-500">Qté : <span className="font-mono font-semibold text-slate-700">{fmtQty(lv.qty_bc)}</span></span>}
                {lv.prix_bc != null && <span className="font-mono text-slate-600">{fmtNum(lv.prix_bc)} DT</span>}
                <span className="bg-amber-100 text-amber-700 rounded px-2 py-0.5 font-medium text-[11px]">Non facturé</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {extra.length > 0 && (
        <div className="rounded-xl border border-sky-200 bg-sky-50/40 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-sky-100">
            <Info size={13} className="text-sky-500" />
            <span className="text-xs font-semibold text-sky-600 uppercase tracking-wide">Articles supplémentaires non commandés ({extra.length})</span>
          </div>
          {extra.map((lv, i) => (
            <div key={i} className={`flex items-start justify-between gap-4 px-4 py-3 text-xs ${i > 0 ? "border-t border-sky-100" : ""}`}>
              <div>
                <span className="font-mono font-semibold text-slate-700 mr-2">{lv.ref_produit}</span>
                <span className="text-slate-500">{lv.designation}</span>
              </div>
              <span className="bg-sky-100 text-sky-700 rounded px-2 py-0.5 font-medium text-[11px] shrink-0">Hors BC</span>
            </div>
          ))}
        </div>
      )}

      {lowConf.length > 0 && (
        <div className="rounded-xl border border-violet-200 bg-violet-50/40 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-violet-100">
            <AlertTriangle size={13} className="text-violet-500" />
            <span className="text-xs font-semibold text-violet-600 uppercase tracking-wide">Lignes à faible confiance ({lowConf.length})</span>
          </div>
          {lowConf.map((lv, i) => (
            <div key={i} className={`flex items-start justify-between gap-4 px-4 py-3 text-xs ${i > 0 ? "border-t border-violet-100" : ""}`}>
              <div>
                <span className="font-mono font-semibold text-slate-700 mr-2">{lv.ref_produit}</span>
                <span className="text-slate-500">{lv.designation}</span>
              </div>
              <ConfPill value={lv.confidence} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main ReviewPage ──────────────────────────────────────────────────────────
export default function ReviewPage() {
  const { jobId }  = useParams();
  const navigate   = useNavigate();
  const { results, loading, error, refetch } = useJobResults(jobId);

  // Review decision state
  const [reviewerId,   setReviewerId]   = useState("");
  const [notes,        setNotes]        = useState("");
  const [submitting,   setSubmitting]   = useState(false);
  const [submitError,  setSubmitError]  = useState(null);
  const [submitted,    setSubmitted]    = useState(false);

  // Re-match state
  const [rematching,   setRematching]   = useState(false);
  const [rematchDone,  setRematchDone]  = useState(false);

  // Active section tab
  const [activeTab, setActiveTab] = useState("documents"); // documents | comparison | discrepancies

  const handleSubmit = async (approved) => {
    if (!reviewerId.trim()) {
      setSubmitError("Veuillez saisir votre nom ou identifiant.");
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      await submitReview(jobId, { reviewerId, approved, notes });
      setSubmitted(true);
      setTimeout(() => navigate(`/results/${jobId}`), 1800);
    } catch (err) {
      setSubmitError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRerunMatch = async () => {
    setRematching(true);
    setRematchDone(false);
    try {
      await rerunMatch(jobId);
      await refetch?.();
      setRematchDone(true);
      setTimeout(() => setRematchDone(false), 3000);
    } catch {
      // silent — refetch will still show latest state
    } finally {
      setRematching(false);
    }
  };

  if (loading) {
    return (
      <PageWrapper title="Chargement…">
        <div className="flex justify-center py-24"><Spinner size="lg" /></div>
      </PageWrapper>
    );
  }
  if (error) {
    return (
      <PageWrapper title="Erreur">
        <Alert variant="error">{error}</Alert>
      </PageWrapper>
    );
  }
  if (!results) return null;
  if (submitted) {
    return (
      <PageWrapper title="Révision soumise">
        <Alert variant="success" title="Décision enregistrée">
          Votre révision a été sauvegardée dans le journal d'audit. Redirection…
        </Alert>
      </PageWrapper>
    );
  }

  const { verdict, documents, match_result, status } = results;
  const lineVerdicts = match_result?.line_verdicts ?? [];
  const gv    = GLOBAL_VERDICT_CFG[verdict] ?? GLOBAL_VERDICT_CFG.REVIEW_REQUIRED;
  const GvIcon = gv.Icon;

  const countVerdict = (v) => lineVerdicts.filter(l => l.verdict === v).length;
  const tabCounts = {
    documents:     (documents?.length ?? 0),
    comparison:    lineVerdicts.length,
    discrepancies: countVerdict("MISMATCH") + countVerdict("MISSING") + countVerdict("EXTRA") + countVerdict("PARTIAL_MATCH") + countVerdict("LOW_CONFIDENCE"),
  };

  const TABS = [
    { key: "documents",     label: "Documents extraits",     icon: FileText },
    { key: "comparison",    label: "Comparaison complète",   icon: ClipboardList },
    { key: "discrepancies", label: "Écarts & alertes",       icon: AlertTriangle, warn: tabCounts.discrepancies > 0 },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      {/* ── Top bar ── */}
      <div className="sticky top-0 z-30 bg-white border-b border-slate-200 shadow-sm">
        <div className="max-w-[1600px] mx-auto px-4 py-3 flex items-center gap-3 flex-wrap">
          <button
            onClick={() => navigate(`/results/${jobId}`)}
            className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-700 font-medium transition-colors"
          >
            <ArrowLeft size={14} /> Résultats
          </button>
          <div className="h-4 w-px bg-slate-200" />
          <div className="flex items-center gap-2">
            <div className={`w-7 h-7 rounded-lg bg-gradient-to-br ${gv.gradient} flex items-center justify-center shrink-0`}>
              <GvIcon size={14} className="text-white" />
            </div>
            <div>
              <div className="text-sm font-semibold text-slate-800 leading-none">{gv.label}</div>
              <div className="text-[10px] text-slate-400 mt-0.5 font-mono">Job {jobId?.slice(0, 8)}…</div>
            </div>
          </div>
          <div className="flex items-center gap-2 ml-auto flex-wrap">
            {/* Stats pills */}
            {[
              { label: "Match",    val: match_result?.match_count   ?? 0, cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
              { label: "Mismatch", val: match_result?.mismatch_count ?? 0, cls: "bg-red-50 text-red-700 ring-red-200" },
              { label: "Missing",  val: match_result?.missing_count  ?? 0, cls: "bg-amber-50 text-amber-700 ring-amber-200" },
              { label: "Extra",    val: match_result?.extra_count    ?? 0, cls: "bg-sky-50 text-sky-700 ring-sky-200" },
            ].map(({ label, val, cls }) => (
              <span key={label} className={`text-xs font-semibold px-2.5 py-1 rounded-lg ring-1 ring-inset ${cls}`}>
                {val} {label}
              </span>
            ))}
            <button
              onClick={handleRerunMatch}
              disabled={rematching}
              className="flex items-center gap-1.5 text-xs border border-slate-200 rounded-lg px-3 py-1.5 text-slate-600 hover:bg-slate-50 font-medium transition-colors disabled:opacity-50"
              title="Relancer le rapprochement après corrections"
            >
              {rematching ? <Spinner size="sm" /> : <RefreshCw size={12} />}
              {rematchDone ? "Relancé ✓" : "Relancer rapprochement"}
            </button>
          </div>
        </div>
      </div>

      {/* ── Main layout: PDF left | content right ── */}
      <div className="max-w-[1600px] mx-auto px-4 py-5 flex gap-5 items-start">

        {/* Left — PDF viewer (sticky) */}
        <div className="hidden xl:block w-[420px] 2xl:w-[500px] shrink-0 sticky top-[61px]">
          <PdfViewer jobId={jobId} />
        </div>

        {/* Right — all review content */}
        <div className="flex-1 min-w-0 space-y-5">

          {/* Mobile PDF toggle */}
          <div className="xl:hidden">
            <PdfViewer jobId={jobId} />
          </div>

          {/* ── Section tabs ── */}
          <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
            <div className="flex border-b border-slate-100">
              {TABS.map(({ key, label, icon: Icon, warn }) => (
                <button
                  key={key}
                  onClick={() => setActiveTab(key)}
                  className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-3 text-xs font-semibold transition-colors border-b-2 ${
                    activeTab === key
                      ? "border-blue-500 text-blue-600 bg-blue-50/50"
                      : "border-transparent text-slate-500 hover:text-slate-700 hover:bg-slate-50"
                  }`}
                >
                  <Icon size={12} />
                  <span className="hidden sm:inline">{label}</span>
                  <span className={`text-[10px] font-mono rounded-full px-1.5 py-0.5 ${
                    warn ? "bg-red-100 text-red-600" : "bg-slate-100 text-slate-400"
                  }`}>
                    {tabCounts[key]}
                  </span>
                </button>
              ))}
            </div>

            <div className="p-4 space-y-4">

              {/* ── Tab: Documents ── */}
              {activeTab === "documents" && (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 text-[11px] text-slate-400 bg-slate-50 rounded-lg px-3 py-2">
                    <Edit3 size={11} className="text-slate-400 shrink-0" />
                    <span>Cliquez sur <strong className="text-slate-600">Modifier</strong> sur un document pour corriger les données extraites, puis sauvegardez et relancez le rapprochement.</span>
                  </div>
                  {(documents || []).map((doc, i) => (
                    <EditableDocCard key={doc.id ?? i} doc={doc} jobId={jobId} onSaved={() => {}} />
                  ))}
                  {(!documents || documents.length === 0) && (
                    <div className="text-center text-sm text-slate-400 py-8">Aucun document extrait.</div>
                  )}
                </div>
              )}

              {/* ── Tab: Full comparison ── */}
              {activeTab === "comparison" && (
                <div>
                  {lineVerdicts.length === 0 ? (
                    <div className="text-center text-sm text-slate-400 py-8">Aucune ligne de comparaison.</div>
                  ) : (
                    <div className="overflow-x-auto rounded-xl border border-slate-200">
                      <table className="w-full">
                        <thead>
                          <tr className="bg-slate-50 border-b border-slate-200 text-xs">
                            <th className="text-left px-3 py-2.5 text-slate-400 font-semibold whitespace-nowrap">Réf</th>
                            <th className="text-left px-3 py-2.5 text-slate-400 font-semibold">Désignation</th>
                            <th className="text-left px-3 py-2.5 text-slate-400 font-semibold whitespace-nowrap">Qté <span className="font-normal text-slate-300">(BC/FAC)</span></th>
                            <th className="text-left px-3 py-2.5 text-slate-400 font-semibold whitespace-nowrap">Prix UN <span className="font-normal text-slate-300">(BC/FAC)</span></th>
                            <th className="text-left px-3 py-2.5 text-slate-400 font-semibold">TVA</th>
                            <th className="text-left px-3 py-2.5 text-slate-400 font-semibold">Conf.</th>
                            <th className="text-left px-3 py-2.5 text-slate-400 font-semibold">Verdict</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-50">
                          {lineVerdicts.map((lv, i) => <CompareRow key={lv.ref_produit ?? i} lv={lv} />)}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}

              {/* ── Tab: Discrepancies ── */}
              {activeTab === "discrepancies" && (
                <DiscrepancySection lineVerdicts={lineVerdicts} />
              )}
            </div>
          </div>

          {/* ── Alias section ── */}
          <AliasSection
            results={results}
            jobId={jobId}
            reviewerId={reviewerId}
            setSubmitError={setSubmitError}
          />

          {/* ── Review decision form ── */}
          <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
            <div className="flex items-center gap-2 px-5 py-3.5 bg-slate-50 border-b border-slate-100">
              <Shield size={13} className="text-slate-500" />
              <span className="text-xs font-semibold text-slate-600 uppercase tracking-wide">Décision de révision</span>
            </div>
            <div className="p-5 space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5">
                  Votre nom / Identifiant réviseur <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  value={reviewerId}
                  onChange={e => setReviewerId(e.target.value)}
                  placeholder="ex: Ahmed Benali"
                  className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white"
                />
              </div>
              <div>
                <label className="block text-xs font-semibold text-slate-600 mb-1.5">
                  Notes (optionnel)
                </label>
                <textarea
                  value={notes}
                  onChange={e => setNotes(e.target.value)}
                  placeholder="Commentaires sur cette décision…"
                  rows={3}
                  className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white resize-none"
                />
              </div>

              {submitError && <Alert variant="error">{submitError}</Alert>}

              <div className="flex gap-3">
                <button
                  onClick={() => handleSubmit(true)}
                  disabled={submitting}
                  className="flex-1 flex items-center justify-center gap-2 bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-300 text-white font-semibold py-3 rounded-xl transition-colors text-sm"
                >
                  {submitting ? <Spinner size="sm" /> : <CheckCircle2 size={16} />}
                  Approuver
                </button>
                <button
                  onClick={() => handleSubmit(false)}
                  disabled={submitting}
                  className="flex-1 flex items-center justify-center gap-2 bg-red-600 hover:bg-red-700 disabled:bg-red-300 text-white font-semibold py-3 rounded-xl transition-colors text-sm"
                >
                  {submitting ? <Spinner size="sm" /> : <XCircle size={16} />}
                  Rejeter
                </button>
              </div>

              <p className="text-[11px] text-slate-400 text-center">
                Cette décision est permanente et sera enregistrée dans le journal d&apos;audit immuable.
              </p>
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
