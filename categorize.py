"""
Transaction categorization.

Deliberately rules-first. Most bank descriptions are the same 40 vendors over
and over, and a regex table is faster, free, deterministic and auditable. The
model only sees the descriptions the rules could not match, which in practice
is a handful of rows per file.

Two things get tagged on every row:
  category  - payroll, cloud, marketing, revenue, financing, ...
  flow      - operating_out, operating_in, financing_in, financing_out

The flow split matters. A SAFE landing in the bank account is not revenue, and
counting it as one would understate burn badly in the month it closes.
"""

import json
import re

# category -> (flow, [regex patterns])
RULES = {
    "payroll":      ("operating_out", [r"\bGUSTO\b", r"\bRIPPLING\b", r"\bADP\b", r"PAYROLL", r"\bJUSTWORKS\b"]),
    "contractors":  ("operating_out", [r"\bDEEL\b", r"\bUPWORK\b", r"\bFIVERR\b", r"CONTRACTOR"]),
    "cloud":        ("operating_out", [r"\bAWS\b", r"AMAZON WEB", r"\bGCP\b", r"GOOGLE CLOUD", r"\bVERCEL\b",
                                       r"\bSUPABASE\b", r"\bHEROKU\b", r"\bCLOUDFLARE\b", r"\bDIGITALOCEAN\b"]),
    "software":     ("operating_out", [r"\bSLACK\b", r"\bNOTION\b", r"\bLINEAR\b", r"\bGITHUB\b", r"\bFIGMA\b",
                                       r"GOOGLE WORKSPACE", r"\bZOOM\b", r"\bHUBSPOT\b", r"\bATLASSIAN\b",
                                       r"\bDATADOG\b", r"\bSENTRY\b"]),
    "marketing":    ("operating_out", [r"GOOGLE ADS", r"LINKEDIN ADS", r"\bMETA ADS\b", r"REDDIT ADS",
                                       r"\bSPONSOR\b", r"\bMAILCHIMP\b", r"\bWEBFLOW\b"]),
    "facilities":   ("operating_out", [r"\bWEWORK\b", r"\bREGUS\b", r"CON EDISON", r"\bRENT\b", r"\bINDUSTRIOUS\b"]),
    "legal_admin":  ("operating_out", [r"\bCOOLEY\b", r"\bLLP\b", r"STRIPE ATLAS", r"\bCARTA\b", r"\bWILSON SONSINI\b",
                                       r"\bGUNDERSON\b", r"\bLEGALZOOM\b"]),
    "travel":       ("operating_out", [r"AIRLINES\b", r"\bAMTRAK\b", r"\bHOTEL\b", r"\bMARRIOTT\b", r"\bHILTON\b",
                                       r"\bUBER\b", r"\bLYFT\b", r"\bDELTA\b", r"\bUNITED\b"]),
    "revenue":      ("operating_in",  [r"STRIPE PAYOUT", r"\bWIRE IN\b.*(?<!SAFE )(?:CORP|INC|LLC|ENTERPRISES)",
                                       r"CUSTOMER PAYMENT", r"\bINVOICE\b"]),
    "financing":    ("financing_in",  [r"\bSAFE\b", r"CONVERTIBLE NOTE", r"SERIES [A-D]\b", r"\bEQUITY\b",
                                       r"\bVENTURE\b.*\bLP\b", r"\bSEED FUND\b"]),
    "other_opex":   ("operating_out", [r"\bAMAZON BUSINESS\b", r"\bSTAPLES\b", r"\bDOORDASH\b", r"\bOFFICE\b"]),
}

# Financing wins over everything. A wire from "VERTEX SEED FUND I LP" would
# otherwise get swept up by the revenue pattern for incoming wires.
PRIORITY = ["financing", "payroll", "contractors", "cloud", "software", "marketing",
            "facilities", "legal_admin", "travel", "revenue", "other_opex"]

FLOW_BY_CATEGORY = {cat: flow for cat, (flow, _patterns) in RULES.items()}


def classify_one(description, amount):
    """Return (category, flow) or (None, None) if no rule matched."""
    d = description.upper()
    for cat in PRIORITY:
        flow, patterns = RULES[cat]
        if any(re.search(p, d) for p in patterns):
            # Direction of the actual cash movement overrides the table default.
            # A refund from AWS is money in, not an operating outflow.
            if cat == "financing":
                flow = "financing_in" if amount > 0 else "financing_out"
            elif amount > 0 and flow == "operating_out":
                flow = "operating_in"
            return cat, flow
    return None, None


def classify_all(df, llm=None, verbose=True):
    """
    Adds `category` and `flow` columns to df. Anything the rules miss is sent
    to the model in one batched call, if a model is available.
    """
    results = [classify_one(d, a) for d, a in zip(df["description"], df["amount"])]
    df["category"] = [r[0] for r in results]
    df["flow"] = [r[1] for r in results]

    unknown = sorted(df.loc[df["category"].isna(), "description"].unique())
    if not unknown:
        if verbose:
            print("categorization: all rows matched by rules")
        return df

    if verbose:
        print(f"categorization: {len(unknown)} description(s) unmatched by rules")

    mapping = {}
    if llm is not None and llm.available:
        mapping = _ask_model(llm, unknown)

    for desc in unknown:
        cat = mapping.get(desc)
        mask = df["description"] == desc
        if cat in FLOW_BY_CATEGORY:
            df.loc[mask, "category"] = cat
            df.loc[mask, "flow"] = [
                _direction(cat, a) for a in df.loc[mask, "amount"]
            ]
        else:
            df.loc[mask, "category"] = "uncategorized"
            df.loc[mask, "flow"] = [
                "operating_in" if a > 0 else "operating_out" for a in df.loc[mask, "amount"]
            ]
    return df


def _direction(cat, amount):
    flow = FLOW_BY_CATEGORY[cat]
    if cat == "financing":
        return "financing_in" if amount > 0 else "financing_out"
    if amount > 0 and flow == "operating_out":
        return "operating_in"
    return flow


def _ask_model(llm, descriptions):
    """One call, all unknowns. Returns {description: category}."""
    cats = ", ".join(FLOW_BY_CATEGORY.keys())
    prompt = (
        "Classify each bank transaction description into exactly one category.\n"
        f"Allowed categories: {cats}\n\n"
        "Rules:\n"
        "- 'financing' is for investor money: SAFEs, notes, priced rounds, venture debt.\n"
        "- 'revenue' is customer payments only.\n"
        "- If you are not confident, use other_opex.\n\n"
        "Descriptions:\n"
        + "\n".join(f"- {d}" for d in descriptions)
        + '\n\nReturn only a JSON object mapping each description exactly as written '
          'to its category. No prose, no code fences.'
    )
    # Low temperature and JSON mode: this is a classification task, not
    # writing. We want the same vendor mapped the same way every run.
    raw = llm.complete(prompt, temperature=0.1, json_mode=True)
    if not raw:
        return {}
    try:
        cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        return json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        print("categorization: model reply was not valid JSON, falling back to uncategorized")
        return {}
