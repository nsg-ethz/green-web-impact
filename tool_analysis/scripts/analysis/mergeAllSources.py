import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

DATA_FACTOR = 0.04106063  # kWh per GB for webNRJ (factor is from greencoding)
# helpers


def extract_breakdown(breakdown):
    result = {}

    for name, values in breakdown.items():
        if not isinstance(values, dict):
            continue

        key = name.lower().replace(" ", "_").replace("-", "_").replace("/", "_")

        result[f"eco_{key}_bytesTotal"] = values.get("byteTotal", np.nan)
        result[f"eco_{key}_percentage"] = values.get("percentage", np.nan)

    return result


def find_categories(obj):
    if isinstance(obj, dict):
        if "categories" in obj and isinstance(obj["categories"], list):
            return obj["categories"]
        for v in obj.values():
            res = find_categories(v)
            if res:
                return res
    elif isinstance(obj, list):
        for item in obj:
            res = find_categories(item)
            if res:
                return res
    return []


def extract_scores(data):
    render_score = np.nan
    interaction_score = np.nan
    emissions_score = np.nan
    overall_eco_score = np.nan

    # NEW
    category_results = {}

    # =====================================================
    # 0. OVERALL ECO SCORE
    # =====================================================
    try:
        overall_eco_score = data["props"]["report"]["response"].get("score", np.nan)
        overall_eco_score = (
            float(overall_eco_score) if overall_eco_score is not None else np.nan
        )
    except Exception:
        overall_eco_score = np.nan

    # Lighthouse scores
    try:
        lh_perf = data["props"]["report"]["response"].get(
            "lighthouse_performance_score", np.nan
        )
        lh_seo = data["props"]["report"]["response"].get("lighthouse_seo_score", np.nan)
        lh_acc = data["props"]["report"]["response"].get(
            "lighthouse_accessibility_score", np.nan
        )

        lh_perf = float(lh_perf) if lh_perf is not None else np.nan
        lh_seo = float(lh_seo) if lh_seo is not None else np.nan
        lh_acc = float(lh_acc) if lh_acc is not None else np.nan

    except Exception:
        lh_perf = lh_seo = lh_acc = np.nan

    unused_js_savings_bytes = 0.0
    unused_css_savings_bytes = 0.0

    categories = find_categories(data)

    for cat in categories:
        if not isinstance(cat, dict):
            continue

        category_name = cat.get("category")

        if category_name:
            key = (
                category_name.lower()
                .replace(" ", "_")
                .replace("/", "_")
                .replace("-", "_")
            )

            category_results[f"eco_{key}_score"] = cat.get(
                "category_score",
                np.nan,
            )

            percent = cat.get("category_percent", np.nan)

            if isinstance(percent, str):
                percent = percent.rstrip("%")

            try:
                percent = float(percent)
            except Exception:
                percent = np.nan

            category_results[f"eco_{key}_percent"] = percent

        metrics = cat.get("metrics", [])

        if not isinstance(metrics, list):
            continue

        for m in metrics:
            if not isinstance(m, dict):
                continue

            name = m.get("name", "")

            # Existing savings extraction
            opps = m.get("opportunity_items", [])

            if isinstance(opps, list):
                for opp in opps:
                    if opp.get("name") == "Unused Javascript":
                        unused_js_savings_bytes += opp.get("overallSavingsBytes", 0)
                    elif opp.get("name") == "Unused CSS Rules":
                        unused_css_savings_bytes += opp.get("overallSavingsBytes", 0)

            # Existing UX extraction
            if cat.get("category") != "UX Design":
                continue

            score = m.get("score", {}) if isinstance(m.get("score", {}), dict) else {}

            metricscore = score.get("metricscore", np.nan)

            if name == "Improve Page Rendering":
                render_score = metricscore

            elif name == "Page Interactions":
                interaction_score = metricscore

    # =====================================================
    # Emissions
    # =====================================================
    try:
        emissions_score = data["props"]["report"]["response"].get(
            "emissions_score",
            np.nan,
        )

        emissions_score = (
            float(emissions_score) if emissions_score is not None else np.nan
        )

    except Exception:
        emissions_score = np.nan

    return (
        overall_eco_score,
        render_score,
        interaction_score,
        emissions_score,
        lh_perf,
        lh_seo,
        lh_acc,
        unused_js_savings_bytes,
        unused_css_savings_bytes,
        category_results,
    )


# ============================================================
# LOAD
# ============================================================

eco = pd.read_csv("ecograder.csv")
gc = pd.read_csv("greencoding.csv")
wc = pd.read_csv("websitecarbon.csv")

# remove known bad urls

eco = eco[
    ~eco["url"].isin(
        {"https://checkpoint.com", "https://one.one", "https://stripe.com"}
    )
]
# ============================================================
# NORMALIZE URLs (CRITICAL FIX)
# ============================================================

for df in (eco, gc, wc):
    df["url"] = df["url"].astype(str).str.strip().str.lower()

# ============================================================
# KEEP ONLY LATEST PER URL (DEDUP FIRST)
# ============================================================

eco = (
    eco.dropna(subset=["url"])
    .sort_values("scrape_date")
    .drop_duplicates("url", keep="last")
)

wc = (
    wc.dropna(subset=["url"])
    .sort_values("scrape_date")
    .drop_duplicates("url", keep="last")
)

gc = (
    gc.dropna(subset=["url"])
    .sort_values("ended_at")
    .drop_duplicates("url", keep="last")
)

# ============================================================
# SANITY CHECKS
# ============================================================

print("\n=== CSV COVERAGE ===")

eco_urls = set(eco["url"])
gc_urls = set(gc["url"])
wc_urls = set(wc["url"])

print("URLs in eco:", len(eco_urls))
print("URLs in GC :", len(gc_urls))
print("URLs in WC :", len(wc_urls))

print("Eco duplicates:", eco["url"].duplicated().sum())
print("GC duplicates :", gc["url"].duplicated().sum())
print("WC duplicates :", wc["url"].duplicated().sum())

# ============================================================
# SET OPERATIONS
# ============================================================

all_urls = eco_urls | gc_urls | wc_urls
common_urls = eco_urls & gc_urls & wc_urls

print("\nUnion:", len(all_urls))
print("Intersection (all 3):", len(common_urls))

print("\nMissing relative to union")
print("Missing from Eco:", len(all_urls - eco_urls))
print("Missing from GC :", len(all_urls - gc_urls))
print("Missing from WC :", len(all_urls - wc_urls))

print("\nUnique to one source")
print("Only Eco:", len(eco_urls - gc_urls - wc_urls))
print("Only GC :", len(gc_urls - eco_urls - wc_urls))
print("Only WC :", len(wc_urls - eco_urls - gc_urls))

df = eco.merge(gc, on="url", how="outer", suffixes=("_eco", "_gc"))
df = df.merge(wc, on="url", how="outer")

print("\nMerged rows:", len(df))
print("Merged unique URLs:", df["url"].nunique())

eco_ids = set(eco["report_id"])
wc_ids = set(wc["report_key"])

PAGES_DIR = Path("data/ecograder")

eco_valid = {}

for f in PAGES_DIR.glob("*/report.json"):
    report_id = f.parent.name
    eco_valid[report_id] = f

valid_eco_ids = set(eco_valid.keys())

eco_success_ids = eco_ids & valid_eco_ids
eco_failed_ids = eco_ids - valid_eco_ids

print("\n=== ECO EXECUTION QUALITY ===")
print("Submitted:", len(eco_ids))
print("Successful (on disk):", len(eco_success_ids))
print("Failed (missing report.json):", len(eco_failed_ids))

# =====================================================
# SAFE EXTRACTION
# =====================================================

eco_render = []
errors = Counter()

for f in PAGES_DIR.glob("*/report.json"):
    report_id = f.parent.name

    if report_id not in valid_eco_ids:
        continue

    try:
        with f.open() as file:
            data = json.load(file)

        (
            overall,
            render_score,
            interaction_score,
            emissions_score,
            lh_perf,
            lh_seo,
            lh_acc,
            unused_js_savings_bytes,
            unused_css_savings_bytes,
            category_results,
        ) = extract_scores(data)

        breakdown = data["props"]["breakdownGraphData"]

        breakdown_results = extract_breakdown(breakdown)

        eco_page_weight = breakdown.get("total", {}).get("byteTotal", np.nan)
        eco_web_requests = breakdown.get("total", {}).get("count", np.nan)

        url_row = eco.loc[eco["report_id"] == report_id]

        if url_row.empty:
            continue

        row = {
            "url": url_row["url"].iloc[0],
            "eco_id": report_id,
            "eco_overall_score": overall,
            "eco_lh_perf": lh_perf,
            "eco_lh_seo": lh_seo,
            "eco_lh_acc": lh_acc,
            "eco_unused_js_mb": unused_js_savings_bytes / 1_048_576,
            "eco_unused_css_mb": unused_css_savings_bytes / 1_048_576,
            "eco_render_score": render_score,
            "eco_interaction_score": interaction_score,
            "eco_emissions_score": emissions_score,
            "eco_page_weight_bytes": float(eco_page_weight),
            "eco_web_requests": float(eco_web_requests),
        }

        # Add all category columns
        row.update(category_results)
        row.update(breakdown_results)
        eco_render.append(row)

    except Exception as e:
        errors[type(e).__name__] += 1

print(errors.most_common())

eco_render = pd.DataFrame(eco_render)

# calculate score without greenhosting
eco_render["eco_overall_score_no_greenhosting"] = np.floor(
    (
        (
            2 * eco_render["eco_page_weight_score"]
            + eco_render["eco_ux_design_score"]
            + 2 * eco_render["eco_carbon_score_score"]
        )
        / 5.0
    )
    + 0.5
).fillna(0).astype(int)

print("Rows in eco_render:", len(eco_render))
print("Unique URLs in eco_render:", eco_render["url"].nunique())
WC_DIR = Path("data/websitecarbon")

wc_pages = []
for f in WC_DIR.glob("*/page.json"):
    key = f.parent.name

    if key not in wc_ids:
        continue

    try:
        with f.open() as file:
            data = json.load(file)

        wc_pages.append(
            {
                "url": wc[wc["report_key"] == key]["url"].iloc[0],
                "wc_id": key,
                "wc_page_g": data.get("grams"),
                "wc_energy_kwh": data.get("energy"),
                "wc_litres": data.get("litres"),
            }
        )
    except Exception:
        continue

wc_pages = pd.DataFrame(wc_pages)

gc_map = gc.set_index("report_id")["url"].to_dict()

PAGESGM_DIR = Path("data/greenmetrics")

gm_pages = []


def uJTokWh(uj):
    j = uj * 10**-6
    wh = j / 3600
    kWh = wh / 1000
    return kWh


for stats_file in PAGESGM_DIR.glob("*/stats.json"):
    try:
        report_id = stats_file.parent.name

        if report_id not in gc_map:
            continue

        url = gc_map[report_id]

        with open(stats_file) as f:
            stats = json.load(f)

        visit = stats["data"]["data"]["Visit page and idle for 5 s"]["data"]

        cpu_energy_uJ = visit["cpu_energy_rapl_msr_component"]["data"]["Package_0"][
            "data"
        ][report_id]["mean"]

        ram_energy_uJ = visit["memory_energy_rapl_msr_component"]["data"]["DRAM_0"][
            "data"
        ][report_id]["mean"]

        cpu_energy_kwh = uJTokWh(cpu_energy_uJ)
        ram_energy_kwh = uJTokWh(ram_energy_uJ)

        page_weight_bytes = visit["network_total_cgroup_container"]["data"][
            "gmt-playwright-nodejs"
        ]["data"][report_id]["mean"]

        gm_pages.append(
            {
                "url": url,
                "gm_id": report_id,
                "gm_cpu_energy_kwh": float(cpu_energy_kwh),
                "gm_ram_energy_kwh": float(ram_energy_kwh),
                "gm_page_weight_bytes": float(page_weight_bytes),
            }
        )

    except Exception:
        continue


gm_pages = pd.DataFrame(gm_pages)
# =====================================================
# ENERGY MODEL
# =====================================================

gm_pages["gm_network_energy_kwh"] = DATA_FACTOR * (
    gm_pages["gm_page_weight_bytes"] / (1024**3)
)

gm_pages["gm_estimated_total_energy_kwh"] = (
    gm_pages["gm_cpu_energy_kwh"]
    + gm_pages["gm_ram_energy_kwh"]  # may be removed
    + gm_pages["gm_network_energy_kwh"]
)

print("\n=== EXTRACTION COVERAGE ===")

print(
    "Eco CSV URLs:",
    eco["url"].nunique(),
    "| Eco extracted:",
    eco_render["url"].nunique(),
)

print("GC CSV URLs:", gc["url"].nunique(), "| GC extracted:", gm_pages["url"].nunique())

print("WC CSV URLs:", wc["url"].nunique(), "| WC extracted:", wc_pages["url"].nunique())

print("\nExtraction losses")

print("Eco loss:", eco["url"].nunique() - eco_render["url"].nunique())

print("GC loss:", gc["url"].nunique() - gm_pages["url"].nunique())

print("WC loss:", wc["url"].nunique() - wc_pages["url"].nunique())

fulldf = pd.merge(df["url"], eco_render, left_on="url", right_on="url")
fulldf = pd.merge(fulldf, wc_pages, left_on="url", right_on="url")
fulldf = pd.merge(fulldf, gm_pages, left_on="url", right_on="url")
print("\n=== FINAL COVERAGE ===")

urls_csv = common_urls

urls_eco_json = set(eco_render["url"])
urls_gc_json = set(gm_pages["url"])
urls_wc_json = set(wc_pages["url"])

print("URLs common in all CSVs:", len(urls_csv))

print("Common URLs missing Eco extraction:", len(urls_csv - urls_eco_json))

print("Common URLs missing GC extraction:", len(urls_csv - urls_gc_json))

print("Common URLs missing WC extraction:", len(urls_csv - urls_wc_json))

print("Final URLs in fulldf:", fulldf["url"].nunique())

print("Rows in fulldf:", len(fulldf))  # save fulldf as csv
fulldf.to_csv("dataExtracted.csv")
