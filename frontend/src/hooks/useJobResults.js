import { useState, useEffect } from "react";
import { getJobResults, getAuditTrail } from "../api/jobs";

function normaliseLineVerdict(raw) {
  if (!raw) return raw;
  return {
    // ── primary alias (the bug fix) ───────────────────────────────────────
    line_ref:         raw.line_ref         ?? raw.ref_produit         ?? null,
    line_ref_facture: raw.line_ref_facture ?? raw.ref_produit_facture ?? null,
    line_ref_bl:      raw.line_ref_bl      ?? raw.ref_produit_bl      ?? null,

    // ── pass-through fields (kept for completeness / future use) ─────────
    ref_produit:          raw.ref_produit          ?? null,
    ref_produit_facture:  raw.ref_produit_facture  ?? null,
    ref_produit_bl:       raw.ref_produit_bl       ?? null,

    designation:  raw.designation  ?? null,
    qty_bc:       raw.qty_bc       ?? null,
    qty_bl:       raw.qty_bl       ?? null,
    qty_facture:  raw.qty_facture  ?? null,
    prix_bc:      raw.prix_bc      ?? null,
    prix_facture: raw.prix_facture ?? null,
    tva_bc:       raw.tva_bc       ?? null,
    tva_facture:  raw.tva_facture  ?? null,
    verdict:          raw.verdict          ?? "PARTIAL_DATA",
    mismatch_fields:  raw.mismatch_fields  ?? [],
    confidence:       raw.confidence       ?? 1.0,
    match_layer:      raw.match_layer      ?? 0,
    notes:            raw.notes            ?? null,
    field_confidence_map: raw.field_confidence_map ?? {},
    reference_alias_applied: raw.reference_alias_applied ?? false,
    reference_alias_id: raw.reference_alias_id ?? null,
    reference_alias_external: raw.reference_alias_external ?? null,
    reference_alias_internal: raw.reference_alias_internal ?? null,
    reference_alias_supplier_key: raw.reference_alias_supplier_key ?? null,
  };
}

/**
 * Normalise the full results payload so the rest of the frontend
 * only deals with the canonical shape above.
 */
function normaliseResults(data) {
  if (!data) return data;

  const mr = data.match_result;
  if (mr?.line_verdicts) {
    mr.line_verdicts = mr.line_verdicts.map(normaliseLineVerdict);
  }

  return data;
}

export function useJobResults(jobId) {
  const [results, setResults]     = useState(null);
  const [auditTrail, setAuditTrail] = useState(null);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;

    async function fetchAll() {
      setLoading(true);
      setError(null);

      try {
        const [resultsData, auditData] = await Promise.all([
          getJobResults(jobId),
          getAuditTrail(jobId).catch(() => null),
        ]);

        if (!cancelled) {
          setResults(normaliseResults(resultsData));
          setAuditTrail(auditData);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchAll();
    return () => { cancelled = true; };
  }, [jobId]);

  async function refetch() {
    try {
      setLoading(true);
      const [resultsData, auditData] = await Promise.all([
        getJobResults(jobId),
        getAuditTrail(jobId).catch(() => null),
      ]);
      setResults(normaliseResults(resultsData));
      setAuditTrail(auditData);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return { results, auditTrail, loading, error, refetch };
}
