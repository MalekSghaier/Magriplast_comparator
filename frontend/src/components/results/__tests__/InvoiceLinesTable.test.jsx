import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import InvoiceLinesTable from "../InvoiceLinesTable";

// lucide-react icons are not critical in unit tests — stub them out.
vi.mock("lucide-react", () => ({
  FileText: () => null,
  AlertTriangle: () => null,
}));

// ── fixtures ───────────────────────────────────────────────────────────────

const INVOICE_LINES = [
  {
    line_number: 1,
    ref_produit: "REF-001",
    designation: "Produit A",
    qty: 10,
    prix_unitaire: 25.5,
    extraction_confidence: 0.92,
  },
  {
    line_number: 2,
    ref_produit: "REF-002",
    designation: "Produit B",
    qty: 5,
    prix_unitaire: 100,
    extraction_confidence: 0.88,
  },
];

// A comparison-only object — must never appear in the invoice table.
const COMPARISON_ONLY_LINE = {
  ref_produit: "REF-BC-ONLY",
  designation: "Article absent de la facture",
  qty_bc: 3,
  qty_facture: null,
  verdict: "MISSING",
  mismatch_fields: [],
};

// ── Test 1 ─────────────────────────────────────────────────────────────────

describe("InvoiceLinesTable — colonnes affichées", () => {
  it("affiche uniquement les 3 colonnes Réf/Désignation, Qté, Prix unitaire", () => {
    render(<InvoiceLinesTable lines={INVOICE_LINES} />);

    expect(screen.getByText(/Réf \/ Désignation/i)).toBeInTheDocument();
    expect(screen.getByText(/Qté/i)).toBeInTheDocument();
    expect(screen.getByText(/Prix unitaire/i)).toBeInTheDocument();
  });
});

// ── Test 2 ─────────────────────────────────────────────────────────────────

describe("InvoiceLinesTable — colonnes absentes", () => {
  it("n'affiche pas BL QTÉ, FAC QTÉ, TVA%, VERDICT ni les badges de comparaison", () => {
    render(<InvoiceLinesTable lines={INVOICE_LINES} />);

    expect(screen.queryByText(/BL\s*Q/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/FAC\s*Q/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/TVA/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/VERDICT/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Partial\s*Match/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Mismatch/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Partial\s*Data/i)).not.toBeInTheDocument();
  });
});

// ── Test 3 ─────────────────────────────────────────────────────────────────

describe("InvoiceLinesTable — filtrage des lignes de comparaison", () => {
  it("n'affiche pas les lignes issues uniquement du bon de commande (verdict présent)", () => {
    render(<InvoiceLinesTable lines={[...INVOICE_LINES, COMPARISON_ONLY_LINE]} />);

    // The comparison-only line must not appear
    expect(screen.queryByText("REF-BC-ONLY")).not.toBeInTheDocument();
    expect(screen.queryByText("Article absent de la facture")).not.toBeInTheDocument();

    // Invoice lines must still be present
    expect(screen.getByText("REF-001")).toBeInTheDocument();
    expect(screen.getByText("REF-002")).toBeInTheDocument();
  });
});

// ── Test 4 ─────────────────────────────────────────────────────────────────

describe("InvoiceLinesTable — rendu des lignes facture", () => {
  it("affiche la référence et la désignation de chaque ligne extraite", () => {
    render(<InvoiceLinesTable lines={INVOICE_LINES} />);

    expect(screen.getByText("REF-001")).toBeInTheDocument();
    expect(screen.getByText("Produit A")).toBeInTheDocument();
    expect(screen.getByText("REF-002")).toBeInTheDocument();
    expect(screen.getByText("Produit B")).toBeInTheDocument();
  });
});

// ── Test 5 ─────────────────────────────────────────────────────────────────

describe("InvoiceLinesTable — état vide", () => {
  it('affiche "Aucune ligne facture extraite" quand lines est vide ou undefined', () => {
    const { rerender } = render(<InvoiceLinesTable lines={[]} />);
    expect(screen.getByText(/Aucune ligne facture extraite/i)).toBeInTheDocument();

    rerender(<InvoiceLinesTable lines={undefined} />);
    expect(screen.getByText(/Aucune ligne facture extraite/i)).toBeInTheDocument();
  });

  it('affiche "Aucune ligne facture extraite" quand toutes les lignes sont des objets de comparaison', () => {
    render(<InvoiceLinesTable lines={[COMPARISON_ONLY_LINE]} />);
    expect(screen.getByText(/Aucune ligne facture extraite/i)).toBeInTheDocument();
  });
});
