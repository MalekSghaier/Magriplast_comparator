"""
Adaptive Word Dictionary — thread-safe, DB-backed OCR correction service.

Contract:
  1. is_dictionary_candidate()  → only real words enter the pipeline.
  2. normalize_dictionary_key() → stable lookup key.
  3. Exact DB lookup → only verified, non-ignored entries.
  4. Fuzzy match             → only for normalizable fields.
  5. GPT batch fallback      → one call for all unknown tokens.
  6. GPT results stored with verified=False, weight≤0.75, source=LLM_SUGGESTED.
  7. Protected tokens (codes, amounts, dates…) are NEVER touched.

Fixes applied (vs original):
  BUG-1  _store_entry: single insert_stmt object, sa_case instead of func.case
  BUG-2  correct():    single locked cache read via .get(), no double re-read
  BUG-3  enrich_from_gpt(): _store_entry outside lock, only cache write inside
  BUG-4  correct_unknown_tokens_with_llm(): all DB I/O outside lock
  BUG-5  _fuzzy_match(): Levenshtein import moved to module level
  BUG-6  _get_fuzzy_index(): _index_dirty / _fuzzy_index guarded by lock
  BUG-7  export_stats(): aggregate SQL queries, no full table load
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field as dc_field
from datetime import datetime, timezone
from typing import Optional

import httpx
from rapidfuzz import fuzz
from sqlalchemy import select, update, func, case as sa_case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from unidecode import unidecode

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.word_dictionary import WordDictionaryEntry, WordCategory, WordSource
from app.services.value_protection import (
    is_protected_value,
    is_normalizable_field,
    is_dictionary_candidate,
    normalize_dictionary_key,
)

logger = logging.getLogger(__name__)

_CacheEntry = tuple[str, float, str]   # (canonical_form, weight, source)
_MAX_GPT_WEIGHT = 0.75

try:
    from Levenshtein import distance as _lev_distance          
except ImportError:
    from rapidfuzz.distance import Levenshtein as _Lev       
    _lev_distance = _Lev.distance
# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class UnknownToken:
    raw_value: str
    field_name: Optional[str] = None
    context_words: list[str] = dc_field(default_factory=list)
    supplier_id: Optional[str] = None
@dataclass
class CorrectionSuggestion:
    raw_value: str
    corrected_value: str
    confidence: float
    term_type: str
    should_add_to_dictionary: bool
    should_apply_now: bool
    reason: str = ""

def _s(raw: str, canonical: str, cat: WordCategory) -> tuple[str, str, WordCategory]:
    """Helper to create a seed entry with normalized key."""
    return (normalize_dictionary_key(raw), canonical, cat)
_D = WordCategory.DOCUMENT
_H = WordCategory.HEADER
_U = WordCategory.UNIT
_P = WordCategory.PRODUCT
_B = WordCategory.BRAND
_M = WordCategory.MATERIAL
_A = WordCategory.ACTION
_PAY = WordCategory.PAYMENT
_X = WordCategory.MISC

# ── A. Document types ─────────────────────────────────────────────────────────
_SEED_DOCUMENT: list[tuple[str, str, WordCategory]] = [
    # FACTURE
    _s("facture",       "FACTURE", _D),
    _s("factur",        "FACTURE", _D),
    _s("fcture",        "FACTURE", _D),
    _s("faeture",       "FACTURE", _D),
    _s("fac",           "FACTURE", _D),
    _s("fct",           "FACTURE", _D),
    _s("facture n",     "FACTURE", _D),
    _s("facture no",    "FACTURE", _D),
    _s("facture n°",    "FACTURE", _D),
    _s("facture ne",    "FACTURE", _D),
    # BON_COMMANDE
    _s("bon de commande",  "BON_COMMANDE", _D),
    _s("bon commande",     "BON_COMMANDE", _D),
    _s("bon de comande",   "BON_COMMANDE", _D),
    _s("bon de commende",  "BON_COMMANDE", _D),
    _s("commande",         "BON_COMMANDE", _D),
    _s("b.c",              "BON_COMMANDE", _D),
    _s("b.c.",             "BON_COMMANDE", _D),
    _s("bc",               "BON_COMMANDE", _D),
    _s("bon cde",          "BON_COMMANDE", _D),
    _s("cde",              "BON_COMMANDE", _D),
    # BON_LIVRAISON
    _s("bon de livraison", "BON_LIVRAISON", _D),
    _s("bon livraison",    "BON_LIVRAISON", _D),
    _s("bon de livr",      "BON_LIVRAISON", _D),
    _s("bon livr",         "BON_LIVRAISON", _D),
    _s("livraison",        "BON_LIVRAISON", _D),
    _s("b.l",              "BON_LIVRAISON", _D),
    _s("b.l.",             "BON_LIVRAISON", _D),
    _s("bl",               "BON_LIVRAISON", _D),
    _s("b liv",            "BON_LIVRAISON", _D),
    # RECEPTION
    _s("reception",   "RECEPTION", _D),
    _s("réception",   "RECEPTION", _D),
    _s("recption",    "RECEPTION", _D),
    _s("recep",       "RECEPTION", _D),
    _s("récéption",   "RECEPTION", _D),
    _s("roception",   "RECEPTION", _D),
    _s("recu",        "RECEPTION", _D),
    _s("reçu",        "RECEPTION", _D),
    _s("date recu",   "RECEPTION", _D),
    _s("date reçu",   "RECEPTION", _D),
]

# ── B. Column headers ─────────────────────────────────────────────────────────
_SEED_HEADERS: list[tuple[str, str, WordCategory]] = [
    # FOURNISSEUR
    _s("fournisseur",  "FOURNISSEUR", _H),
    _s("fourniseur",   "FOURNISSEUR", _H),
    _s("founisseur",   "FOURNISSEUR", _H),
    _s("foumisseur",   "FOURNISSEUR", _H),
    _s("fournis",      "FOURNISSEUR", _H),
    _s("fseur",        "FOURNISSEUR", _H),
    # CLIENT
    _s("client",       "CLIENT", _H),
    _s("cllent",       "CLIENT", _H),
    _s("c1ient",       "CLIENT", _H),
    _s("cli",          "CLIENT", _H),
    _s("code client",  "CLIENT", _H),
    _s("cd client",    "CLIENT", _H),
    # NUMERO
    _s("numero",          "NUMERO", _H),
    _s("numéro",          "NUMERO", _H),
    _s("num",             "NUMERO", _H),
    _s("n°",              "NUMERO", _H),
    _s("no",              "NUMERO", _H),
    _s("numero facture",  "NUMERO", _H),
    _s("numero bl",       "NUMERO", _H),
    _s("numero bc",       "NUMERO", _H),
    # DATE
    _s("date",   "DATE", _H),
    _s("daté",   "DATE", _H),
    _s("dte",    "DATE", _H),
    _s("dt",     "DATE", _H),
    _s("du",     "DATE", _H),
    # PAGE
    _s("page",   "PAGE", _H),
    _s("pagé",   "PAGE", _H),
    _s("pge",    "PAGE", _H),
    # REFERENCE
    _s("reference",   "REFERENCE", _H),
    _s("références",  "REFERENCE", _H),
    _s("ref",         "REFERENCE", _H),
    _s("réf",         "REFERENCE", _H),
    _s("reff",        "REFERENCE", _H),
    _s("referance",   "REFERENCE", _H),
    # ARTICLE
    _s("article",           "ARTICLE", _H),
    _s("art",               "ARTICLE", _H),
    _s("code article",      "ARTICLE", _H),
    _s("code artic1e",      "ARTICLE", _H),
    _s("lg code article",   "ARTICLE", _H),
    _s("code produit",      "ARTICLE", _H),
    _s("code",              "ARTICLE", _H),
    # DESIGNATION
    _s("designation",              "DESIGNATION", _H),
    _s("désignation",              "DESIGNATION", _H),
    _s("designatlon",              "DESIGNATION", _H),
    _s("désignatlon",              "DESIGNATION", _H),
    _s("desig",                    "DESIGNATION", _H),
    _s("désig",                    "DESIGNATION", _H),
    _s("dsig",                     "DESIGNATION", _H),
    _s("libelle",                  "DESIGNATION", _H),
    _s("libellé",                  "DESIGNATION", _H),
    _s("description",              "DESIGNATION", _H),
    _s("descriptlon",              "DESIGNATION", _H),
    _s("designations articles",    "DESIGNATION", _H),
    _s("désignations articles",    "DESIGNATION", _H),
    # QUANTITE
    _s("quantite",           "QUANTITE", _H),
    _s("quantité",           "QUANTITE", _H),
    _s("quantlte",           "QUANTITE", _H),
    _s("qte",                "QUANTITE", _H),
    _s("qté",                "QUANTITE", _H),
    _s("qtè",                "QUANTITE", _H),
    _s("qto",                "QUANTITE", _H),
    _s("qtô",                "QUANTITE", _H),
    _s("qty",                "QUANTITE", _H),
    _s("quantite livree",    "QUANTITE", _H),
    _s("qte bon livr",       "QUANTITE", _H),
    _s("qte recept",         "QUANTITE", _H),
    # UNITE
    _s("unite",              "UNITE", _H),
    _s("unité",              "UNITE", _H),
    _s("unit",               "UNITE", _H),
    _s("um",                 "UNITE", _H),
    _s("u.m",                "UNITE", _H),
    _s("u.m.",               "UNITE", _H),
    _s("unite de mesure",    "UNITE", _H),
    # PRIX_UNITAIRE_HT
    _s("prix ht",            "PRIX_UNITAIRE_HT", _H),
    _s("prix h.t",           "PRIX_UNITAIRE_HT", _H),
    _s("prix unit",          "PRIX_UNITAIRE_HT", _H),
    _s("prix un",            "PRIX_UNITAIRE_HT", _H),
    _s("prix unitaire",      "PRIX_UNITAIRE_HT", _H),
    _s("prix unitair",       "PRIX_UNITAIRE_HT", _H),
    _s("prix unitaire ht",   "PRIX_UNITAIRE_HT", _H),
    _s("p.u.ht",             "PRIX_UNITAIRE_HT", _H),
    _s("pu ht",              "PRIX_UNITAIRE_HT", _H),
    _s("puht",               "PRIX_UNITAIRE_HT", _H),
    _s("p.u",                "PRIX_UNITAIRE_HT", _H),
    _s("pu",                 "PRIX_UNITAIRE_HT", _H),
    # MONTANT_HT
    _s("montant ht",         "MONTANT_HT", _H),
    _s("montant h.t",        "MONTANT_HT", _H),
    _s("montant net ht",     "MONTANT_HT", _H),
    _s("total ht",           "MONTANT_HT", _H),
    _s("total h.t",          "MONTANT_HT", _H),
    _s("tot ht",             "MONTANT_HT", _H),
    _s("total hors taxes",   "MONTANT_HT", _H),
    _s("net hors taxes",     "MONTANT_HT", _H),
    _s("net ht",             "MONTANT_HT", _H),
    _s("net h.t",            "MONTANT_HT", _H),
    _s("net htva",           "MONTANT_HT", _H),
    # TVA
    _s("tva",          "TVA", _H),
    _s("t.v.a",        "TVA", _H),
    _s("taux tva",     "TVA", _H),
    _s("base tva",     "TVA", _H),
    _s("base taxable", "TVA", _H),
    _s("taxe",         "TVA", _H),
    # FODEC
    _s("fodec",   "FODEC", _H),
    _s("fodéc",   "FODEC", _H),
    _s("f0dec",   "FODEC", _H),
    # REMISE
    _s("remise",            "REMISE", _H),
    _s("rem",               "REMISE", _H),
    _s("rem.",              "REMISE", _H),
    _s("% rem",             "REMISE", _H),
    _s("remise hors taxes", "REMISE", _H),
    # TIMBRE_FISCAL
    _s("timbre",        "TIMBRE_FISCAL", _H),
    _s("timbre fiscal", "TIMBRE_FISCAL", _H),
    _s("timbre fisc",   "TIMBRE_FISCAL", _H),
    _s("timbre loi",    "TIMBRE_FISCAL", _H),
    # TOTAL_TTC
    _s("total ttc",    "TOTAL_TTC", _H),
    _s("total t.t.c",  "TOTAL_TTC", _H),
    _s("montant ttc",  "TOTAL_TTC", _H),
    _s("montant t.t.c","TOTAL_TTC", _H),
    # NET_A_PAYER
    _s("net a payer",  "NET_A_PAYER", _H),
    _s("net à payer",  "NET_A_PAYER", _H),
    _s("netapayer",    "NET_A_PAYER", _H),
    _s("net payer",    "NET_A_PAYER", _H),
    # MONTANT
    _s("montant",  "MONTANT", _H),
    _s("mnt",      "MONTANT", _H),
    # ADRESSE / CONTACT
    _s("adresse",      "ADRESSE", _H),
    _s("adress",       "ADRESSE", _H),
    _s("adr",          "ADRESSE", _H),
    _s("telephone",    "TELEPHONE", _H),
    _s("téléphone",    "TELEPHONE", _H),
    _s("tel",          "TELEPHONE", _H),
    _s("tél",          "TELEPHONE", _H),
    _s("fax",          "FAX", _H),
    _s("email",        "EMAIL", _H),
    _s("e-mail",       "EMAIL", _H),
    _s("mail",         "EMAIL", _H),
    _s("site web",     "SITE_WEB", _H),
    _s("www",          "SITE_WEB", _H),
    _s("matricule fiscal", "MATRICULE_FISCAL", _H),
    _s("mat fiscal",       "MATRICULE_FISCAL", _H),
    _s("mf",               "MATRICULE_FISCAL", _H),
    _s("m.f",              "MATRICULE_FISCAL", _H),
    _s("c.tva",            "MATRICULE_FISCAL", _H),
    _s("rib",              "RIB", _H),
    _s("banque",           "RIB", _H),
    # Misc doc headers
    _s("conditions livraison",         "CONDITIONS_LIVRAISON", _H),
    _s("conditions de livraison",      "CONDITIONS_LIVRAISON", _H),
    _s("ht",              "HORS_TAXES", _H),
    _s("h.t",             "HORS_TAXES", _H),
    _s("h.t.",            "HORS_TAXES", _H),
    _s("ttc",             "TTC", _H),
    _s("t.t.c",           "TTC", _H),
    _s("t.t.c.",          "TTC", _H),
    _s("hors taxes",      "HORS_TAXES", _H),
    _s("signature",       "SIGNATURE", _X),
    _s("signatur",        "SIGNATURE", _X),
    _s("cachet signature","SIGNATURE", _X),
    _s("cachet",          "CACHET", _X),
    _s("chauffeur",       "CHAUFFEUR", _X),
    _s("vehicule",        "VEHICULE", _X),
    _s("véhicule",        "VEHICULE", _X),
    _s("marchandise",     "MARCHANDISE", _X),
    _s("marchandises",    "MARCHANDISE", _X),
    _s("conforme",        "CONFORME", _X),
    _s("apparent",        "APPARENT", _X),
]

# ── C. Payment terms ──────────────────────────────────────────────────────────
_SEED_PAYMENT: list[tuple[str, str, WordCategory]] = [
    _s("mode reglement",        "MODE_REGLEMENT", _PAY),
    _s("mode de reglement",     "MODE_REGLEMENT", _PAY),
    _s("reglement",             "MODE_REGLEMENT", _PAY),
    _s("modalites paiement",    "MODALITES_PAIEMENT", _PAY),
    _s("modalites de paiement", "MODALITES_PAIEMENT", _PAY),
    _s("echeance",              "ECHEANCE", _PAY),
    _s("échéance",              "ECHEANCE", _PAY),
    _s("cheque",                "CHEQUE", _PAY),
    _s("chèque",                "CHEQUE", _PAY),
    _s("chéque",                "CHEQUE", _PAY),
    _s("traite",                "TRAITE", _PAY),
    _s("traité",                "TRAITE", _PAY),
    _s("traite 60 jrs",         "TRAITE", _PAY),
    _s("traite 90 jrs",         "TRAITE", _PAY),
    _s("virement",              "VIREMENT", _PAY),
    _s("retenue",               "RETENUE", _PAY),
    _s("retenu",                "RETENUE", _PAY),
    _s("retenue a la source",   "RETENUE_SOURCE", _PAY),
    _s("penalite",              "PENALITE", _PAY),
    _s("pénalité",              "PENALITE", _PAY),
    _s("legal",                 "LEGAL", _PAY),
    _s("légal",                 "LEGAL", _PAY),
]

# ── D. Units ──────────────────────────────────────────────────────────────────
_SEED_UNITS: list[tuple[str, str, WordCategory]] = [
    _s("pc",       "PC", _U),
    _s("pcs",      "PC", _U),
    _s("pce",      "PC", _U),
    _s("piece",    "PC", _U),
    _s("pièce",    "PC", _U),
    _s("pieces",   "PC", _U),
    _s("pièces",   "PC", _U),
    _s("u",        "PC", _U),
    _s("un",       "PC", _U),
    _s("mt",       "MT", _U),
    _s("m.t",      "MT", _U),
    _s("metre",    "MT", _U),
    _s("mètre",    "MT", _U),
    _s("ml",       "ML", _U),
    _s("m.l",      "ML", _U),
    _s("kg",       "KG", _U),
    _s("kgs",      "KG", _U),
    _s("kilo",     "KG", _U),
    _s("l",        "L", _U),
    _s("litre",    "L", _U),
    _s("litres",   "L", _U),
    _s("lit",      "L", _U),
    _s("dt",       "TND", _U),
    _s("dinar",    "TND", _U),
    _s("tnd",      "TND", _U),
    _s("mm",       "MM", _U),
    _s("m",        "M", _U),
    _s("m2",       "M2", _U),
    _s("m3",       "M3", _U),
    _s("cm",       "CM", _U),
    _s("g",        "G", _U),
    _s("gr",       "G", _U),
    _s("t",        "T", _U),
    _s("tonne",    "T", _U),
    _s("jours",    "JOURS", _U),
    _s("jrs",      "JOURS", _U),
    _s("jour",     "JOURS", _U),
    _s("ens",      "ENSEMBLE", _U),
    _s("lot",      "LOT", _U),
    _s("bte",      "BOITE", _U),
    _s("boite",    "BOITE", _U),
    _s("rouleau",  "ROULEAU", _U),
    _s("rl",       "ROULEAU", _U),
    _s("sac",      "SAC", _U),
    _s("bidon",    "BIDON", _U),
    _s("botte",    "BOTTE", _U),
    _s("bobine",   "BOBINE", _U),
    _s("colis",    "COLIS", _U),
]

# ── E. Products — TEG / outillage industriel ──────────────────────────────────
_SEED_TEG: list[tuple[str, str, WordCategory]] = [
    # DISQUE (many OCR variants)
    _s("disque",              "DISQUE", _P),
    _s("disk",                "DISQUE", _P),
    _s("disc",                "DISQUE", _P),
    _s("disq",                "DISQUE", _P),
    _s("d1sque",              "DISQUE", _P),
    _s("disoue",              "DISQUE", _P),
    _s("disque a lamelle",    "DISQUE_LAMELLE", _P),
    # LAMELLE
    _s("lamelle",     "LAMELLE", _P),
    _s("lameile",     "LAMELLE", _P),
    _s("lamel1e",     "LAMELLE", _P),
    _s("lame11e",     "LAMELLE", _P),
    # TYROLIT
    _s("tyrolit",     "TYROLIT", _B),
    _s("tyro1it",     "TYROLIT", _B),
    _s("tyrol1t",     "TYROLIT", _B),
    _s("tyroilt",     "TYROLIT", _B),
    # CADENAS
    _s("cadenas",     "CADENAS", _P),
    _s("cadena",      "CADENAS", _P),
    _s("cadnas",      "CADENAS", _P),
    _s("cadna",       "CADENAS", _P),
    _s("cadenna",     "CADENAS", _P),
    # CHAINE
    _s("chaine",      "CHAINE", _P),
    _s("chaîne",      "CHAINE", _P),
    _s("cha1ne",      "CHAINE", _P),
    _s("chame",       "CHAINE", _P),
    _s("chnine",      "CHAINE", _P),
    # GALVANISE
    _s("galvanise",   "GALVANISE", _M),
    _s("galvanisé",   "GALVANISE", _M),
    _s("galv",        "GALVANISE", _M),
    _s("ga1v",        "GALVANISE", _M),
    _s("gaiv",        "GALVANISE", _M),
    # DECAPANT
    _s("decapant",    "DECAPANT", _P),
    _s("décapant",    "DECAPANT", _P),
    _s("decapan",     "DECAPANT", _P),
    # ACIER
    _s("acier",       "ACIER", _M),
    _s("ac1er",       "ACIER", _M),
    _s("acierr",      "ACIER", _M),
    _s("acicr",       "ACIER", _M),
    # ALUMINIUM
    _s("aluminium",   "ALUMINIUM", _M),
    _s("aluminiu",    "ALUMINIUM", _M),
    _s("alum1nium",   "ALUMINIUM", _M),
    _s("alu",         "ALUMINIUM", _M),
    _s("allu",        "ALUMINIUM", _M),
    # MECHE
    _s("meche",       "MECHE", _P),
    _s("mèche",       "MECHE", _P),
    # TARAUD
    _s("taraud",      "TARAUD", _P),
    _s("tareau",      "TARAUD", _P),
    _s("tarraud",     "TARAUD", _P),
    _s("tarrand",     "TARAUD", _P),
    # RIVET
    _s("rivet",       "RIVET", _P),
    _s("rivct",       "RIVET", _P),
    # SILICONE
    _s("silicone",    "SILICONE", _P),
    _s("silic0ne",    "SILICONE", _P),
    # SIKAFLEX
    _s("sikaflex",    "SIKAFLEX", _B),
    _s("sikaf1ex",    "SIKAFLEX", _B),
    _s("sikafiex",    "SIKAFLEX", _B),
    # ARALDITE
    _s("araldite",    "ARALDITE", _B),
    _s("araldit",     "ARALDITE", _B),
    _s("araidite",    "ARALDITE", _B),
    # COLLE / EPOXY
    _s("colle",       "COLLE", _P),
    _s("co1le",       "COLLE", _P),
    _s("epoxy",       "EPOXY", _P),
    _s("époxy",       "EPOXY", _P),
    _s("epoxi",       "EPOXY", _P),
    # SADER
    _s("sader",       "SADER", _B),
    # RONDELLE
    _s("rondelle",    "RONDELLE", _P),
    _s("rondelle plate", "RONDELLE_PLATE", _P),
    # VIS
    _s("vis",         "VIS", _P),
    _s("vls",         "VIS", _P),
    # CLE
    _s("cle",         "CLE", _P),
    _s("clé",         "CLE", _P),
    # RECTIFIE
    _s("rectifie",    "RECTIFIE", _P),
    _s("rectifié",    "RECTIFIE", _P),
    _s("rectif1e",    "RECTIFIE", _P),
    # GANT
    _s("gant",        "GANT", _P),
    _s("gants",       "GANT", _P),
    # ELECTRODE
    _s("electrode",   "ELECTRODE", _P),
    _s("électrode",   "ELECTRODE", _P),
    _s("electr0de",   "ELECTRODE", _P),
    # SOUDURE
    _s("soudure",     "SOUDURE", _P),
    _s("soudur",      "SOUDURE", _P),
]

# ── F. Products — Boudrant / pneumatique ──────────────────────────────────────
_SEED_BOUDRANT: list[tuple[str, str, WordCategory]] = [
    _s("shako",             "SHAKO", _B),
    _s("shak0",             "SHAKO", _B),
    _s("shakoe",            "SHAKO", _B),
    # UNION
    _s("union",             "UNION", _P),
    _s("unlon",             "UNION", _P),
    _s("uni0n",             "UNION", _P),
    _s("un1on",             "UNION", _P),
    # TECHNOPOLYMERE
    _s("technopolymere",    "TECHNOPOLYMERE", _M),
    _s("technopolymère",    "TECHNOPOLYMERE", _M),
    _s("technopo1ymere",    "TECHNOPOLYMERE", _M),
    # RACCORD
    _s("raccord",           "RACCORD", _P),
    _s("racor",             "RACCORD", _P),
    _s("raccor",            "RACCORD", _P),
    _s("racc0rd",           "RACCORD", _P),
    _s("raccords",          "RACCORD", _P),
    # ELECTROVANNE
    _s("electrovanne",      "ELECTROVANNE", _P),
    _s("électrovanne",      "ELECTROVANNE", _P),
    _s("electroanne",       "ELECTROVANNE", _P),
    _s("electrovane",       "ELECTROVANNE", _P),
    _s("electrovan",        "ELECTROVANNE", _P),
    # TEMPORISATEUR
    _s("temporisateur",     "TEMPORISATEUR", _P),
    _s("tempor1sateur",     "TEMPORISATEUR", _P),
    _s("temporisatevr",     "TEMPORISATEUR", _P),
    # BUTEE
    _s("butee",             "BUTEE", _P),
    _s("butée",             "BUTEE", _P),
    _s("butte",             "BUTEE", _P),
    # ROULEMENT
    _s("roulement",         "ROULEMENT", _P),
    _s("rlt",               "ROULEMENT", _P),
    # CLAVETTE
    _s("clavette",          "CLAVETTE", _P),
    _s("c1avette",          "CLAVETTE", _P),
    # BARREAU
    _s("barreau",           "BARREAU", _P),
    _s("barrea",            "BARREAU", _P),
    # AIGUILLE
    _s("aiguille",          "AIGUILLE", _P),
    _s("aiguilles",         "AIGUILLE", _P),
    _s("aigu1lles",         "AIGUILLE", _P),
    # TUBE / DROIT / BLEU
    _s("tube",              "TUBE", _P),
    _s("tubc",              "TUBE", _P),
    _s("droit",             "DROIT", _P),
    _s("dro1t",             "DROIT", _P),
    _s("bleu",              "BLEU", _P),
    _s("b1eu",              "BLEU", _P),
]

# ── G. Products — Mondial Flexible ───────────────────────────────────────────
_SEED_MONDIAL: list[tuple[str, str, WordCategory]] = [
    _s("flexible",    "FLEXIBLE", _P),
    _s("flexib1e",    "FLEXIBLE", _P),
    _s("flex",        "FLEXIBLE", _P),
    _s("graisse",     "GRAISSE", _P),
    _s("gra1sse",     "GRAISSE", _P),
    _s("tuyau",       "TUYAU", _P),
    _s("tuyav",       "TUYAU", _P),
    _s("tuyan",       "TUYAU", _P),
    _s("arme",        "ARME", _P),
    _s("armé",        "ARME", _P),
    _s("armee",       "ARME", _P),
    _s("collier",     "COLLIER", _P),
    _s("colier",      "COLLIER", _P),
    _s("co1lier",     "COLLIER", _P),
    _s("coll1er",     "COLLIER", _P),
    _s("serrage",     "SERRAGE", _P),
    _s("serage",      "SERRAGE", _P),
    _s("serragc",     "SERRAGE", _P),
    _s("boulon",      "BOULON", _P),
    _s("bou1on",      "BOULON", _P),
    _s("boulons",     "BOULON", _P),
    _s("adapteur",    "ADAPTEUR", _P),
    _s("adaptateur",  "ADAPTEUR", _P),
    _s("gorge",       "GORGE", _P),
    _s("g0rge",       "GORGE", _P),
    _s("diam",        "DIAMETRE", _P),
    _s("diamètre",    "DIAMETRE", _P),
    _s("diametre",    "DIAMETRE", _P),
    _s("dia",         "DIAMETRE", _P),
    _s("dn",          "DN", _P),
    _s("inox",        "INOX", _M),
    _s("in0x",        "INOX", _M),
    _s("laiton",      "LAITON", _M),
    _s("la1ton",      "LAITON", _M),
    _s("laitton",     "LAITON", _M),
    _s("laton",       "LAITON", _M),
]

# ── H. Products — STEMCA / emballage ─────────────────────────────────────────
_SEED_STEMCA: list[tuple[str, str, WordCategory]] = [
    _s("emballage",     "EMBALLAGE", _P),
    _s("embalage",      "EMBALLAGE", _P),
    _s("emba11age",     "EMBALLAGE", _P),
    _s("cartonnage",    "CARTONNAGE", _P),
    _s("cartonage",     "CARTONNAGE", _P),
    _s("cart0nnage",    "CARTONNAGE", _P),
    _s("caisse",        "CAISSE", _P),
    _s("caise",         "CAISSE", _P),
    _s("ca1sse",        "CAISSE", _P),
    _s("calsse",        "CAISSE", _P),
    _s("carton",        "CARTON", _P),
    _s("cart0n",        "CARTON", _P),
    _s("karton",        "CARTON", _P),
    _s("couvercle",     "COUVERCLE", _P),
    _s("couv",          "COUVERCLE", _P),
    _s("compose",       "COMPOSE", _P),
    _s("composé",       "COMPOSE", _P),
    _s("comp",          "COMPOSE", _P),
    _s("octogonal",     "OCTOGONAL", _P),
    _s("oct",           "OCTOGONAL", _P),
    _s("fond",          "FOND", _P),
    _s("f0nd",          "FOND", _P),
]

# ── I. Products — SudPack / packaging ────────────────────────────────────────
_SEED_SUDPACK: list[tuple[str, str, WordCategory]] = [
    _s("sudpack",     "SUDPACK", _B),
    _s("sud pack",    "SUDPACK", _B),
    _s("sud pac",     "SUDPACK", _B),
    _s("film",        "FILM", _P),
    _s("fi1m",        "FILM", _P),
    _s("bobine",      "BOBINE", _P),
    _s("bobin",       "BOBINE", _P),
    _s("pack",        "PACK", _P),
    _s("pak",         "PACK", _P),
    _s("camion",      "CAMION", _X),
    _s("camlon",      "CAMION", _X),
    _s("source",      "SOURCE", _X),
]

# ── J. Products — Tunimetal / métal ──────────────────────────────────────────
_SEED_METAL: list[tuple[str, str, WordCategory]] = [
    _s("tole",        "TOLE", _P),
    _s("tôle",        "TOLE", _P),
    _s("t0le",        "TOLE", _P),
    _s("profile",     "PROFILE", _P),
    _s("profilé",     "PROFILE", _P),
    _s("prof1le",     "PROFILE", _P),
    _s("ipn",         "IPN", _P),
    _s("1pn",         "IPN", _P),
    _s("hm",          "HM", _P),
    _s("longueur",    "LONGUEUR", _P),
    _s("longeur",     "LONGUEUR", _P),
    _s("long",        "LONGUEUR", _P),
    _s("boite",       "BOITE", _P),
    _s("boîte",       "BOITE", _P),
    _s("bo1te",       "BOITE", _P),
    _s("electrode",   "ELECTRODE", _P),
    _s("electr0de",   "ELECTRODE", _P),
    _s("rutile",      "RUTILE", _P),
    _s("ruti1e",      "RUTILE", _P),
    _s("tige",        "TIGE", _P),
    _s("t1ge",        "TIGE", _P),
]

# ── Master seed list ──────────────────────────────────────────────────────────
_ALL_SEED_ENTRIES: list[tuple[str, str, WordCategory]] = (
    _SEED_DOCUMENT
    + _SEED_HEADERS
    + _SEED_PAYMENT
    + _SEED_UNITS
    + _SEED_TEG
    + _SEED_BOUDRANT
    + _SEED_MONDIAL
    + _SEED_STEMCA
    + _SEED_SUDPACK
    + _SEED_METAL
)

# ══════════════════════════════════════════════════════════════════════════════
# OCR VARIANT GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

_OCR_SUBSTITUTIONS: list[tuple[str, str]] = [
    ("o", "0"), ("0", "o"),
    ("i", "1"), ("1", "i"),
    ("l", "1"), ("1", "l"),
    ("s", "5"), ("5", "s"),
    ("b", "8"), ("8", "b"),
    ("rn", "m"),
    ("cl", "d"),
    ("vv", "w"),
]


def generate_ocr_variants(
    raw_form: str,
    canonical_form: str,
    category: WordCategory,
) -> list[tuple[str, str, WordCategory]]:
    """
    Generate plausible OCR variants for a seed entry.
    Only generates variants where the result is still a recognizable word (no codes).
    """
    variants: set[str] = set()
    base = raw_form.lower()

    for ocr_char, real_char in _OCR_SUBSTITUTIONS:
        if ocr_char in base:
            variant = base.replace(ocr_char, real_char, 1)
            if variant != base and len(variant) >= 3:
                variants.add(variant)

    result: list[tuple[str, str, WordCategory]] = []
    for v in variants:
        if not is_protected_value(v) and is_dictionary_candidate(v, "designation"):
            result.append((v, canonical_form, category))
    return result

def build_full_seed_with_variants() -> list[tuple[str, str, WordCategory]]:
    """Expand the master seed list with OCR variants."""
    seen: set[str] = set()
    result: list[tuple[str, str, WordCategory]] = []

    for raw, canonical, cat in _ALL_SEED_ENTRIES:
        key = normalize_dictionary_key(raw)
        if key and key not in seen:
            seen.add(key)
            result.append((key, canonical, cat))
        if cat in (_P, _B, _M, _H, _D):
            for vraw, vcan, vcat in generate_ocr_variants(key, canonical, cat):
                vkey = normalize_dictionary_key(vraw)
                if vkey and vkey not in seen:
                    seen.add(vkey)
                    result.append((vkey, vcan, vcat))
    return result


# ══════════════════════════════════════════════════════════════════════════════
# WORD DICTIONARY CLASS
# ══════════════════════════════════════════════════════════════════════════════

class WordDictionary:
    """
    Thread-safe adaptive OCR correction dictionary.

    Pipeline for a single word:
      correct(word, field_name) →
        1. is_dictionary_candidate() guard
        2. Exact DB lookup (verified, not ignored)
        3. Fuzzy match (normalizable fields only)
        4. Return PASSTHROUGH (GPT called in batch from pipeline)

    Concurrency model:
      - self._lock guards ONLY the in-memory _cache dict and the
        _fuzzy_index / _index_dirty pair.
      - All DB I/O (SELECT, UPSERT) runs OUTSIDE the lock so concurrent
        coroutines execute their database calls in parallel.
    """

    def __init__(self) -> None:
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._fuzzy_index: list[tuple[str, str]] | None = None
        self._index_dirty = True

    async def correct(
        self,
        word: str,
        field_name: str | None = None,
        supplier_profile=None,
        context_words: list[str] | None = None,
    ) -> tuple[str, float, str]:
        """
        Attempt to correct an OCR word.

        Lock scope: only the in-memory _cache dict access is locked.
        DB operations run outside the lock so concurrent coroutines can
        execute their database calls in parallel.
        Returns (canonical_form, confidence, source).
        Protected or non-candidate tokens are returned unchanged.
        """
        if not word or not word.strip():
            return word, 0.0, "PASSTHROUGH"

        if is_protected_value(word, field_name=field_name, supplier_profile=supplier_profile):
            return word, 1.0, "PROTECTED"

        if field_name is not None and not is_normalizable_field(field_name):
            return word, 1.0, "PROTECTED"

        if not is_dictionary_candidate(word, field_name=field_name):
            return word, 1.0, "PROTECTED"

        key = normalize_dictionary_key(word)
        if not key:
            return word, 0.0, "PASSTHROUGH"

        # ── Phase 1: thread-safe cache lookup ─────────────────────────────────
        # BUG-2 FIX:
        cached: _CacheEntry | None = None
        async with self._lock:
            cached = self._cache.get(key) 

        if cached is not None:
            await self._increment_usage(key)
            return cached

        # ── Phase 2: DB lookup — no lock needed (no shared mutable state) ─────
        db_entry = await self._db_lookup(key)
        if db_entry and db_entry.verified and not db_entry.ignored and db_entry.weight > 0.7:
            result: _CacheEntry = (db_entry.canonical_form, db_entry.weight, db_entry.source)
            async with self._lock:
                self._cache[key] = result      
            await self._increment_usage(key)   
            return result
        # ── Phase 3: fuzzy match — DB call, no lock ───────────────────────────
        allow_fuzzy = field_name is None or is_normalizable_field(field_name)
        if allow_fuzzy:
            fuzzy_result = await self._fuzzy_match(key)
            if fuzzy_result:
                canonical, weight, _ = fuzzy_result
                await self._store_entry(
                    key, canonical, WordCategory.MISC, weight,
                    WordSource.FUZZY, verified=True,
                )
                async with self._lock:
                    self._cache[key] = fuzzy_result
                    self._index_dirty = True
                return fuzzy_result
        return word, 0.5, "PASSTHROUGH"

    async def correct_designation_tokens(
        self,
        tokens: list[str],
        supplier_profile=None,
    ) -> list[tuple[str, str, float]]:
        """
        Correct multiple designation tokens in one pass.
        Returns list of (original_token, corrected_token, confidence).
        Only corrects genuine words — codes and amounts pass through unchanged.
        """
        results: list[tuple[str, str, float]] = []
        for tok in tokens:
            corrected, conf, _src = await self.correct(
                tok, field_name="designation", supplier_profile=supplier_profile
            )
            results.append((tok, corrected, conf))
        return results

    async def normalize_text(
        self,
        text: str,
        field_name: str = "designation",
        supplier_profile=None,
    ) -> str:
        """
        Apply word_dictionary corrections to every whitespace-separated token in *text*.

        For each token:
          - Protected values (codes, amounts, dates, dimensions) are preserved unchanged.
          - Tokens found in word_dictionary (ignored=False) are replaced by canonical_form.
          - Unknown tokens that pass all guards but are not in the dictionary remain unchanged.

        No word is ever hardcoded — all corrections come from the database.
        """
        if not text or not text.strip():
            return text

        parts = re.split(r"(\s+)", text)
        output: list[str] = []

        for part in parts:
            if not part or re.match(r"^\s+$", part):
                output.append(part)
                continue
            corrected, _, _ = await self.correct(
                part,
                field_name=field_name,
                supplier_profile=supplier_profile,
            )
            output.append(corrected)

        return "".join(output)

    async def enrich_from_gpt(self, word: str, context: list[str]) -> str:
        """Single-word GPT enrichment (wraps batch call for backwards compat)."""
        if not is_dictionary_candidate(word, field_name="designation"):
            return word

        token = UnknownToken(raw_value=word, context_words=context)
        suggestions = await self.correct_unknown_tokens_with_llm([token], context={})

        if suggestions:
            s = suggestions[0]
            if s.should_add_to_dictionary and s.corrected_value != word and s.confidence >= 0.70:
                key = normalize_dictionary_key(word)
                capped = min(s.confidence, _MAX_GPT_WEIGHT)

                # BUG-3 FIX:
                await self._store_entry(
                    key, s.corrected_value, WordCategory.MISC,
                    capped, WordSource.LLM_SUGGESTED, verified=False,
                )
                async with self._lock:
                    self._cache[key] = (s.corrected_value, capped, "LLM_SUGGESTED")
                    self._index_dirty = True

                return s.corrected_value

        return word

    async def correct_unknown_tokens_with_llm(
        self,
        tokens: list[UnknownToken],
        context: dict,
    ) -> list[CorrectionSuggestion]:
        """
        Batch GPT correction. One API call for all tokens.
        Filters out protected values. Stores results with verified=False, weight≤0.75.
        All DB I/O runs outside self._lock (BUG-4 FIX).
        """
        if not tokens:
            return []

        to_correct: list[UnknownToken] = []
        known_results: dict[str, CorrectionSuggestion] = {}
        for tok in tokens:
            if is_protected_value(tok.raw_value, field_name=tok.field_name):
                known_results[tok.raw_value] = CorrectionSuggestion(
                    raw_value=tok.raw_value, corrected_value=tok.raw_value,
                    confidence=1.0, term_type="code",
                    should_add_to_dictionary=False, should_apply_now=False,
                    reason="Protected value — preserved unchanged",
                )
                continue
            if not is_dictionary_candidate(tok.raw_value, field_name=tok.field_name):
                known_results[tok.raw_value] = CorrectionSuggestion(
                    raw_value=tok.raw_value, corrected_value=tok.raw_value,
                    confidence=1.0, term_type="code",
                    should_add_to_dictionary=False, should_apply_now=False,
                    reason="Not a dictionary candidate — preserved unchanged",
                )
                continue

            key = normalize_dictionary_key(tok.raw_value)
            db_entry = await self._db_lookup(key)
            if db_entry and db_entry.verified and not db_entry.ignored:
                known_results[tok.raw_value] = CorrectionSuggestion(
                    raw_value=tok.raw_value, corrected_value=db_entry.canonical_form,
                    confidence=db_entry.weight, term_type="known",
                    should_add_to_dictionary=False, should_apply_now=True,
                    reason="Already in verified dictionary",
                )
                continue

            to_correct.append(tok)

        if not to_correct:
            return list(known_results.values())

        gpt_results: list[CorrectionSuggestion] = []
        try:
            prompt = _build_batch_correction_prompt(
                [{"raw_form": t.raw_value, "context": t.context_words[:5],
                  "field_name": t.field_name or "designation"} for t in to_correct],
                context,
            )
            gpt_results = await _call_gpt_batch_correction(prompt)
        except Exception as exc:
            logger.warning("word_dictionary_gpt_batch_failed error=%s", str(exc))
            for tok in to_correct:
                known_results[tok.raw_value] = CorrectionSuggestion(
                    raw_value=tok.raw_value, corrected_value=tok.raw_value,
                    confidence=0.3, term_type="unknown",
                    should_add_to_dictionary=False, should_apply_now=False,
                    reason="GPT batch failed",
                )
        # BUG-4 FIX:
        for s in gpt_results:
            if not s.should_add_to_dictionary:
                continue
            if is_protected_value(s.raw_value):
                continue
            if not is_dictionary_candidate(s.raw_value):
                continue
            if s.confidence < 0.70:
                continue  

            key = normalize_dictionary_key(s.raw_value)
            capped_weight = min(s.confidence, _MAX_GPT_WEIGHT)
            tok_supplier_id = next(
                (t.supplier_id for t in to_correct if t.raw_value == s.raw_value), None
            )
            existing = await self._db_lookup(key)
            if existing is not None:
                continue
            # Atomic upsert
            await self._store_entry(
                key, s.corrected_value, WordCategory.MISC,
                capped_weight, WordSource.LLM_SUGGESTED,
                verified=False, supplier_id=tok_supplier_id,
            )
            if s.corrected_value.lower() != key:
                async with self._lock:
                    self._cache[key] = (s.corrected_value, capped_weight, "LLM_SUGGESTED")
                    self._index_dirty = True



        all_results = list(known_results.values()) + gpt_results
        return all_results

    async def bulk_seed(
        self,
        word_pairs: list[tuple[str, str, WordCategory]] | None = None,
        with_variants: bool = True,
        batch_size: int = 200,
    ) -> int:
        """
        Seed the dictionary in batched bulk upserts.

        Idempotent: existing entries are never overwritten (ON CONFLICT DO NOTHING).
        Generates OCR variants automatically when with_variants=True.
        Returns the count of actually inserted rows.
        """
        if word_pairs is None:
            word_pairs = (
                build_full_seed_with_variants() if with_variants else _ALL_SEED_ENTRIES
            )
        seen: set[str] = set()
        rows: list[dict] = []
        for raw_key, canonical, category in word_pairs:
            key = normalize_dictionary_key(raw_key) if raw_key else ""
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append({
                "raw_form": key,
                "canonical_form": canonical,
                "category": category,
                "weight": 1.0,
                "source": WordSource.MANUAL,
                "verified": True,
                "ignored": False,
                "usage_count": 0,
            })

        inserted = 0
        async with AsyncSessionLocal() as db:
            for i in range(0, len(rows), batch_size):
                batch = rows[i : i + batch_size]
                stmt = (
                    pg_insert(WordDictionaryEntry)
                    .values(batch)
                    .on_conflict_do_nothing(index_elements=["raw_form"])
                )
                result = await db.execute(stmt)
                inserted += result.rowcount
            await db.commit()

        self._index_dirty = True

        return inserted

    async def update_usage(self, words: list[str]) -> None:
        normalized = [normalize_dictionary_key(w) for w in words if w and w.strip()]
        if not normalized:
            return
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(WordDictionaryEntry)
                .where(WordDictionaryEntry.raw_form.in_(normalized))
                .values(usage_count=WordDictionaryEntry.usage_count + 1)
            )
            await db.commit()

    async def export_stats(self) -> dict:
        """
        Return dictionary statistics using aggregate SQL queries.
        BUG-7 FIX:PostgreSQL computes all counts and distributions in a
        single round-trip per query with no data transferred to the application.
        """
        async with AsyncSessionLocal() as db:
            total = await db.scalar(
                select(func.count()).select_from(WordDictionaryEntry)
            ) or 0
            unverified = await db.scalar(
                select(func.count()).select_from(WordDictionaryEntry)
                .where(WordDictionaryEntry.verified == False) 
            ) or 0
            ignored_count = await db.scalar(
                select(func.count()).select_from(WordDictionaryEntry)
                .where(WordDictionaryEntry.ignored == True)   
            ) or 0
            src_rows = (await db.execute(
                select(WordDictionaryEntry.source, func.count().label("cnt"))
                .group_by(WordDictionaryEntry.source)
            )).all()
            by_source = {str(r[0]): int(r[1]) for r in src_rows}
            cat_rows = (await db.execute(
                select(WordDictionaryEntry.category, func.count().label("cnt"))
                .group_by(WordDictionaryEntry.category)
            )).all()
            by_category = {str(r[0]): int(r[1]) for r in cat_rows}

        return {
            "total_entries":      total,
            "unverified_entries": unverified,
            "ignored_entries":    ignored_count,
            "by_source":          by_source,
            "by_category":        by_category,
            "cache_size":         len(self._cache),
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _db_lookup(self, key: str) -> WordDictionaryEntry | None:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WordDictionaryEntry).where(WordDictionaryEntry.raw_form == key)
            )
            return result.scalar_one_or_none()

    async def _increment_usage(self, key: str) -> None:
        try:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(WordDictionaryEntry)
                    .where(WordDictionaryEntry.raw_form == key)
                    .values(usage_count=WordDictionaryEntry.usage_count + 1)
                )
                await db.commit()
        except Exception:
            pass

    async def _get_fuzzy_index(self) -> list[tuple[str, str]]:
        """
        Return the verified, non-ignored fuzzy index. Rebuilds from DB when dirty.
        BUG-6
        """
        async with self._lock:
            if not self._index_dirty and self._fuzzy_index is not None:
                return self._fuzzy_index
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(WordDictionaryEntry.raw_form, WordDictionaryEntry.canonical_form)
                .where(
                    WordDictionaryEntry.verified == True, 
                    WordDictionaryEntry.ignored  == False,  
                )
            )
            rows = result.all()
        new_index = [(r[0], r[1]) for r in rows]
        async with self._lock:
            self._fuzzy_index = new_index
            self._index_dirty = False

        return new_index

    async def _fuzzy_match(self, key: str) -> _CacheEntry | None:
        """
        Fuzzy match against the verified dictionary index.
        BUG-5 FIX:
        """
        index = await self._get_fuzzy_index()
        best: _CacheEntry | None = None
        best_score = 0.0
        for raw_form, canonical_form in index:
            dist = _lev_distance(key, raw_form)
            if dist > 2:
                continue
            ratio = fuzz.ratio(key, raw_form) / 100.0
            if ratio < 0.80:
                continue
            score = ratio * (1.0 - dist * 0.05)
            if score > best_score:
                best_score = score
                best = (canonical_form, min(score * 0.95, 0.95), "FUZZY")

        return best

    def clear_cache(self) -> int:
        """Clear all in-memory cached corrections. Returns number of entries cleared."""
        count = len(self._cache)
        self._cache.clear()
        self._index_dirty = True
        return count

    def invalidate_cache_key(self, raw_form: str) -> bool:
        """
        Remove a normalised key from the cache so the next call hits the DB.
        Accepts raw or already-normalised forms.
        Returns True if an entry was actually removed.
        """
        key = normalize_dictionary_key(raw_form)
        removed = self._cache.pop(key, None) is not None
        if removed:
            self._index_dirty = True
        return removed

    async def _store_entry(
        self,
        raw_form: str,
        canonical_form: str,
        category: WordCategory,
        weight: float,
        source: WordSource,
        verified: bool = True,
        ignored: bool = False,
        supplier_id: str | None = None,
    ) -> None:
        """
        Atomically upsert a dictionary entry using PostgreSQL ON CONFLICT DO UPDATE.

        BUG-1 FIX create a SINGLE insert_stmt and alias its .excluded once. Every
        reference to excluded columns in set_ must use this alias.
        BUG-1 FIX Update rules enforced by the DO UPDATE clause
        """
        try:
            async with AsyncSessionLocal() as db:
                insert_stmt = pg_insert(WordDictionaryEntry).values(
                    raw_form=raw_form,
                    canonical_form=canonical_form,
                    category=category,
                    weight=weight,
                    source=source,
                    verified=verified,
                    ignored=ignored,
                    supplier_id=supplier_id,
                    usage_count=1,
                )
                ex = insert_stmt.excluded

                stmt = insert_stmt.on_conflict_do_update(
                    index_elements=["raw_form"],
                    set_={
                        "canonical_form": sa_case(
                            (ex.weight > WordDictionaryEntry.weight, ex.canonical_form),
                            (
                                (~WordDictionaryEntry.verified) & ex.verified,
                                ex.canonical_form,
                            ),
                            else_=WordDictionaryEntry.canonical_form,
                        ),
                        "weight": func.greatest(WordDictionaryEntry.weight, ex.weight),
                        "source": sa_case(
                            (ex.weight > WordDictionaryEntry.weight, ex.source),
                            (
                                (~WordDictionaryEntry.verified) & ex.verified,
                                ex.source,
                            ),
                            else_=WordDictionaryEntry.source,
                        ),
                        "verified": WordDictionaryEntry.verified | ex.verified,
                        "ignored": WordDictionaryEntry.ignored & ex.ignored,
                        "supplier_id": func.coalesce(
                            ex.supplier_id, WordDictionaryEntry.supplier_id
                        ),
                        "updated_at": datetime.now(timezone.utc),
                    },
                    where=(WordDictionaryEntry.source != WordSource.MANUAL),
                )
                await db.execute(stmt)
                await db.commit()
            self.invalidate_cache_key(raw_form)

        except Exception as exc:
            logger.warning(
                "word_dictionary_store_failed raw=%s error=%s", raw_form, str(exc)
            )


# ── Batch GPT helpers ─────────────────────────────────────────────────────────

def _build_batch_correction_prompt(tokens: list[dict], context: dict) -> str:
    token_json = json.dumps(tokens, ensure_ascii=False, indent=2)
    doc_ctx = ""
    if context.get("supplier_name"):
        doc_ctx += f"Fournisseur : {context['supplier_name']}\n"
    if context.get("doc_type"):
        doc_ctx += f"Type de document : {context['doc_type']}\n"

    return f"""Tu es un correcteur OCR pour documents commerciaux B2B en français (Tunisie).
{doc_ctx}
Corrige uniquement les mots OCR bruités dans les désignations et les en-têtes de colonnes.

NE CORRIGE JAMAIS :
- codes articles (ex: P199420414, M400010432, BCF04H, DW36PT, S096)
- références produit (alphanumériques, ex: 4032185)
- numéros de facture, BL, BC (ex: FA-2025/0531, BL2460/2025)
- montants (ex: 6 576,000)
- dates (ex: 30/06/2025)
- quantités
- TVA, remises
- téléphones, matricules fiscaux, emails, RIB
- dimensions techniques (ex: 595X395X330, 1200*1000*980)
- codes avec slash type "C/C 595X395X330 F40"

Si le token ressemble à un code ou une valeur technique, retourne-le inchangé avec should_add=false.

Réponds UNIQUEMENT en JSON strict (sans markdown) :
{{
  "corrections": [
    {{
      "raw_form": "...",
      "canonical_form": "...",
      "category": "PRODUCT|UNIT|BRAND|ACTION|MATERIAL|DOCUMENT|HEADER|PAYMENT|MISC",
      "confidence": 0.0,
      "should_add": true,
      "should_apply_now": true
    }}
  ]
}}

Règles :
- confidence >= 0.70 et should_apply_now=true → insérer dans dictionnaire et utiliser la correction
- sinon → garder raw_form, ne pas corriger automatiquement
- weight = min(confidence, 0.75), source = "GPT"

Tokens à corriger :
{token_json}"""


async def _call_gpt_batch_correction(prompt: str) -> list[CorrectionSuggestion]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": getattr(settings, "llm_correction_model", settings.llm_model),
                "max_tokens": 1000,
                "temperature": 0.0,
                "messages": [{"role": "user", "content": prompt}],
            },
        )
        response.raise_for_status()
        raw_text = response.json()["choices"][0]["message"]["content"].strip()

    raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text, flags=re.MULTILINE)
    raw_text = re.sub(r"\s*```$", "", raw_text, flags=re.MULTILINE)
    parsed = json.loads(raw_text)
    results: list[CorrectionSuggestion] = []
    for item in parsed.get("corrections", []):
        conf = float(item.get("confidence", 0.3))
        results.append(CorrectionSuggestion(
            raw_value=item.get("raw_form", ""),
            corrected_value=item.get("canonical_form", item.get("raw_form", "")),
            confidence=conf,
            term_type=item.get("category", "MISC").lower(),
            should_add_to_dictionary=bool(item.get("should_add", False)) and conf >= 0.70,
            should_apply_now=bool(item.get("should_apply_now", False)) and conf >= 0.70,
            reason="",
        ))
    return results
word_dictionary = WordDictionary()