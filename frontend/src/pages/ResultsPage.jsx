import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useJobResults } from "../hooks/useJobResults";
import { formatMismatchField } from "../utils/mismatchFields";
import PageWrapper from "../components/layout/PageWrapper";
import AuditTrail from "../components/results/AuditTrail";
import Spinner from "../components/ui/Spinner";
import Alert from "../components/ui/Alert";
import Modal from "../components/ui/Modal";
import {
  ClipboardList,
  FileText,
  Upload,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Info,
  Calendar,
  Building2,
  Layers,
  ChevronDown,
  ChevronUp,
  TrendingUp,
  ArrowRight,
  ScanSearch,
  ShieldCheck,
  Minus,
  FileSearch,
  Eye,
  CircleDot,
  Activity,
  Gauge,
  Target,
} from "lucide-react";

const LINE_VERDICT_CFG = {
  MATCH:          { label: "Match",          colors: "bg-emerald-50 text-emerald-700 ring-emerald-200", row: "border-l-emerald-400", rowBg: "" },
  MISMATCH:       { label: "Mismatch",       colors: "bg-red-50 text-red-700 ring-red-200",            row: "border-l-red-400",     rowBg: "bg-red-50/40" },
  MISSING:        { label: "Missing",        colors: "bg-amber-50 text-amber-700 ring-amber-200",      row: "border-l-amber-400",   rowBg: "bg-amber-50/30" },
  EXTRA:          { label: "Extra",          colors: "bg-sky-50 text-sky-700 ring-sky-200",            row: "border-l-sky-400",     rowBg: "bg-sky-50/20" },
  PARTIAL_DATA:   { label: "Partial Data",   colors: "bg-slate-100 text-slate-500 ring-slate-200",     row: "border-l-slate-300",   rowBg: "" },
  LOW_CONFIDENCE: { label: "Low Confidence", colors: "bg-violet-50 text-violet-700 ring-violet-200",   row: "border-l-violet-400",  rowBg: "bg-violet-50/20" },
  PARTIAL_MATCH:  { label: "Partial Match",  colors: "bg-orange-50 text-orange-700 ring-orange-200",   row: "border-l-orange-400",  rowBg: "bg-orange-50/20" },
};
const GLOBAL_VERDICT_CFG = {
  VALIDATED:       { label: "Validé",    bg: "from-emerald-600 to-emerald-700", Icon: CheckCircle2,  desc: "Toutes les lignes concordent. Facture approuvée." },
  REJECTED:        { label: "Rejeté",   bg: "from-red-600 to-red-700",         Icon: XCircle,       desc: "Écarts critiques détectés. Révision manuelle requise." },
  REVIEW_REQUIRED: { label: "À réviser", bg: "from-amber-500 to-amber-600",    Icon: AlertTriangle,  desc: "Certains éléments nécessitent une vérification humaine." },
};
const DOC_TYPE_CFG = {
  FACTURE: { border: "border-l-blue-400",   badge: "bg-blue-50 text-blue-700",     label: "Facture",          dot: "bg-blue-400" },
  BC:      { border: "border-l-violet-400", badge: "bg-violet-50 text-violet-700", label: "Bon de Commande",  dot: "bg-violet-400" },
  BL:      { border: "border-l-teal-400",   badge: "bg-teal-50 text-teal-700",     label: "Bon de Livraison", dot: "bg-teal-400" },
};
const AUDIT_FIELD_STATUS = {
  correct: { label: "Correct",  bg: "bg-emerald-50", text: "text-emerald-700", ring: "ring-emerald-200", dot: "bg-emerald-500" },
  wrong:   { label: "Erroné",   bg: "bg-red-50",     text: "text-red-700",     ring: "ring-red-200",     dot: "bg-red-500"     },
  missed:  { label: "Manqué",   bg: "bg-amber-50",   text: "text-amber-700",   ring: "ring-amber-200",   dot: "bg-amber-500"   },
  approx:  { label: "≈ Approx", bg: "bg-sky-50",     text: "text-sky-700",     ring: "ring-sky-200",     dot: "bg-sky-400"     },
};
const LINE_AUDIT_VERDICT = {
  correct:       { label: "Correct",        icon: CheckCircle2, cls: "text-emerald-600", bg: "bg-emerald-50",  border: "border-emerald-200" },
  price_wrong:   { label: "Prix erroné",    icon: XCircle,      cls: "text-red-600",     bg: "bg-red-50",      border: "border-red-200"     },
  ref_wrong:     { label: "Réf. incorrecte",icon: AlertTriangle,cls: "text-amber-600",   bg: "bg-amber-50",    border: "border-amber-200"   },
  missed:        { label: "Ligne manquée",  icon: Minus,        cls: "text-slate-500",   bg: "bg-slate-50",    border: "border-slate-200"   },
  price_rounded: { label: "Arrondi prix",   icon: AlertTriangle,cls: "text-orange-600",  bg: "bg-orange-50",   border: "border-orange-200"  },
  partial:       { label: "Partiel",        icon: CircleDot,    cls: "text-violet-600",  bg: "bg-violet-50",   border: "border-violet-200"  },
};

const fmtNum = (v, dec = 3) =>
  v != null ? Number(v).toLocaleString("fr-TN", { minimumFractionDigits: dec, maximumFractionDigits: dec }) : null;
const fmtQty = (v) =>
  v != null ? Number(v).toLocaleString("fr-TN", { maximumFractionDigits: 0 }) : null;

const pctValue = (value) => {
  const n = Number(value);
  if (!Number.isFinite(n)) return null;
  return Math.round(n <= 1 ? n * 100 : n);
};

const averagePct = (values) => {
  const valid = values.filter((v) => v != null && Number.isFinite(Number(v)));
  if (!valid.length) return null;
  return Math.round(valid.reduce((a, b) => a + Number(b), 0) / valid.length);
};

const OCR_SOURCE_LABELS = {
  gemini: "Gemini",
  tesseract: "Tesseract",
  native: "Texte PDF",
};

function computeQualityMetrics(documents, match_result, auditTrail) {
  const byType = {};
  (documents ?? []).forEach((doc) => {
    if (!byType[doc.doc_type]) byType[doc.doc_type] = [];
    byType[doc.doc_type].push(doc);
  });

  const auditEvents = auditTrail?.audit_trail ?? [];
  const ocrByPage = new Map();
  const classifiedByPage = new Map();
  auditEvents.forEach((entry) => {
    const page = Number(entry?.data?.page_number);
    if (!Number.isFinite(page)) return;
    if (entry.event_type === "PAGE_OCR_COMPLETED") ocrByPage.set(page, entry.data);
    if (entry.event_type === "PAGE_CLASSIFIED") classifiedByPage.set(page, entry.data);
  });

  function docClassification(type) {
    const scores = (byType[type] ?? [])
      .map((doc) => pctValue(doc.classification_confidence));
    return averagePct(scores);
  }

  function docOcr(type) {
    const scores = [];
    const sources = new Set();
    (byType[type] ?? []).forEach((doc) => {
      (doc.pages ?? []).forEach((pageNumber) => {
        const page = Number(pageNumber);
        const ocrData = ocrByPage.get(page);
        const classData = classifiedByPage.get(page);
        const source = ocrData?.selected_source ?? classData?.ocr_source;
        if (!source) return;

        sources.add(OCR_SOURCE_LABELS[source] ?? source);
        if (source === "gemini" || source === "native") {
          scores.push(100);
        } else {
          scores.push(pctValue(ocrData?.tesseract_confidence ?? classData?.ocr_confidence));
        }
      });
    });

    return {
      pct: averagePct(scores),
      source: sources.size ? Array.from(sources).join(" + ") : null,
    };
  }

  const lineVerdicts = match_result?.line_verdicts ?? [];
  const fromRows = lineVerdicts.length > 0;
  const count = (verdict) => lineVerdicts.filter((line) => line.verdict === verdict).length;

  const matches = fromRows ? count("MATCH") : (match_result?.match_count ?? match_result?.matches ?? 0);
  const mismatches = fromRows ? count("MISMATCH") : (match_result?.mismatch_count ?? match_result?.mismatches ?? 0);
  const missing = fromRows ? count("MISSING") : (match_result?.missing_count ?? match_result?.missing ?? 0);
  const extra = fromRows ? count("EXTRA") : (match_result?.extra_count ?? match_result?.extra ?? 0);
  const review = fromRows
    ? lineVerdicts.filter((line) => ["LOW_CONFIDENCE", "PARTIAL_DATA", "PARTIAL_MATCH"].includes(line.verdict)).length
    : (match_result?.low_confidence_count ?? 0);

  const validatedTotal = matches + mismatches + extra + review;
  const orderedTotal = matches + mismatches + missing + review;
  const total = match_result?.total_lines ?? (validatedTotal + missing);
  const validatedPct = validatedTotal > 0 ? Math.round((matches / validatedTotal) * 100) : null;
  const coveragePct = orderedTotal > 0 ? Math.round((matches / orderedTotal) * 100) : null;
  const overallPct =
    validatedPct == null ? coveragePct
    : coveragePct == null ? validatedPct
    : Math.min(validatedPct, coveragePct);
  const factureOcr = docOcr("FACTURE");
  const bcOcr = docOcr("BC");
  const blOcr = docOcr("BL");

  return {
    validated:         validatedPct,
    validatedFrac:     validatedTotal > 0 ? `${matches}/${validatedTotal}` : null,
    coverage:          coveragePct,
    coverageFrac:      orderedTotal > 0 ? `${matches}/${orderedTotal}` : null,
    overall:           overallPct,
    missing,
    mismatches,
    extra,
    review,
    total,
    factureOcr:        factureOcr.pct,
    factureOcrSource:  factureOcr.source,
    bcOcr:             bcOcr.pct,
    bcOcrSource:       bcOcr.source,
    blOcr:             blOcr.pct,
    blOcrSource:       blOcr.source,
    factureClass:      docClassification("FACTURE"),
    bcClass:           docClassification("BC"),
    blClass:           docClassification("BL"),
  };
}


function QualityBar({ label, pct, frac, target = 85, sublabel }) {
  if (pct == null || Number.isNaN(Number(pct))) return null;

  const color =
    pct >= 85 ? { bar: "bg-emerald-500", text: "text-emerald-700", bg: "bg-emerald-50", ring: "ring-emerald-200" }
    : pct >= 65 ? { bar: "bg-amber-400",   text: "text-amber-700",   bg: "bg-amber-50",   ring: "ring-amber-200"   }
    :             { bar: "bg-red-500",      text: "text-red-700",     bg: "bg-red-50",     ring: "ring-red-200"     };

  const gap = target - pct;

  return (
    <div className="flex items-center gap-4 py-2.5 border-b border-slate-50 last:border-none">
      {/* Label */}
      <div className="w-44 shrink-0">
        <div className="text-xs font-semibold text-slate-700">{label}</div>
        {sublabel && <div className="text-[10px] text-slate-400 mt-0.5">{sublabel}</div>}
      </div>

      {/* Bar track */}
      <div className="flex-1 min-w-0">
        <div className="relative h-2 bg-slate-100 rounded-full overflow-hidden">
          {/* Target marker */}
          <div
            className="absolute top-0 bottom-0 w-px bg-slate-300"
            style={{ left: `${target}%` }}
            title={`Cible : ${target}%`}
          />
          <div
            className={`h-full rounded-full transition-all duration-700 ${color.bar}`}
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        </div>
        {/* Gap note */}
        {gap > 0 && (
          <div className="text-[10px] text-slate-400 mt-0.5">
            {gap} pts sous la cible ({target}%)
          </div>
        )}
      </div>

      {/* Score pill */}
      <div className={`shrink-0 flex items-center gap-1.5 rounded-lg px-2.5 py-1 ring-1 ring-inset ${color.bg} ${color.ring}`}>
        <span className={`text-sm font-bold tabular-nums ${color.text}`}>{pct}%</span>
        {frac && <span className="text-[10px] text-slate-400 font-mono">{frac}</span>}
      </div>
    </div>
  );
}

function QualityScoreSection({ documents, match_result, auditTrail }) {
  const m = computeQualityMetrics(documents, match_result, auditTrail);
  const [open, setOpen] = useState(true);
  const overallColor =
    (m.overall ?? 0) >= 85 ? "text-emerald-600"
    : (m.overall ?? 0) >= 65 ? "text-amber-600"
    : "text-red-600";
  const qualityNote =
    m.mismatches === 0 && m.extra === 0 && m.review === 0
      ? (
        m.missing > 0
          ? `Toutes les lignes facturees sont validees. ${m.missing} article${m.missing > 1 ? "s" : ""} commande${m.missing > 1 ? "s" : ""} non facture${m.missing > 1 ? "s" : ""}.`
          : "Toutes les lignes controlees sont validees."
      )
      : "Des ecarts ou lignes incertaines restent a traiter.";

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-3.5 bg-slate-50/70 border-b border-slate-100 hover:bg-slate-100/70 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-lg bg-slate-100 flex items-center justify-center">
            <Gauge size={14} className="text-slate-500" />
          </div>
          <div className="text-left">
            <div className="text-xs font-semibold text-slate-700">Qualite metier du controle</div>
            <div className="text-[10px] text-slate-400 mt-0.5">Exactitude validee + signaux OCR</div>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {m.overall !== null && (
            <span className={`text-lg font-bold tabular-nums ${overallColor}`}>
              {m.overall}%
            </span>
          )}
          {open ? <ChevronUp size={13} className="text-slate-400" /> : <ChevronDown size={13} className="text-slate-400" />}
        </div>
      </button>

      {open && (
        <div className="px-5 py-1">
          {/* Bars */}
          {m.validated !== null && (
            <QualityBar
              label="Lignes facturees validees"
              sublabel="hors articles non factures"
              pct={m.validated}
              frac={m.validatedFrac}
              target={85}
            />
          )}
          {m.coverage !== null && (
            <QualityBar
              label="Couverture commande"
              sublabel="part des lignes BC retrouvees en facture"
              pct={m.coverage}
              frac={m.coverageFrac}
              target={85}
            />
          )}
          {m.factureOcr !== null && (
            <QualityBar
              label="Lecture OCR Facture"
              sublabel="source texte utilisee"
              pct={m.factureOcr}
              frac={m.factureOcrSource}
              target={90}
            />
          )}
          {m.factureClass !== null && (
            <QualityBar
              label="Classification Facture"
              sublabel="type de document detecte"
              pct={m.factureClass}
              target={90}
            />
          )}
          {m.bcOcr !== null && (
            <QualityBar
              label="Lecture OCR BC"
              sublabel="source texte utilisee"
              pct={m.bcOcr}
              frac={m.bcOcrSource}
              target={90}
            />
          )}
          {m.bcClass !== null && (
            <QualityBar
              label="Classification BC"
              sublabel="type de document detecte"
              pct={m.bcClass}
              target={90}
            />
          )}
          {m.blOcr !== null && (
            <QualityBar
              label="Lecture OCR BL"
              sublabel="source texte utilisee"
              pct={m.blOcr}
              frac={m.blOcrSource}
              target={90}
            />
          )}
          {m.blClass !== null && (
            <QualityBar
              label="Classification BL"
              sublabel="type de document detecte"
              pct={m.blClass}
              target={90}
            />
          )}
          {/* Business note */}
          <div className="flex items-start gap-2.5 mt-3 mb-3 rounded-lg bg-emerald-50 border border-emerald-100 px-3.5 py-2.5">
            <Target size={13} className="text-emerald-500 mt-0.5 shrink-0" />
            <div>
              <span className="text-[11px] font-semibold text-emerald-700">Lecture du score : </span>
              <span className="text-[11px] text-emerald-600">{qualityNote}</span>
            </div>
          </div>

          {/* Legend */}
          <div className="flex items-center gap-3 pb-3 flex-wrap">
            <span className="text-[10px] text-slate-400 font-medium uppercase tracking-wide">Legende :</span>
            {[
              { cls: "bg-emerald-500", label: ">= 85% - Bon" },
              { cls: "bg-amber-400",   label: "65-84% - A ameliorer" },
              { cls: "bg-red-500",     label: "< 65% - Critique" },
            ].map(({ cls, label }) => (
              <span key={label} className="flex items-center gap-1 text-[10px] text-slate-500">
                <span className={`w-2 h-2 rounded-full ${cls}`} />
                {label}
              </span>
            ))}
            <span className="flex items-center gap-1 text-[10px] text-slate-400">
              <span className="inline-block w-px h-3 bg-slate-300 mx-0.5" />
              barre verticale = cible de la ligne
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
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
  const pct = Math.round(Number(value) * 100);
  const cls =
    pct >= 85 ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
    : pct >= 65 ? "bg-amber-50 text-amber-700 ring-amber-200"
    :             "bg-red-50 text-red-700 ring-red-200";
  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium ring-1 ring-inset ${cls}`}>
      {pct}%
    </span>
  );
}

function DocField({ icon: Icon, label, value, mono = false, className = "" }) {
  return (
    <div className="flex items-start gap-2 min-w-0">
      {Icon && <Icon size={12} className="text-slate-400 mt-0.5 shrink-0" />}
      <div className="min-w-0">
        <span className="text-[10px] text-slate-400 uppercase tracking-wide block">{label}</span>
        <span className={`text-xs text-slate-700 font-medium break-words ${mono ? "font-mono" : ""} ${className}`}>
          {value ?? "—"}
        </span>
      </div>
    </div>
  );
}

function DocCard({ doc }) {
  const [open, setOpen] = useState(false);
  if (!doc) return null;
  const tc = DOC_TYPE_CFG[doc.doc_type] ?? DOC_TYPE_CFG.BL;

  return (
    <div className={`bg-white rounded-xl border border-slate-200 border-l-4 ${tc.border} shadow-sm flex flex-col overflow-hidden`}>
      <div className="px-4 pt-4 pb-3">
        <div className="flex items-center gap-2 mb-3">
          <span className={`text-[11px] font-semibold px-2 py-0.5 rounded ${tc.badge}`}>{tc.label}</span>
          <span className="font-mono text-sm font-semibold text-slate-800 truncate">{doc.ref_document || "—"}</span>
        </div>
        <div className="grid grid-cols-2 gap-x-4 gap-y-2.5">
          <DocField icon={Calendar}  label="Date"        value={doc.document_date} />
          <DocField icon={Building2} label="Fournisseur" value={doc.supplier_name} />
          <DocField icon={Layers}    label="Lignes"       value={doc.lines?.length ?? 0} />
          <div className="flex items-start gap-2">
            <TrendingUp size={12} className="text-slate-400 mt-0.5 shrink-0" />
            <div>
              <span className="text-[10px] text-slate-400 uppercase tracking-wide block">Extraction</span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <ConfPill value={doc.extraction_confidence} />
                {doc.extraction_source_tier && (
                  <span className="text-[10px] text-slate-400">{doc.extraction_source_tier}</span>
                )}
              </div>
            </div>
          </div>
        </div>
        {Object.entries(doc.field_confidence_map || {}).filter(([, v]) => Number(v) < 0.7).length > 0 && (
          <div className="mt-2.5 flex flex-wrap gap-1">
            {Object.entries(doc.field_confidence_map || {}).filter(([, v]) => Number(v) < 0.7).map(([f]) => (
              <span key={f} className="inline-flex items-center gap-1 text-[10px] bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200 px-1.5 py-0.5 rounded font-mono">
                <AlertTriangle size={9} /> {f}
              </span>
            ))}
          </div>
        )}
      </div>

      {(doc.total_ht != null || doc.total_ttc != null) && (
        <div className="border-t border-slate-100 px-4 py-2.5 flex justify-between gap-4 bg-slate-50/60">
          {doc.total_ht != null && (
            <div>
              <div className="text-[10px] text-slate-400 uppercase tracking-wide">Total HT</div>
              <div className="font-mono text-sm font-semibold text-slate-800">
                {fmtNum(doc.total_ht, 2)} <span className="text-xs text-slate-400 font-sans">DT</span>
              </div>
            </div>
          )}
          {doc.total_ttc != null && (
            <div className="text-right">
              <div className="text-[10px] text-slate-400 uppercase tracking-wide">Total TTC</div>
              <div className="font-mono text-sm font-semibold text-slate-900">
                {fmtNum(doc.total_ttc, 2)} <span className="text-xs text-slate-400 font-sans">DT</span>
              </div>
            </div>
          )}
        </div>
      )}

      {doc.lines?.length > 0 && (
        <>
          <button
            onClick={() => setOpen(!open)}
            className="flex items-center justify-between px-4 py-2 bg-slate-50 border-t border-slate-100 text-[11px] text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition-colors"
          >
            <span>{open ? "Masquer" : "Voir"} les {doc.lines.length} lignes extraites</span>
            {open ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
          {open && (
            <div className="border-t border-slate-100 overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-100">
                    <th className="text-left px-3 py-2 text-slate-400 font-medium whitespace-nowrap">Réf</th>
                    <th className="text-left px-3 py-2 text-slate-400 font-medium">Désignation</th>
                    <th className="text-right px-3 py-2 text-slate-400 font-medium">Qté</th>
                    <th className="text-right px-3 py-2 text-slate-400 font-medium whitespace-nowrap">Prix UN HT</th>
                    <th className="text-right px-3 py-2 text-slate-400 font-medium">TVA</th>
                  </tr>
                </thead>
                <tbody>
                  {doc.lines.map((line, i) => (
                    <tr key={i} className="border-b border-slate-50 hover:bg-slate-50/60 last:border-none">
                      <td className="px-3 py-1.5 font-mono text-slate-600 whitespace-nowrap align-top">{line.ref_produit || "—"}</td>
                      <td className="px-3 py-1.5 text-slate-600 leading-snug align-top">{line.designation || "—"}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-slate-700 align-top">{line.qty != null ? Number(line.qty) : "—"}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-slate-700 align-top">{fmtNum(line.prix_unitaire) ?? "—"}</td>
                      <td className="px-3 py-1.5 text-right font-mono text-slate-400 align-top">{line.tva_rate != null ? `${line.tva_rate}%` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
function CompareRow({ lv }) {
  const [expanded, setExpanded] = useState(false);
  const cfg = LINE_VERDICT_CFG[lv.verdict] ?? LINE_VERDICT_CFG.PARTIAL_DATA;

  const priceBC  = lv.prix_bc      != null ? Number(lv.prix_bc)      : null;
  const priceFAC = lv.prix_facture != null ? Number(lv.prix_facture)  : null;
  const qtyBC    = lv.qty_bc       != null ? Number(lv.qty_bc)        : null;
  const qtyFAC   = lv.qty_facture  != null ? Number(lv.qty_facture)   : null;
  const qtyBL    = lv.qty_bl       != null ? Number(lv.qty_bl)        : null;

  const priceMatch    = priceBC != null && priceFAC != null && Math.abs(priceBC - priceFAC) < 0.015;
  const priceMismatch = priceBC != null && priceFAC != null && !priceMatch;
  const qtyMismatch   = qtyBC != null && qtyFAC != null && qtyBC !== qtyFAC;

  const hasMismatchDetail = lv.mismatch_fields?.length > 0;

  return (
    <>
      <tr
        className={`border-l-4 ${cfg.row} ${cfg.rowBg} transition-colors ${hasMismatchDetail ? "cursor-pointer hover:brightness-[0.98]" : ""}`}
        onClick={() => hasMismatchDetail && setExpanded(!expanded)}
        title={hasMismatchDetail ? "Cliquer pour voir les détails" : undefined}
      >
        {/* ── Ref: now correctly reads lv.line_ref (mapped from ref_produit) ── */}
        <td className="px-3 py-2.5 align-top whitespace-nowrap">
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-xs font-semibold text-slate-700">
              {lv.ref_produit || "—"}
            </span>
            {lv.line_ref_facture && lv.line_ref_facture !== lv.ref_produit && (
              <span className="font-mono text-[10px] text-blue-500">{lv.line_ref_facture}</span>
            )}
          </div>
        </td>

        <td className="px-3 py-2.5 align-top">
          <span className="text-xs text-slate-700 leading-snug block max-w-[240px]">{lv.designation || "—"}</span>
        </td>

        <td className="px-3 py-2.5 align-top">
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-slate-400 w-6 font-medium shrink-0">BC</span>
              <span className={`font-mono text-xs ${qtyMismatch ? "text-red-600 font-semibold" : "text-slate-600"}`}>
                {fmtQty(qtyBC) ?? <span className="text-slate-300">—</span>}
              </span>
            </div>
            {qtyBL != null && (
              <div className="flex items-center gap-1.5">
                <span className="text-[10px] text-slate-400 w-6 font-medium shrink-0">BL</span>
                <span className="font-mono text-xs text-slate-600">{fmtQty(qtyBL)}</span>
              </div>
            )}
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-slate-400 w-6 font-medium shrink-0">FAC</span>
              <span className={`font-mono text-xs ${qtyMismatch ? "text-red-600 font-semibold" : qtyFAC == null ? "text-slate-300" : "text-slate-600"}`}>
                {fmtQty(qtyFAC) ?? "—"}
              </span>
            </div>
          </div>
        </td>

        <td className="px-3 py-2.5 align-top">
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-slate-400 w-6 font-medium shrink-0">BC</span>
              <span className={`font-mono text-xs ${priceMismatch ? "text-red-600 font-semibold" : "text-slate-600"}`}>
                {fmtNum(lv.prix_bc) ?? <span className="text-slate-300">—</span>}
              </span>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-[10px] text-slate-400 w-6 font-medium shrink-0">FAC</span>
              <span className={`font-mono text-xs ${priceMismatch ? "text-red-600 font-semibold" : priceFAC == null ? "text-slate-300" : "text-slate-600"}`}>
                {fmtNum(lv.prix_facture) ?? "—"}
              </span>
            </div>
          </div>
        </td>

        <td className="px-3 py-2.5 align-top">
          <span className="font-mono text-xs text-slate-500">
            {(lv.tva_bc ?? lv.tva_facture) != null ? `${lv.tva_bc ?? lv.tva_facture}%` : "—"}
          </span>
        </td>
        <td className="px-3 py-2.5 align-top"><ConfPill value={lv.confidence} /></td>
        <td className="px-3 py-2.5 align-top">
          <div className="flex items-center gap-1.5">
            <VerdictBadge verdict={lv.verdict} />
            {hasMismatchDetail && (
              <span className="text-slate-300">{expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}</span>
            )}
          </div>
        </td>
      </tr>

      {expanded && hasMismatchDetail && (
        <tr className={`border-l-4 ${cfg.row} bg-red-50/60`}>
          <td colSpan={7} className="px-4 py-2.5 border-b border-slate-100">
            <div className="flex items-start gap-3 flex-wrap">
              <div className="flex items-center gap-1.5">
                <AlertTriangle size={11} className="text-red-500 shrink-0" />
                <span className="text-[11px] text-red-600 font-medium">Champs en écart :</span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {lv.mismatch_fields.map((f) => (
                  <code key={f} className="text-[11px] bg-red-100 text-red-700 px-2 py-0.5 rounded font-mono">{formatMismatchField(f)}</code>
                ))}
              </div>
              {priceMismatch && priceBC != null && priceFAC != null && (
                <span className="text-[11px] text-red-500">Écart prix : {fmtNum(Math.abs(priceBC - priceFAC))} DT</span>
              )}
              {lv.notes && (
                <span className="text-[11px] text-slate-500 italic">{lv.notes}</span>
              )}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function BannerStat({ value, label }) {
  return (
    <div className="bg-white/15 backdrop-blur-sm rounded-xl px-4 py-3 text-center min-w-[80px]">
      <div className="text-2xl font-semibold tabular-nums text-white leading-none">{value ?? 0}</div>
      <div className="text-[11px] text-white/70 mt-1 font-medium">{label}</div>
    </div>
  );
}
function AuditStatusPill({ status }) {
  const cfg = AUDIT_FIELD_STATUS[status] ?? AUDIT_FIELD_STATUS.approx;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${cfg.bg} ${cfg.text} ${cfg.ring}`}>
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
      {cfg.label}
    </span>
  );
}

function AuditScoreCard({ value, label, appValue, variant = "default" }) {
  const variants = {
    default: { card: "bg-white border-slate-200",        num: "text-slate-800",   sub: "text-slate-400"   },
    success: { card: "bg-emerald-50 border-emerald-200", num: "text-emerald-700", sub: "text-emerald-500" },
    danger:  { card: "bg-red-50 border-red-200",         num: "text-red-700",     sub: "text-red-400"     },
    warning: { card: "bg-amber-50 border-amber-200",     num: "text-amber-700",   sub: "text-amber-500"   },
  };
  const v = variants[variant] ?? variants.default;
  return (
    <div className={`rounded-xl border px-4 py-3 flex flex-col gap-1 ${v.card}`}>
      <div className={`text-2xl font-bold tabular-nums ${v.num}`}>{value}</div>
      <div className="text-[11px] font-semibold text-slate-600 leading-tight">{label}</div>
      {appValue != null && (
        <div className={`text-[10px] ${v.sub} mt-0.5`}>App : <span className="font-mono font-semibold">{appValue}</span></div>
      )}
    </div>
  );
}

function PdfAuditSection({ audit }) {
  const [lineOpen, setLineOpen]     = useState(true);
  const [headerOpen, setHeaderOpen] = useState(true);
  if (!audit) return null;

  const overallCfg = {
    PARTIALLY_WRONG: { label: "Partiellement incorrect", bg: "bg-amber-500",   icon: AlertTriangle, desc: "Le verdict final est accidentellement correct, mais pour de mauvaises raisons." },
    CORRECT:         { label: "Application correcte",    bg: "bg-emerald-600", icon: CheckCircle2,  desc: "L'extraction et la comparaison correspondent aux données réelles du PDF." },
    WRONG:           { label: "Application incorrecte",  bg: "bg-red-600",     icon: XCircle,       desc: "Des erreurs d'extraction significatives ont faussé les résultats." },
  };
  const ov = overallCfg[audit.overall_verdict] ?? overallCfg.PARTIALLY_WRONG;
  const OvIcon = ov.icon;
  const ss = audit.score_summary ?? {};

  return (
    <section className="space-y-4">
      <div className="rounded-2xl overflow-hidden border border-slate-200 shadow-sm">
        <div className={`${ov.bg} px-5 py-4 flex items-center gap-3`}>
          <div className="w-9 h-9 rounded-xl bg-white/20 flex items-center justify-center shrink-0">
            <OvIcon size={18} className="text-white" />
          </div>
          <div>
            <div className="text-white font-semibold text-base leading-tight">{ov.label}</div>
            <div className="text-white/70 text-xs mt-0.5">{ov.desc}</div>
          </div>
        </div>

        {ss && (
          <div className="bg-white px-5 py-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
            <AuditScoreCard value={ss.true_matches?.real ?? "—"}    label="Vrais Matchs"    appValue={ss.true_matches?.app}    variant={ss.true_matches?.real !== ss.true_matches?.app ? "warning" : "success"} />
            <AuditScoreCard value={ss.true_mismatches?.real ?? "—"} label="Vrais Mismatches" appValue={ss.true_mismatches?.app}  variant={ss.true_mismatches?.real !== ss.true_mismatches?.app ? "warning" : "default"} />
            <AuditScoreCard value={ss.missing?.real ?? "—"}         label="Lignes manquées"  appValue={ss.missing?.app}         variant={(ss.missing?.real ?? 0) > 0 ? "danger" : "default"} />
            <AuditScoreCard value={ss.true_extras?.real ?? "—"}     label="Vrais Extras"     appValue={ss.true_extras?.app}     variant="default" />
          </div>
        )}

        {audit.overall_note && (
          <div className="border-t border-slate-100 px-5 py-3 bg-slate-50/50 flex items-start gap-2">
            <Info size={13} className="text-slate-400 mt-0.5 shrink-0" />
            <p className="text-xs text-slate-500 leading-relaxed">{audit.overall_note}</p>
          </div>
        )}
      </div>

      {/* Header fields */}
      {audit.header_fields?.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <button onClick={() => setHeaderOpen(!headerOpen)} className="w-full flex items-center justify-between px-5 py-3.5 border-b border-slate-100 bg-slate-50/70 hover:bg-slate-100/70 transition-colors">
            <div className="flex items-center gap-2">
              <FileSearch size={13} className="text-slate-500" />
              <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Métadonnées — PDF vs Application</span>
            </div>
            {headerOpen ? <ChevronUp size={13} className="text-slate-400" /> : <ChevronDown size={13} className="text-slate-400" />}
          </button>
          {headerOpen && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-100">
                    <th className="text-left px-4 py-2.5 text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Champ</th>
                    <th className="text-left px-4 py-2.5 text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Valeur réelle (PDF)</th>
                    <th className="text-left px-4 py-2.5 text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Valeur extraite (App)</th>
                    <th className="text-left px-4 py-2.5 text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Statut</th>
                    <th className="text-left px-4 py-2.5 text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Note</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {audit.header_fields.map((hf, i) => {
                    const isWrong  = hf.status === "wrong";
                    const isMissed = hf.status === "missed";
                    return (
                      <tr key={i} className={`transition-colors ${isWrong ? "bg-red-50/50" : isMissed ? "bg-amber-50/40" : "hover:bg-slate-50/60"}`}>
                        <td className="px-4 py-2.5 font-mono text-slate-600 font-medium align-top whitespace-nowrap">{hf.field}</td>
                        <td className="px-4 py-2.5 align-top">
                          <span className="font-mono text-emerald-700 font-semibold bg-emerald-50 px-1.5 py-0.5 rounded text-[11px]">{hf.actual_value ?? "—"}</span>
                        </td>
                        <td className="px-4 py-2.5 align-top">
                          <span className={`font-mono font-semibold px-1.5 py-0.5 rounded text-[11px] ${isWrong ? "bg-red-100 text-red-700" : isMissed ? "bg-amber-100 text-amber-700" : "bg-slate-100 text-slate-600"}`}>
                            {hf.app_value ?? <span className="italic font-sans font-normal text-slate-400">non extrait</span>}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 align-top whitespace-nowrap"><AuditStatusPill status={hf.status} /></td>
                        <td className="px-4 py-2.5 align-top">{hf.note ? <span className="text-[11px] text-slate-500 leading-snug">{hf.note}</span> : <span className="text-slate-300">—</span>}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Line audit */}
      {audit.line_audit?.length > 0 && (
        <div className="bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden">
          <button onClick={() => setLineOpen(!lineOpen)} className="w-full flex items-center justify-between px-5 py-3.5 border-b border-slate-100 bg-slate-50/70 hover:bg-slate-100/70 transition-colors">
            <div className="flex items-center gap-2">
              <Eye size={13} className="text-slate-500" />
              <span className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Lignes facture — PDF vs Application</span>
              <span className="text-[10px] text-slate-400 font-mono">({audit.line_audit.length})</span>
            </div>
            {lineOpen ? <ChevronUp size={13} className="text-slate-400" /> : <ChevronDown size={13} className="text-slate-400" />}
          </button>
          {lineOpen && (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-100">
                    <th className="text-left px-3 py-2.5 text-[10px] text-slate-400 font-semibold uppercase tracking-wide whitespace-nowrap">
                      <span className="inline-flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />Réf réelle (PDF)</span>
                    </th>
                    <th className="text-left px-3 py-2.5 text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Désignation réelle</th>
                    <th className="text-right px-3 py-2.5 text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Qté</th>
                    <th className="text-right px-3 py-2.5 text-[10px] text-emerald-600 font-semibold uppercase tracking-wide whitespace-nowrap">Prix réel HT</th>
                    <th className="px-1" />
                    <th className="text-left px-3 py-2.5 text-[10px] text-slate-400 font-semibold uppercase tracking-wide whitespace-nowrap">
                      <span className="inline-flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-blue-400" />Réf App</span>
                    </th>
                    <th className="text-right px-3 py-2.5 text-[10px] text-blue-600 font-semibold uppercase tracking-wide whitespace-nowrap">Prix App</th>
                    <th className="text-left px-3 py-2.5 text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Verdict</th>
                    <th className="text-left px-3 py-2.5 text-[10px] text-slate-400 font-semibold uppercase tracking-wide">Note</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-50">
                  {audit.line_audit.map((la, i) => {
                    const vc = LINE_AUDIT_VERDICT[la.verdict] ?? LINE_AUDIT_VERDICT.partial;
                    const VcIcon = vc.icon;
                    const priceReal = la.actual_price != null ? Number(la.actual_price) : null;
                    const priceApp  = la.app_price    != null ? Number(la.app_price)    : null;
                    const priceDiff = priceReal != null && priceApp != null ? Math.abs(priceReal - priceApp) : null;
                    const hasPriceDiff = priceDiff != null && priceDiff >= 0.001;
                    const refMismatch = la.app_ref && la.actual_ref && la.app_ref !== la.actual_ref;
                    return (
                      <tr key={i} className={`border-l-4 transition-colors ${
                        la.verdict === "correct"       ? "border-l-emerald-400 hover:bg-emerald-50/20" :
                        la.verdict === "missed"        ? "border-l-slate-300 bg-slate-50/60" :
                        la.verdict === "price_wrong"   ? "border-l-red-400 bg-red-50/30" :
                        la.verdict === "price_rounded" ? "border-l-orange-400 bg-orange-50/20" :
                        la.verdict === "ref_wrong"     ? "border-l-amber-400 bg-amber-50/20" :
                                                        "border-l-violet-400 bg-violet-50/10"
                      }`}>
                        <td className="px-3 py-2.5 align-top whitespace-nowrap">
                          <span className="font-mono text-emerald-700 font-semibold text-[11px]">{la.actual_ref || "—"}</span>
                        </td>
                        <td className="px-3 py-2.5 align-top">
                          <span className="text-slate-600 leading-snug block max-w-[200px]">{la.actual_designation || "—"}</span>
                        </td>
                        <td className="px-3 py-2.5 align-top text-right">
                          <span className="font-mono text-slate-600">{la.qty ?? "—"}</span>
                        </td>
                        <td className="px-3 py-2.5 align-top text-right">
                          <span className="font-mono font-semibold text-emerald-700 text-[11px]">{priceReal != null ? fmtNum(priceReal) : "—"}</span>
                        </td>
                        <td className="px-1 align-middle text-center"><ArrowRight size={11} className="text-slate-300 mx-auto" /></td>
                        <td className="px-3 py-2.5 align-top whitespace-nowrap">
                          {la.verdict === "missed"
                            ? <span className="text-slate-300 italic text-[11px]">non extrait</span>
                            : <span className={`font-mono text-[11px] font-semibold ${refMismatch ? "text-amber-600" : "text-blue-600"}`}>{la.app_ref || "—"}</span>
                          }
                        </td>
                        <td className="px-3 py-2.5 align-top text-right">
                          {la.verdict === "missed"
                            ? <span className="text-slate-300">—</span>
                            : (
                              <div className="flex flex-col items-end gap-0.5">
                                <span className={`font-mono text-[11px] font-semibold ${hasPriceDiff ? "text-red-600" : "text-blue-600"}`}>
                                  {priceApp != null ? fmtNum(priceApp) : "—"}
                                </span>
                                {hasPriceDiff && (
                                  <span className="text-[10px] bg-red-100 text-red-600 font-mono px-1 rounded">Δ {fmtNum(priceDiff)}</span>
                                )}
                              </div>
                            )
                          }
                        </td>
                        <td className="px-3 py-2.5 align-top whitespace-nowrap">
                          <span className={`inline-flex items-center gap-1 text-[11px] font-semibold rounded-md px-2 py-0.5 border ${vc.bg} ${vc.cls} ${vc.border}`}>
                            <VcIcon size={10} />{vc.label}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 align-top">
                          {la.note ? <span className="text-[11px] text-slate-500 leading-snug">{la.note}</span> : <span className="text-slate-300">—</span>}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

/* ─────────────────────────────────────────────────────────────────
   RESULTS PAGE
───────────────────────────────────────────────────────────────── */
export default function ResultsPage() {
  const { jobId } = useParams();
  const navigate  = useNavigate();
  const { results, auditTrail, loading, error } = useJobResults(jobId);
  const [auditOpen, setAuditOpen] = useState(false);

  if (loading) {
    return (
      <PageWrapper title="Chargement des résultats…">
        <div className="flex justify-center py-24"><Spinner size="lg" /></div>
      </PageWrapper>
    );
  }

  if (error) {
    return (
      <PageWrapper title="Erreur">
        <Alert variant="error" title="Impossible de charger les résultats">{error}</Alert>
      </PageWrapper>
    );
  }

  if (!results) return null;

  const { verdict, documents, match_result, status, pdf_audit } = results;
  const needsReview = status === "REVIEW_REQUIRED";

  const gv = GLOBAL_VERDICT_CFG[verdict] ?? GLOBAL_VERDICT_CFG.REVIEW_REQUIRED;
  const GvIcon = gv.Icon;

  const lineVerdicts  = match_result?.line_verdicts ?? [];
  const missingLines  = lineVerdicts.filter((lv) => lv.verdict === "MISSING");
  const extraLines    = lineVerdicts.filter((lv) => lv.verdict === "EXTRA");
  const mismatchLines = lineVerdicts.filter((lv) => lv.verdict === "MISMATCH");

  const SectionHeading = ({ icon: Icon, children, count }) => (
    <h2 className="text-[11px] font-semibold text-slate-400 uppercase tracking-widest mb-2.5 flex items-center gap-1.5">
      <Icon size={12} />
      {children}
      {count != null && <span className="ml-1 font-mono font-normal normal-case tracking-normal text-slate-300">({count})</span>}
    </h2>
  );

  const CompareTable = ({ rows, emptyMsg = "Aucune ligne." }) => (
    <div className="bg-white border border-slate-200 rounded-xl overflow-hidden shadow-sm">
      {rows.length === 0 ? (
        <div className="px-4 py-6 text-center text-sm text-slate-400">{emptyMsg}</div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 border-l-4 border-l-transparent text-xs">
                <th className="text-left px-3 py-2.5 text-slate-400 font-semibold whitespace-nowrap">Réf</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-semibold">Désignation</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-semibold whitespace-nowrap">Qté <span className="font-normal text-slate-300">(BC / FAC)</span></th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-semibold whitespace-nowrap">Prix UN <span className="font-normal text-slate-300">(BC / FAC)</span></th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-semibold">TVA</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-semibold">Confiance</th>
                <th className="text-left px-3 py-2.5 text-slate-400 font-semibold">Verdict</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-50">
              {rows.map((lv, i) => <CompareRow key={lv.ref_produit ?? i} lv={lv} />)}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  return (
    <PageWrapper title="Vérification" subtitle={`Job ${jobId?.slice(0, 8)}…`}>
      <div className="space-y-8">

        {/* ══ VERDICT BANNER ══ */}
        <div className={`rounded-2xl overflow-hidden shadow-sm bg-gradient-to-r ${gv.bg}`}>
          <div className="px-6 py-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="w-11 h-11 rounded-xl bg-white/15 flex items-center justify-center shrink-0">
                <GvIcon size={22} className="text-white" />
              </div>
              <div>
                <div className="text-white text-xl font-semibold tracking-tight leading-none">{gv.label}</div>
                <div className="text-white/65 text-sm mt-1 leading-snug">{gv.desc}</div>
              </div>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <BannerStat value={match_result?.matches}    label="Match"    />
              <BannerStat value={match_result?.mismatches} label="Mismatch" />
              <BannerStat value={match_result?.missing}    label="Missing"  />
              <BannerStat value={match_result?.extra}      label="Extra"    />
            </div>
          </div>
          {match_result?.total_lines > 0 && (
            <div className="h-1 bg-white/10">
              <div className="h-full bg-white/40 transition-all" style={{ width: `${((match_result.matches ?? 0) / match_result.total_lines) * 100}%` }} />
            </div>
          )}
        </div>

        {/* ══ QUALITY SCORE ══ */}
        <QualityScoreSection documents={documents} match_result={match_result} auditTrail={auditTrail} />

        {/* ══ HUMAN REVIEW CTA ══ */}
        {needsReview && (
          <Alert variant="warning" title="Révision humaine requise">
            Ce dossier a été signalé pour révision manuelle.{" "}
            <button onClick={() => navigate(`/review/${jobId}`)} className="underline font-semibold">
              Aller à la page de révision →
            </button>
          </Alert>
        )}

        {/* ══ DOCUMENTS EXTRACTED ══ */}
        <section>
          <SectionHeading icon={FileText} count={documents?.length ?? 0}>Documents extraits</SectionHeading>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {documents?.map((doc, i) => <DocCard key={i} doc={doc} />)}
          </div>
        </section>

        {/* ══ FULL COMPARISON TABLE ══ */}
        {lineVerdicts.length > 0 && (
          <section>
            <div className="flex items-center justify-between mb-2.5 flex-wrap gap-2">
              <SectionHeading icon={ClipboardList} count={match_result?.total_lines}>
                Comparaison FAC / BL vs BC
              </SectionHeading>
              <div className="flex items-center gap-1.5 flex-wrap">
                {Object.entries(LINE_VERDICT_CFG).map(([k]) => <VerdictBadge key={k} verdict={k} />)}
              </div>
            </div>
            <CompareTable rows={lineVerdicts} />
          </section>
        )}

        {/* ══ MISMATCHES ══ */}
        {mismatchLines.length > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-2.5">
              <XCircle size={14} className="text-red-500" />
              <h2 className="text-[11px] font-semibold text-red-500 uppercase tracking-widest">Écarts de prix / quantité ({mismatchLines.length})</h2>
            </div>
            <div className="rounded-xl border border-red-200 bg-red-50/40 overflow-hidden">
              {mismatchLines.map((lv, i) => {
                const priceBC  = Number(lv.prix_bc ?? 0);
                const priceFAC = Number(lv.prix_facture ?? 0);
                const diff     = Math.abs(priceBC - priceFAC);
                return (
                  <div key={lv.ref_produit ?? i} className={`flex items-start justify-between gap-4 px-4 py-3 text-xs ${i > 0 ? "border-t border-red-100" : ""}`}>
                    <div>
                      <span className="font-mono font-semibold text-slate-700 mr-2">{lv.ref_produit}</span>
                      <span className="text-slate-500">{lv.designation}</span>
                    </div>
                    <div className="flex items-center gap-3 shrink-0 flex-wrap justify-end">
                      {/* Qty mismatch block — shown when qty is the actual problem */}
                      {lv.mismatch_fields?.includes("qty_bc_vs_facture") && (
                        <div className="flex items-center gap-2">
                          <div className="text-right">
                            <div className="text-[10px] text-slate-400">Qté BC</div>
                            <div className="font-mono font-semibold text-slate-700">{fmtQty(lv.qty_bc)}</div>
                          </div>
                          <ArrowRight size={11} className="text-slate-300" />
                          <div className="text-right">
                            <div className="text-[10px] text-slate-400">Qté FAC</div>
                            <div className="font-mono font-semibold text-red-600">{fmtQty(lv.qty_facture)}</div>
                          </div>
                          <div className="bg-red-100 text-red-700 rounded px-2 py-0.5 font-mono text-[11px] font-medium">
                            Δ {Math.abs((lv.qty_bc ?? 0) - (lv.qty_facture ?? 0))} unités
                          </div>
                        </div>
                      )}
                      {/* Price mismatch block — only shown when price diff is real (> 0) */}
                      {lv.mismatch_fields?.includes("prix_unitaire") && diff > 0 && (
                        <div className="flex items-center gap-2">
                          {lv.prix_bc != null && (
                            <div className="text-right">
                              <div className="text-[10px] text-slate-400">Prix BC</div>
                              <div className="font-mono font-semibold text-slate-700">{fmtNum(lv.prix_bc)}</div>
                            </div>
                          )}
                          <ArrowRight size={11} className="text-slate-300" />
                          {lv.prix_facture != null && (
                            <div className="text-right">
                              <div className="text-[10px] text-slate-400">Prix FAC</div>
                              <div className="font-mono font-semibold text-red-600">{fmtNum(lv.prix_facture)}</div>
                            </div>
                          )}
                          <div className="bg-red-100 text-red-700 rounded px-2 py-0.5 font-mono text-[11px] font-medium">
                            Δ {fmtNum(diff)} DT
                          </div>
                        </div>
                      )}
                      {/* Fallback: other mismatch fields (tva, etc.) */}
                      {!lv.mismatch_fields?.includes("qty_bc_vs_facture") &&
                       !lv.mismatch_fields?.includes("prix_unitaire") &&
                       lv.mismatch_fields?.length > 0 && (
                        <div className="flex gap-1 flex-wrap">
                          {lv.mismatch_fields.map((f) => (
                            <code key={f} className="text-[11px] bg-red-100 text-red-700 px-2 py-0.5 rounded font-mono">{formatMismatchField(f)}</code>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}

        {/* ══ MISSING ══ */}
        {missingLines.length > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-2.5">
              <AlertTriangle size={14} className="text-amber-500" />
              <h2 className="text-[11px] font-semibold text-amber-600 uppercase tracking-widest">Articles commandés non facturés ({missingLines.length})</h2>
            </div>
            <div className="rounded-xl border border-amber-200 bg-amber-50/40 overflow-hidden">
              {missingLines.map((lv, i) => (
                <div key={lv.ref_produit ?? i} className={`flex items-start justify-between gap-4 px-4 py-3 text-xs ${i > 0 ? "border-t border-amber-100" : ""}`}>
                  <div>
                    <span className="font-mono font-semibold text-slate-700 mr-2">{lv.ref_produit}</span>
                    <span className="text-slate-500">{lv.designation}</span>
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    {lv.qty_bc != null && <span className="text-slate-500">Qté commandée : <span className="font-mono font-semibold text-slate-700">{fmtQty(lv.qty_bc)}</span></span>}
                    {lv.prix_bc != null && <span className="font-mono text-slate-600">{fmtNum(lv.prix_bc)} DT</span>}
                    <span className="bg-amber-100 text-amber-700 rounded px-2 py-0.5 font-medium text-[11px]">Non facturé</span>
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ══ EXTRA ══ */}
        {extraLines.length > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-2.5">
              <Info size={14} className="text-sky-500" />
              <h2 className="text-[11px] font-semibold text-sky-600 uppercase tracking-widest">Articles supplémentaires non commandés ({extraLines.length})</h2>
            </div>
            <div className="rounded-xl border border-sky-200 bg-sky-50/40 overflow-hidden">
              {extraLines.map((lv, i) => (
                <div key={lv.ref_produit ?? i} className={`flex items-start justify-between gap-4 px-4 py-3 text-xs ${i > 0 ? "border-t border-sky-100" : ""}`}>
                  <div>
                    <span className="font-mono font-semibold text-slate-700 mr-2">{lv.ref_produit}</span>
                    <span className="text-slate-500">{lv.designation}</span>
                  </div>
                  <span className="bg-sky-100 text-sky-700 rounded px-2 py-0.5 font-medium text-[11px] shrink-0">Hors BC</span>
                </div>
              ))}
            </div>
          </section>
        )}

        {/* ══ PDF vs APP AUDIT ══ */}
        {pdf_audit && (
          <section>
            <div className="flex items-center gap-2 mb-3">
              <ScanSearch size={13} className="text-violet-500" />
              <h2 className="text-[11px] font-semibold text-violet-600 uppercase tracking-widest">Audit PDF vs Résultats Application</h2>
              <div className="flex-1 h-px bg-violet-100" />
              <span className="text-[10px] text-violet-400 font-medium bg-violet-50 border border-violet-200 px-2 py-0.5 rounded-md">Vérification indépendante</span>
            </div>
            <div className="mb-4 rounded-xl border border-violet-200 bg-violet-50/50 px-4 py-3 flex items-start gap-3">
              <ShieldCheck size={15} className="text-violet-500 mt-0.5 shrink-0" />
              <p className="text-xs text-violet-700 leading-relaxed">
                Cette section compare les <strong>valeurs réelles extraites du PDF source</strong> avec ce que l'application a effectivement lu et interprété.
                Elle permet d'identifier les erreurs d'OCR, les arrondis incorrects, les références mal lues ou les lignes entières manquées,
                indépendamment du rapprochement BC / BL / FAC.
              </p>
            </div>
            <PdfAuditSection audit={pdf_audit} />
          </section>
        )}

        {/* ══ ACTION BAR ══ */}
        <div className="flex items-center gap-2 pt-4 border-t border-slate-100">
          <button onClick={() => navigate("/")} className="flex items-center gap-1.5 px-3.5 py-2 border border-slate-200 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors font-medium">
            <Upload size={13} />
            Nouveau document
          </button>
          <button onClick={() => setAuditOpen(true)} className="flex items-center gap-1.5 px-3.5 py-2 border border-slate-200 rounded-lg text-sm text-slate-600 hover:bg-slate-50 transition-colors font-medium">
            <ClipboardList size={13} />
            Journal d&apos;audit
          </button>
          {needsReview && (
            <button onClick={() => navigate(`/review/${jobId}`)} className="flex items-center gap-1.5 px-4 py-2 bg-amber-500 hover:bg-amber-600 text-white rounded-lg text-sm font-semibold transition-colors shadow-sm">
              <CheckCircle2 size={14} />
              Réviser &amp; Approuver
            </button>
          )}
        </div>
      </div>

      <Modal open={auditOpen} onClose={() => setAuditOpen(false)} title="Journal d'audit">
        <AuditTrail auditTrail={auditTrail} />
      </Modal>
    </PageWrapper>
  );
}
