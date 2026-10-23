"""Record the JOA application's study settings outside the public repository.

Run with ``uv run python configure_joa_study.py``. This reads the application,
checks that it matches the implemented settings, and verifies its sample size
with a noncentral t distribution. It never modifies source documents or data.
"""

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from zoneinfo import ZoneInfo

from scipy import __version__ as scipy_version
from scipy.optimize import brentq
from scipy.stats import nct, t

from hip_paths import INPUT_DIR, JOA_DIR, JOA_ANALYSIS_PLAN, from_home


def read_application(path):
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    if root.findall(".//w:ins", ns) or root.findall(".//w:del", ns):
        raise ValueError("申請書に未確定の変更履歴があります。採用する版を確認してください。")
    paragraphs = [
        "".join(node.text or "" for node in p.findall(".//w:t", ns))
        for p in root.findall(".//w:p", ns)
    ]
    text = unicodedata.normalize("NFKC", "\n".join(paragraphs))
    # Fail rather than silently reusing old settings when the application changes.
    compact = re.sub(r"\s+", "", text)
    required = [
        "2021年4月から2024年3月", "両側同時手術例", "再置換術症例",
        "神経筋疾患", "上前腸骨棘から膝関節レベル", "年齢、性別、BMI",
        "1対1", "有意水準5%", "検出力80%", "両側検定", "d=0.5",
        "各群約64例", "計約128例", "120~150例",
    ]
    missing = [value for value in required if value not in compact]
    if missing:
        raise ValueError(f"申請書と設定の照合に失敗しました: {missing}")


def two_sample_power(n, effect_size=0.5, alpha=0.05):
    """Two-sided equal-variance independent t test, equal group sizes."""
    df = 2 * n - 2
    critical = t.ppf(1 - alpha / 2, df)
    noncentrality = effect_size * math.sqrt(n / 2)
    result = float(nct.sf(critical, df, noncentrality)
                   + nct.cdf(-critical, df, noncentrality))
    if not math.isfinite(result):
        raise ValueError("検出力計算で有限値が得られませんでした。")
    return result


def configure(application):
    read_application(application)
    continuous_n = brentq(lambda n: two_sample_power(n) - 0.8, 60, 70)
    n = math.ceil(continuous_n)
    if n != 64 or not two_sample_power(n - 1) < 0.8 <= two_sample_power(n):
        raise ValueError("申請書の64例/群を再現できませんでした。")
    return {
        "schema_version": 2,
        "language": "en",
        "study_objectives": {
            "primary": "Evaluate associations of preoperative three-dimensional hip muscle volume and fatty degeneration with postoperative patient-reported outcomes after arthroscopic surgery for FAI and THA for end-stage hip osteoarthritis.",
            "secondary": [
                "Evaluate associations with gait function and hip abductor strength.",
                "Assess measurement reproducibility across observers using the intraclass correlation coefficient (ICC).",
                "Explore cutoffs and prediction models for poor postoperative outcomes.",
            ],
            "design": "Retrospective two-cohort study with a user-amended surgery period and age/sex-only matching pending BMI availability.",
        },
        "created_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
        "application": {
            "path": from_home(application),
            "sha256": hashlib.sha256(application.read_bytes()).hexdigest(),
            "section": "Research plan",
        },
        "cohort": {
            "surgery_date_start_inclusive": "2016-11-01",
            "surgery_date_end_inclusive": "2026-10-31",
            "original_application_period": {"start_inclusive": "2021-04-01", "end_inclusive": "2024-03-31"},
            "period_amendment_source": "User instruction; start explicitly confirmed as 1 November 2016.",
            "site_filter": "Hip cases only; remove non-hip and out-of-period records from the cleaned dataset while retaining the source workbook and raw export.",
            "groups": {"FAI": "Arthroscopic hip surgery for femoroacetabular impingement", "THA": "Total hip arthroplasty for end-stage hip osteoarthritis; revision arthroplasty excluded"},
            "exclusions": ["Simultaneous bilateral surgery", "Revision arthroplasty", "Neuromuscular disease"],
            "analysis_unit": "patient",
            "analysis_unit_note": "The application describes patients. Selection of repeated or staged bilateral operations remains unspecified; spreadsheet rows must not be counted as unique patients without review.",
            "repeated_surgery_selection_rule": "Provisional implementation: earliest eligible operation per patient in the period. Exclude cross-cohort patients and identified simultaneous bilateral surgery from matching; retain the audit trail.",
        },
        "sample_size": {
            "test": "independent_two_sample_t_test_equal_variance",
            "alternative": "two-sided",
            "alpha": 0.05,
            "power": 0.8,
            "cohens_d": 0.5,
            "allocation_ratio_THA_to_FAI": 1,
            "required_analyzable_per_group": n,
            "required_analyzable_total": 2 * n,
            "prematching_target_per_group_range": [120, 150],
            "prematching_target_total_range": [240, 300],
            "calculation": {
                "method": "noncentral t distribution; two-sided rejection tails",
                "scipy_version": scipy_version,
                "continuous_n_per_group": continuous_n,
                "power_at_63_per_group": two_sample_power(63),
                "power_at_64_per_group": two_sample_power(64),
                "reference": "https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestIndPower.solve_power.html",
            },
            "scope": "Design requirement for the application's independent two-group mean comparison. This does not independently establish power for matched analyses, regression, ROC analysis, or ICC estimation.",
            "recruitment_note": "The application specifies a range of approximately 120 to 150 patients per group before matching to allow for matching losses and missing postoperative assessments. No single target within that range has been selected.",
        },
        "matching": {
            "method": "propensity_score", "ratio": "1:1",
            "covariates": ["age", "sex"],
            "original_application_covariates": ["age", "sex", "BMI"],
            "BMI_omission": "User explicitly authorized proceeding without BMI because BMI, height and weight are absent from the supplied workbook.",
            "score_model": "Unpenalized logistic regression: P(FAI) from standardized age and sex.",
            "algorithm": "Maximum-cardinality, minimum-total-logit-distance 1:1 matching; exact matching on sex; restrict to sex-specific common support.",
            "caliper": {"scale": "logit_propensity_score", "pooled_within_group_SD_multiplier": 0.2},
            "replacement": False,
            "balance_diagnostic": "Absolute standardized mean differences for age and sex before/after matching, using the prematching pooled SD as denominator; 0.1 as a diagnostic threshold.",
            "status": "Provisional schedule-based cohort until surgery, diagnosis, imaging and outcome eligibility are clinically verified.",
        },
        "measurements": {
            "ct_extent": "From the anterior superior iliac spine to the knee joint level",
            "exposures": ["Muscle volume", "Body-size-adjusted muscle volume", "Intramuscular fat fraction on noncontrast CT", "Goutallier classification on preoperative MRI"],
            "volume_normalization_formula": None,
            "ct_fat_HU_thresholds": None,
            "primary_domain": "Postoperative patient-reported outcome measures (PROMs)",
            "PROMs_listed": ["mHHS", "NAHS", "VHS", "iHOT-12", "HOS"],
            "primary_PROM": None, "primary_timepoint_months": None,
            "followup_months": [3, 6, 12, 24],
            "secondary": ["Presence of limping", "Trendelenburg sign", "Hip abductor strength"],
            "morphology": ["Center-edge angle", "Sharp angle", "Vertical-center-anterior angle", "Femoral neck anteversion angle", "Alpha angle (FAI cohort only)"],
            "reliability": "ICC across multiple observers; ICC model and observer count unspecified",
        },
        "analyses_planned": ["Compare outcomes between groups defined by muscle atrophy and fatty degeneration", "Multivariable regression", "ROC analysis, cutoff estimation, and prediction modeling", "ICC reliability assessment", "Propensity score matching of the FAI and THA cohorts"],
        "unresolved_before_outcome_analysis": [
            "Select the primary PROM and primary follow-up timepoint, and define multiplicity handling.",
            "Define the analysis unit and selection rules for repeat operations and staged bilateral surgery.",
            "Define the analysis population and handling of missing PROMs.",
            "Define body-size normalization, CT fat HU thresholds, and atrophy/fatty-degeneration group thresholds.",
            "Confirm provisional matching choices and use outcome analyses that account for matched pairs.",
            "Define poor outcome, regression model complexity, and internal validation procedures.",
            "Specify the ICC model, observer count, and repeat measurement plan.",
        ],
        "data_processing": {
            "sequence": ["Export the original Excel cell data to raw JSON", "Create a separate cleaned JSON from the raw JSON", "Review data-quality flags and confirm eligibility before statistical analysis"],
            "source_excel_policy": "Read only; never modify the source workbook.",
            "raw_json_policy": "Preserve all worksheets, source cell coordinates, stored values, formulas and cached results before cleaning. Omit formatting-only empty cells, while recording worksheet dimensions and the omitted-cell count.",
            "cleaning_policy": "After raw JSON export, normalize text/dates and retain only hip records dated 2016-11-01 through 2026-10-31 in the cleaned dataset. Quarantine ambiguous records; record every exclusion with source references. Anchor changing annual layouts to an explicit hip-site cell and adjacent demographic/diagnosis/procedure columns. Never impute clinical data or infer final eligibility.",
            "output_directory": from_home(JOA_DIR),
            "analysis_plan_location": from_home(JOA_ANALYSIS_PLAN),
            "unspecified_settings": "Null values identify decisions not specified in the application; they are not imputed values.",
        },
    }


def write_report(config, path):
    sample = config["sample_size"]
    lines = [
        "# JOA研究の症例数設定", "",
        "申請書の研究計画に従い、解析可能症例数はFAI群64例、THA群64例、計128例とする。",
        "マッチング前の目標は各群120〜150例、計240〜300例とする。範囲内の単一目標は未指定。", "",
        "| 項目 | 設定 |", "|---|---|",
        "| 検定 | 独立2群の平均値比較、両側、等割付 |",
        "| 有意水準 | 0.05 |", "| 検出力 | 0.80 |", "| Cohen’s d | 0.50 |",
        f"| 非心t分布による必要数 | {sample['calculation']['continuous_n_per_group']:.5f}例/群 → 64例/群 |",
        f"| 63例/群の検出力 | {two_sample_power(63):.6f} |",
        f"| 64例/群の検出力 | {two_sample_power(64):.6f} |", "",
        "G*Power自体は実行せず、同じ独立2群t検定の前提で非心t分布による計算を行った。",
        "この必要数は申請書の独立2群比較の設計値であり、回帰・ROC・ICCの十分性は別途評価する。", "",
        "## 対象と解析計画", "",
        "現在の対象期間は2016年11月1日から2026年10月31日（両端を含む）。申請書の2021年4月〜2024年3月からユーザー指示により延長した。",
        "両側同時手術、再置換術、神経筋疾患を除外する。BMIが未収集のため、ユーザーの承認により暫定的に年齢・性別で1対1の傾向スコアマッチングを行う。",
        "術後評価時点は3・6・12・24か月。主要評価領域はPROMs（mHHS、NAHS、VHS、iHOT-12、HOSなど）。",
        "まずExcelで対象期間・術式・診断・重複患者・除外条件・年齢・性別・BMI・追跡評価の充足状況を確認する。",
        "手術予定表の行数を確定症例数として扱わず、施行実績・適格性・画像・術後評価を照合する。", "",
        "## 本解析前の未確定事項", "",
    ]
    lines.extend(f"- {item}" for item in config["unresolved_before_outcome_analysis"])
    lines += ["", "## 出典と再現性", "",
              f"申請書: {config['application']['path']}（研究計画）",
              f"SHA-256: {config['application']['sha256']}",
              f"設定日時: {config['created_at']}",
              f"計算環境: SciPy {scipy_version}",
              f"設定の機械可読版: {config['data_processing']['analysis_plan_location']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", type=Path)
    parser.add_argument("--out-dir", type=Path, default=JOA_DIR)
    parser.add_argument("--config-path", type=Path, default=JOA_ANALYSIS_PLAN)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    application = args.application
    if application is None:
        candidates = sorted(INPUT_DIR.glob("JOA*.docx"))
        if len(candidates) != 1:
            parser.error("--application で申請書を1件指定してください。")
        application = candidates[0]
    config = configure(application.expanduser())
    config["data_processing"]["output_directory"] = from_home(args.out_dir)
    config["data_processing"]["analysis_plan_location"] = from_home(args.config_path)
    if not args.check_only:
        out_dir = args.out_dir.expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        config_path = args.config_path.expanduser()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        legacy_config = out_dir / "study_config.json"
        if legacy_config.exists() and legacy_config != config_path:
            legacy_config.write_text(json.dumps({
                "status": "superseded",
                "authoritative_analysis_plan": from_home(config_path),
                "note": "Use the English analysis plan in input for the current surgery period and matching specification.",
            }, indent=2) + "\n", encoding="utf-8")
        write_report(config, out_dir / "study_setup.md")
        print(f"Saved analysis plan: {from_home(config_path)}")
    print(json.dumps(config["sample_size"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
