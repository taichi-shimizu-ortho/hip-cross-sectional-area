"""Filter the saved schedule JSON to hip cases and provisionally match FAI/THA.

Run ``uv run python match_joa_cohorts.py --check-only`` before writing outputs.
This does not modify the original workbook, raw JSON or normalized JSON.
"""

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata
from zoneinfo import ZoneInfo

import numpy as np
from scipy import __version__ as scipy_version
from scipy.optimize import linear_sum_assignment, minimize
from scipy.special import expit

from hip_paths import JOA_DIR, JOA_ANALYSIS_PLAN, from_home

START, END = date(2016, 11, 1), date(2026, 10, 31)
HIP = {"股", "股関節", "hip"}


def write_json(value, path):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def text(value):
    return "" if value is None else str(value).strip()


def numeric(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def column_number(col):
    result = 0
    for char in col:
        result = result * 26 + ord(char) - 64
    return result


def column_name(number):
    value = ""
    while number:
        number, rem = divmod(number - 1, 26)
        value = chr(65 + rem) + value
    return value


def surgery_group(diagnosis, procedure):
    fai = bool(re.search(r"(?i)\bFAI\b|インピンジメント", diagnosis))
    tha = bool(re.search(r"(?i)\bTHA\b|人工股関節", procedure))
    revision = bool(re.search(r"(?i)revision|re[- ]?THA|再置換|再THA", procedure))
    arthroscopy = bool(re.search(r"(?i)\bAS\b|arthroscop|scope|関節鏡|鏡視", procedure))
    oa = bool(re.search(r"(?i)\bOA\b|変形性股|coxarthrosis", diagnosis))
    if fai and tha:
        return None, "conflicting_FAI_and_THA"
    if revision:
        return None, "revision_arthroplasty"
    if fai and arthroscopy:
        return "FAI", None
    if tha and oa:
        return "THA", None
    if fai:
        return None, "FAI_without_explicit_arthroscopy"
    if tha:
        return None, "THA_without_explicit_OA"
    return None, "other_hip_procedure_or_diagnosis"


def filter_hips(normalized, as_of):
    retained, review, exclusions = [], [], []
    counts = Counter()
    for sheet in normalized["sheets"]:
        # Annual sheets contain the surgical register. Auxiliary sheets are
        # retained in raw JSON, but not mixed into this register as extra cases.
        annual = bool(re.fullmatch(r"20\d{2}(?: surgery)?", unicodedata.normalize("NFKC", sheet["name"]).strip()))
        for row in sheet["rows"]:
            ref = {"sheet": sheet["name"], "row": row["source_row"]}
            counts["input_rows"] += 1
            reason = None
            if not annual:
                reason = "auxiliary_sheet_not_surgical_register"
            elif row["row_kind"] == "header":
                reason = "header_row"
            values = row["values"]
            # In modern annual sheets surgery date is column A. Use typed dates
            # only; never carry a date forward from an adjacent row.
            day = parse_date(values.get("A")) if row["value_types"].get("A") in {"datetime", "date", "iso_date"} else None
            if reason is None and day is not None and not START <= day <= END:
                reason = "outside_requested_period"
            if reason:
                exclusions.append({**ref, "reason": reason})
                counts[reason] += 1
                continue
            clinical = {col: text(v) for col, v in values.items() if 8 <= column_number(col) <= 16}
            hip_columns = [col for col, v in clinical.items() if v.lower() in HIP]
            strong_keyword = any(re.search(r"(?i)\bFAI\b|THA|股関節|インピンジメント", v) for v in clinical.values())
            if day is None:
                if hip_columns or strong_keyword:
                    review.append({**ref, "reason": "hip_evidence_but_missing_or_invalid_surgery_date", "source_values": values})
                    counts["review_missing_date"] += 1
                else:
                    exclusions.append({**ref, "reason": "undated_noncase_or_unresolved_row"})
                    counts["undated_noncase_or_unresolved_row"] += 1
                continue
            if len(hip_columns) != 1:
                if strong_keyword or len(hip_columns) > 1:
                    review.append({**ref, "reason": "hip_diagnosis_or_procedure_without_unambiguous_hip_site", "source_values": values})
                    counts["review_ambiguous_site"] += 1
                else:
                    exclusions.append({**ref, "reason": "nonhip_or_no_explicit_hip_evidence"})
                    counts["nonhip_or_no_explicit_hip_evidence"] += 1
                continue
            site_col = hip_columns[0]
            site_index = column_number(site_col)
            get = lambda offset: values.get(column_name(site_index + offset))
            diagnosis, procedure = text(get(1)), text(get(2))
            group, group_reason = surgery_group(diagnosis, procedure)
            flags = []
            age = numeric(get(-3))
            sex = {"M": "M", "F": "F", "男": "M", "女": "F", "男性": "M", "女性": "F"}.get(text(get(-2)).upper())
            side = {"R": "R", "L": "L", "B": "B", "両": "B", "両側": "B", "右": "R", "左": "L"}.get(text(get(-1)).upper())
            field_map = row["header_field_map"]
            id_col = next((c for c, f in field_map.items() if f == "patient_id"), None)
            patient_id = text(values.get(id_col)) if id_col else ""
            if patient_id.endswith(".0") and re.fullmatch(r"\d+\.0", patient_id):
                patient_id = patient_id[:-2]
            if not re.fullmatch(r"\d+", patient_id):
                flags.append("missing_or_invalid_patient_id")
            if age is None or not 0 <= age <= 120:
                age = None
                flags.append("missing_or_invalid_age")
            if sex is None:
                flags.append("missing_or_invalid_sex")
            if side is None:
                flags.append("unrecognized_laterality")
            # Detect demographic contradictions instead of correcting them.
            dob_col = next((c for c, f in field_map.items() if f == "date_of_birth"), None)
            dob = parse_date(values.get(dob_col)) if dob_col else None
            if dob is not None and age is not None:
                derived_age = day.year - dob.year - ((day.month, day.day) < (dob.month, dob.day))
                if abs(derived_age - age) > 1:
                    flags.append("age_and_birth_date_disagree")
            if day > as_of:
                flags.append("future_scheduled_surgery")
            # Explicitly record use of a site-anchored layout instead of a stale
            # annual header; this is never based on patient outcome values.
            if field_map.get(column_name(site_index - 3)) != "age" or field_map.get(column_name(site_index + 2)) != "procedure":
                flags.append("site_anchored_layout_differs_from_header")
            case_id = f"{sheet['name'].strip()}:{row['source_row']}"
            retained.append({
                "case_id": case_id, "source": ref, "surgery_date": day.isoformat(),
                "patient_id": patient_id or None, "age": age, "sex": sex,
                "laterality": side, "anatomical_site": "hip", "site_source_column": site_col,
                "diagnosis": diagnosis, "procedure": procedure,
                "cohort_candidate": group, "noncandidate_reason": group_reason,
                "BMI": None, "eligibility_status": "provisional_schedule_record",
                "flags": flags, "source_values": values,
            })
            counts["retained_hip_records"] += 1
    assert counts["input_rows"] == len(retained) + len(review) + len(exclusions)
    return retained, review, exclusions, dict(counts)


def select_index_cases(cases):
    candidates = [c for c in cases if c["cohort_candidate"] in {"FAI", "THA"}]
    excluded, selected = {}, []
    grouped = defaultdict(list)
    for case in candidates:
        if "missing_or_invalid_patient_id" in case["flags"]:
            excluded[case["case_id"]] = "missing_patient_identifier"
        else:
            grouped[case["patient_id"]].append(case)
    for patient_cases in grouped.values():
        groups = {c["cohort_candidate"] for c in patient_cases}
        same_day = defaultdict(set)
        for c in patient_cases:
            same_day[c["surgery_date"]].add(c["laterality"])
        bilateral = any("B" in sides or {"R", "L"} <= sides for sides in same_day.values())
        if len(groups) > 1 or bilateral:
            reason = "patient_in_both_cohorts" if len(groups) > 1 else "identified_simultaneous_bilateral_patient"
            for c in patient_cases:
                excluded[c["case_id"]] = reason
            continue
        ordered = sorted(patient_cases, key=lambda c: (c["surgery_date"], c["case_id"]))
        index = ordered[0]
        for later in ordered[1:]:
            excluded[later["case_id"]] = "later_or_duplicate_operation_same_patient"
        invalid = {"missing_or_invalid_age", "missing_or_invalid_sex", "age_and_birth_date_disagree", "future_scheduled_surgery", "unrecognized_laterality"} & set(index["flags"])
        if invalid:
            excluded[index["case_id"]] = ";".join(sorted(invalid))
        else:
            selected.append(index)
    return candidates, selected, excluded


def match_cases(cases):
    groups = np.array([c["cohort_candidate"] == "FAI" for c in cases], dtype=int)
    if len(cases) < 4 or len(set(groups)) != 2:
        raise ValueError("Both cohorts need enough complete, unique patients to estimate propensity scores.")
    ages = np.array([c["age"] for c in cases], dtype=float)
    female = np.array([c["sex"] == "F" for c in cases], dtype=int)
    age_mean, age_sd = float(ages.mean()), float(ages.std(ddof=0))
    if age_sd == 0:
        raise ValueError("Age has no variation; the specified score model cannot be fit.")
    z_age = (ages - age_mean) / age_sd
    # Explicit elementwise likelihood/gradient avoids platform BLAS warnings
    # and supplies an independent, auditable convergence check.
    def objective(beta):
        linear = beta[0] + beta[1] * z_age + beta[2] * female
        residual = expit(linear) - groups
        loss = float(np.mean(np.logaddexp(0, linear) - groups * linear))
        gradient = np.array([residual.mean(), (residual * z_age).mean(), (residual * female).mean()])
        return loss, gradient
    fit = minimize(objective, np.zeros(3), jac=True, method="BFGS", options={"gtol": 1e-10, "maxiter": 2000})
    max_gradient = float(np.max(np.abs(objective(fit.x)[1])))
    if not np.isfinite(fit.x).all() or max_gradient > 1e-7:
        raise ValueError("The logistic likelihood did not converge to a finite stationary point.")
    logits = fit.x[0] + fit.x[1] * z_age + fit.x[2] * female
    scores = expit(logits)
    if not np.isfinite(logits).all() or not np.isfinite(scores).all():
        raise ValueError("Non-finite propensity scores.")
    pooled = math.sqrt((float(logits[groups == 1].var(ddof=1)) + float(logits[groups == 0].var(ddof=1))) / 2)
    caliper = 0.2 * pooled
    allowed = np.zeros(len(cases), dtype=bool)
    support = {}
    for sex in ["M", "F"]:
        a = np.array([i for i, c in enumerate(cases) if c["sex"] == sex and groups[i] == 1], dtype=int)
        b = np.array([i for i, c in enumerate(cases) if c["sex"] == sex and groups[i] == 0], dtype=int)
        if len(a) and len(b):
            lower, upper = max(float(logits[a].min()), float(logits[b].min())), min(float(logits[a].max()), float(logits[b].max()))
            support[sex] = {"lower_logit": lower, "upper_logit": upper, "overlap_exists": lower <= upper}
            for i, c in enumerate(cases):
                if c["sex"] == sex and lower <= logits[i] <= upper:
                    allowed[i] = True
    fai = np.flatnonzero((groups == 1) & allowed)
    tha = np.flatnonzero((groups == 0) & allowed)
    pairs = []
    if len(fai) and len(tha):
        distances = np.abs(logits[fai, None] - logits[tha][None, :])
        same_sex = female[fai, None] == female[tha][None, :]
        valid = same_sex & (distances <= caliper + 1e-12)
        # Every FAI row gets either a real THA or a unique dummy assignment.
        # A dummy penalty larger than all possible real-distance savings makes
        # cardinality primary, then minimizes total distance at that cardinality.
        unmatched_cost = (len(fai) + 1) * (max(caliper, 1.0) + 1)
        cost = np.full((len(fai), len(tha) + len(fai)), unmatched_cost)
        cost[:, :len(tha)] = np.where(valid, distances, unmatched_cost * (len(fai) + 2))
        row_indices, col_indices = linear_sum_assignment(cost)
        for row, col in zip(row_indices, col_indices):
            if col < len(tha) and valid[row, col]:
                i, j = int(fai[row]), int(tha[col])
                pairs.append({"pair_id": len(pairs) + 1, "FAI_case_id": cases[i]["case_id"],
                              "THA_case_id": cases[j]["case_id"], "FAI_index": i, "THA_index": j,
                              "sex": cases[i]["sex"], "FAI_age": cases[i]["age"], "THA_age": cases[j]["age"],
                              "absolute_age_difference_years": abs(cases[i]["age"] - cases[j]["age"]),
                              "absolute_logit_distance": float(distances[row, col])})
    matched = {index for pair in pairs for index in [pair["FAI_index"], pair["THA_index"]]}
    scored = []
    for i, c in enumerate(cases):
        scored.append({k: c[k] for k in ["case_id", "patient_id", "surgery_date", "cohort_candidate", "age", "sex"]}
                      | {"propensity_score_FAI": float(scores[i]), "logit_propensity_score_FAI": float(logits[i]),
                         "in_sex_specific_common_support": bool(allowed[i]), "matched": i in matched})
    balance = []
    for name, array in [("age_years", ages), ("female_proportion", female.astype(float))]:
        x, y = array[groups == 1], array[groups == 0]
        denominator = math.sqrt((float(x.var(ddof=1)) + float(y.var(ddof=1))) / 2)
        after_x = array[[p["FAI_index"] for p in pairs]]
        after_y = array[[p["THA_index"] for p in pairs]]
        for label, a, b in [("before", x, y), ("after", after_x, after_y)]:
            delta = float(a.mean() - b.mean()) if len(a) and len(b) else None
            smd = None if delta is None else (delta / denominator if denominator else (0.0 if delta == 0 else None))
            balance.append({"variable": name, "stage": label, "FAI_n": len(a), "THA_n": len(b),
                            "FAI_mean": float(a.mean()) if len(a) else None, "THA_mean": float(b.mean()) if len(b) else None,
                            "FAI_SD": float(a.std(ddof=1)) if len(a)>1 else None, "THA_SD": float(b.std(ddof=1)) if len(b)>1 else None,
                            "SMD": smd, "absolute_SMD": abs(smd) if smd is not None else None,
                            "prematching_pooled_SD_denominator": denominator})
    # No patient or control can appear in more than one pair.
    assert len(matched) == 2 * len(pairs)
    assert len({c["patient_id"] for c in cases}) == len(cases)
    assert all(p["absolute_logit_distance"] <= caliper + 1e-12 for p in pairs)
    return {"model": {"outcome": "FAI=1, THA=0", "covariates": ["age", "sex"], "BMI_included": False,
                      "scipy_version": scipy_version, "penalty": None,
                      "optimizer": "BFGS with analytic gradient of the mean binomial negative log likelihood",
                      "maximum_absolute_likelihood_gradient": max_gradient,
                      "age_standardization_mean": age_mean, "age_standardization_SD": age_sd,
                      "intercept": float(fit.x[0]),
                      "coefficients": {"standardized_age": float(fit.x[1]), "female": float(fit.x[2])},
                      "caliper_logit": caliper, "caliper_pooled_SD_multiplier": 0.2,
                      "algorithm": "Maximum-cardinality then minimum-total-distance assignment without replacement; exact sex",
                      "common_support_by_sex": support},
            "scored_cases": scored, "pairs": pairs, "balance": balance,
            "outside_common_support": int((~allowed).sum()),
            "unmatched_inside_common_support": int(allowed.sum()) - 2 * len(pairs)}


LIMITATIONS = [
    "This is provisional matching of surgery-schedule records, not a verified final research cohort. Completed operations, CT availability/coverage, end-stage OA, and all exclusions require chart and image review.",
    "BMI, height and weight are absent from the source workbook. BMI was omitted with the user's explicit authorization. Age/sex matching does not control BMI or body-size-related confounding.",
    "Only explicit hip-site rows are retained automatically. Rows with conflicting site, diagnosis or procedure evidence and missing dates are quarantined for review, which may omit genuine cases until corrected.",
    "Annual column layouts change and some recorded demographics conflict. Site-anchored extraction is audited; ambiguous age/sex and age/birth-date contradictions are excluded from matching rather than repaired or imputed.",
    "FAI requires an explicit FAI diagnosis and arthroscopy notation; THA requires explicit THA and OA notation. These text rules cannot establish radiographic disease severity, operative indications or freedom from neuromuscular disease.",
    "The provisional analysis uses the earliest eligible operation per identified patient. Cross-cohort patients, identified simultaneous bilateral cases and later operations are omitted. Missing identifiers, unrecorded bilateral procedures or inconsistent IDs may affect deduplication.",
    "FAI and THA have different indications and age distributions. Limited common support can substantially reduce the sample, and the matched subset may not represent either entire clinical population.",
    "The period was expanded from the application's April 2021-March 2024 window to November 2016-October 2026. This should be recorded as a protocol change and checked against the approved study scope. Calendar-year changes in care and imaging are not adjusted by this age/sex model.",
    "The requested end date is after the analysis date. Future scheduled operations are retained in the period-filtered data but excluded from current matching; two-year outcome follow-up is unavailable for recent operations.",
    "A logistic model with linear age and sex cannot remove unmeasured confounding or establish causal comparability. A small standardized mean difference is a balance diagnostic, not proof that the groups are exchangeable.",
    "The 64-per-group sample target concerns the application's independent mean comparison with d=0.5. It does not guarantee power for this matched analysis, multiple PROMs, regression, ROC or reliability analyses. Outcome analyses must account for pair dependence and incomplete follow-up.",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normalized-json", type=Path, default=JOA_DIR / "surgery_schedule.normalized.json")
    parser.add_argument("--out-dir", type=Path, default=JOA_DIR)
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(ZoneInfo("Asia/Tokyo")).date())
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    normalized = json.loads(args.normalized_json.expanduser().read_text(encoding="utf-8"))
    cases, review, excluded, filtering = filter_hips(normalized, args.as_of)
    candidates, selected, candidate_exclusions = select_index_cases(cases)
    matched = match_cases(selected)
    metadata = {"created_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
                "as_of": args.as_of.isoformat(), "surgery_period_inclusive": [START.isoformat(), END.isoformat()],
                "source_normalized_json": from_home(args.normalized_json),
                "source_normalized_sha256": hashlib.sha256(args.normalized_json.expanduser().read_bytes()).hexdigest(),
                "analysis_plan": from_home(JOA_ANALYSIS_PLAN), "status": "provisional"}
    summary = {"filtering": filtering,
               "retained_hip_records_by_year": dict(sorted(Counter(c["surgery_date"][:4] for c in cases).items())),
               "candidate_records_by_group": dict(Counter(c["cohort_candidate"] for c in candidates)),
               "unique_complete_index_patients_by_group": dict(Counter(c["cohort_candidate"] for c in selected)),
               "candidate_exclusion_reasons": dict(Counter(candidate_exclusions.values())),
               "matched_pairs": len(matched["pairs"]),
               "meets_64_per_group_design_target": len(matched["pairs"]) >= 64,
               "outside_common_support": matched["outside_common_support"],
               "unmatched_inside_common_support": matched["unmatched_inside_common_support"],
               "retained_flags": dict(Counter(f for c in cases for f in c["flags"])),
               "balance": matched["balance"]}
    if not args.check_only:
        out = args.out_dir.expanduser()
        out.mkdir(parents=True, exist_ok=True)
        write_json({**metadata, "stage": "hip_only_period_filtered", "summary": summary,
                    "cases": cases}, out / "surgery_schedule.cleaned.json")
        write_json({**metadata, "review_records": review, "removed_source_references": excluded,
                    "candidate_exclusions": candidate_exclusions}, out / "hip_cases.review.json")
        write_json({**metadata, "summary": summary, **matched, "limitations": LIMITATIONS,
                    "references": ["https://pmc.ncbi.nlm.nih.gov/articles/PMC3120982/", "https://pmc.ncbi.nlm.nih.gov/articles/PMC3144483/"]}, out / "cohort_matching.json")
        report = ["# Provisional FAI and THA matching", "",
                  f"Surgery period: {START.isoformat()} through {END.isoformat()}, inclusive. Analysis date: {args.as_of.isoformat()}.", "",
                  f"Retained hip surgery records: {len(cases)}. Records requiring site/date review: {len(review)}.",
                  f"Candidate records: {json.dumps(summary['candidate_records_by_group'])}.",
                  f"Unique complete index patients before common-support restriction: {json.dumps(summary['unique_complete_index_patients_by_group'])}.",
                  f"Matched pairs: {len(matched['pairs'])}; {len(matched['pairs'])} patients per group.",
                  f"Outside sex-specific common support: {matched['outside_common_support']}. Unmatched within support: {matched['unmatched_inside_common_support']}.", "",
                  "## Method", "",
                  "Unpenalized logistic regression estimates P(FAI) using age and sex. BMI is omitted as authorized. Matching is 1:1 without replacement, exact on sex, restricted to sex-specific common support, maximizing pair count before minimizing total logit distance.",
                  f"Caliper: 0.2 times the pooled within-group SD of the logit propensity score ({matched['model']['caliper_logit']:.6f} logit units).", "",
                  "| Covariate | Stage | FAI mean | THA mean | Absolute SMD |", "|---|---|---:|---:|---:|"]
        for b in matched["balance"]:
            fmt = lambda v: "unavailable" if v is None else f"{v:.4f}"
            report.append(f"| {b['variable']} | {b['stage']} | {fmt(b['FAI_mean'])} | {fmt(b['THA_mean'])} | {fmt(b['absolute_SMD'])} |")
        if matched["pairs"]:
            gaps = [p["absolute_age_difference_years"] for p in matched["pairs"]]
            report += ["", f"Pair age differences: median {np.median(gaps):.1f} years; maximum {max(gaps):.1f} years."]
        report += ["", "## Limitations", ""] + [f"- {s}" for s in LIMITATIONS]
        report += ["", "## Files and references", "", "The source workbook and raw JSON remain unchanged. The cleaned JSON contains only explicit hip cases within the requested period; ambiguous rows are in hip_cases.review.json. cohort_matching.json contains scores, pair IDs, model coefficients, balance diagnostics and limitations.",
                   "", "Caliper reference: https://pmc.ncbi.nlm.nih.gov/articles/PMC3120982/", "General propensity-score limitations: https://pmc.ncbi.nlm.nih.gov/articles/PMC3144483/", ""]
        (out / "matching_report.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
