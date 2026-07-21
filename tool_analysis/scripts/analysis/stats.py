import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import (
    kendalltau,
    ks_2samp,
    pearsonr,
    spearmanr,
    ttest_rel,
    wilcoxon,
)
from sklearn.decomposition import PCA
from sklearn.feature_selection import mutual_info_regression
from sklearn.preprocessing import StandardScaler

# =========================================================
# PART 1: WEBNRJ vs ECOGRADER (existing 2-source analysis)
# =========================================================


def safe_z(x):
    x = np.asarray(x, dtype=float)
    mu = np.nanmean(x)
    sigma = np.nanstd(x)
    if sigma == 0 or np.isnan(sigma):
        return np.zeros_like(x)
    return (x - mu) / sigma


# --- Load + Clean ---

web = pd.read_csv("webnrj.csv")
eco = pd.read_csv("ecograder.csv")

web["URL"] = web["URL"].astype(str).str.strip().str.rstrip("/")
eco["url"] = eco["url"].astype(str).str.strip().str.rstrip("/")

web["created_at"] = pd.to_datetime(web["created_at"], errors="coerce", utc=True)
eco["scrape_date"] = pd.to_datetime(eco["scrape_date"], errors="coerce", utc=True)

web = web.sort_values("created_at").drop_duplicates("URL", keep="last")
eco = eco.sort_values("scrape_date").drop_duplicates("url", keep="last")

eco = eco[eco["status"] == "success"].copy()

eco["ecograder_score"] = pd.to_numeric(eco["ecograder_score"], errors="coerce")
eco["co2_emissions"] = pd.to_numeric(eco["co2_emissions"], errors="coerce")
eco = eco.dropna(subset=["ecograder_score", "co2_emissions"])

web["rendering_power_w"] = pd.to_numeric(web["Rendering Power [W]"], errors="coerce")
web["network_transfer_mb"] = pd.to_numeric(
    web["Network Transfer [MB]"], errors="coerce"
)

web = web.dropna(subset=["rendering_power_w", "network_transfer_mb"])

# --- Strict Match (webNRJ + EcoGrader) ---

common_urls = set(web["URL"]).intersection(set(eco["url"]))

df_web_eco = web[web["URL"].isin(common_urls)].merge(
    eco[eco["url"].isin(common_urls)],
    left_on="URL",
    right_on="url",
    how="inner",
)

print("\n=== PART 1: WebNRJ vs EcoGrader (2 sources) ===")
print("Dataset size (exact URL match):", df_web_eco.shape)

# --- Features ---

df_web_eco["resource_intensity"] = safe_z(df_web_eco["rendering_power_w"]) + safe_z(
    df_web_eco["network_transfer_mb"]
)

df_web_eco["resource_gap"] = safe_z(df_web_eco["resource_intensity"]) - safe_z(
    df_web_eco["co2_emissions"]
)
df_web_eco["disagreement_axis"] = np.abs(df_web_eco["resource_gap"])

df_web_eco["webnrj_rank"] = df_web_eco["resource_intensity"].rank()
df_web_eco["eco_rank"] = df_web_eco["co2_emissions"].rank()

df_web_eco["latent_intensity"] = (
    safe_z(df_web_eco["resource_intensity"]) + safe_z(df_web_eco["co2_emissions"])
) / 2

df_web_eco["web_residual"] = safe_z(df_web_eco["resource_intensity"]) - df_web_eco[
    "latent_intensity"
]
df_web_eco["eco_residual"] = safe_z(df_web_eco["co2_emissions"]) - df_web_eco[
    "latent_intensity"
]

# --- Agreement ---

print("\n=== AGREEMENT (WebNRJ vs EcoGrader) ===")

pearson_r, pearson_p = pearsonr(
    df_web_eco["resource_intensity"], df_web_eco["co2_emissions"]
)
spearman_r, spearman_p = spearmanr(
    df_web_eco["resource_intensity"], df_web_eco["co2_emissions"]
)
kendall_r, kendall_p = kendalltau(
    df_web_eco["resource_intensity"], df_web_eco["co2_emissions"]
)

print("Pearson:", round(pearson_r, 4), "p:", pearson_p)
print("Spearman:", round(spearman_r, 4), "p:", spearman_p)
print("Kendall:", round(kendall_r, 4), "p:", kendall_p)

# --- Mutual Information ---

target = df_web_eco["co2_emissions"]

mi_power = mutual_info_regression(
    df_web_eco[["rendering_power_w"]], target, random_state=42
)[0]
mi_network = mutual_info_regression(
    df_web_eco[["network_transfer_mb"]], target, random_state=42
)[0]
mi_score = mutual_info_regression(
    df_web_eco[["ecograder_score"]], target, random_state=42
)[0]

print("\n=== MUTUAL INFORMATION ===")
print("Rendering Power:", round(mi_power, 4))
print("Network Transfer:", round(mi_network, 4))
print("Eco Score:", round(mi_score, 4))

# --- PCA ---

features = df_web_eco[
    ["rendering_power_w", "network_transfer_mb", "co2_emissions", "ecograder_score"]
]

scaled = StandardScaler().fit_transform(features)
pca = PCA(n_components=2)
pca_result = pca.fit_transform(scaled)

df_web_eco["pc1"] = pca_result[:, 0]
df_web_eco["pc2"] = pca_result[:, 1]

print("\n=== PCA ===")
print("Explained variance:", pca.explained_variance_ratio_)

# --- Statistical Tests ---

print("\n=== STATISTICAL TESTS ===")

web_vals = df_web_eco["resource_intensity"].values
eco_vals = df_web_eco["co2_emissions"].values

w_stat, w_p = wilcoxon(web_vals, eco_vals)
t_stat, t_p = ttest_rel(web_vals, eco_vals)
ks_stat, ks_p = ks_2samp(web_vals, eco_vals)

np.random.seed(42)
obs = pearson_r
perm = []

for _ in range(1000):
    shuffled = np.random.permutation(eco_vals)
    perm.append(pearsonr(web_vals, shuffled)[0])

perm = np.array(perm)
perm_p = np.mean(np.abs(perm) >= np.abs(obs))

# --- Outliers (2-source) ---

df_web_eco["outlier_score"] = (
    df_web_eco["disagreement_axis"]
    + 0.5 * np.abs(safe_z(df_web_eco["rendering_power_w"]))
    + 0.5 * np.abs(safe_z(df_web_eco["network_transfer_mb"]))
    + 0.5 * np.abs(safe_z(df_web_eco["co2_emissions"]))
)

df_web_eco["findings"] = df_web_eco.apply(
    lambda r: [
        "high disagreement (>2σ)" if r["disagreement_axis"] > 2 else None,
        "high rendering power"
        if r["rendering_power_w"] > df_web_eco["rendering_power_w"].quantile(0.95)
        else None,
        "high network transfer"
        if r["network_transfer_mb"] > df_web_eco["network_transfer_mb"].quantile(0.95)
        else None,
        "high CO₂" if r["co2_emissions"] > df_web_eco["co2_emissions"].quantile(0.95)
        else None,
    ],
    axis=1,
)

df_web_eco["findings"] = df_web_eco["findings"].apply(
    lambda x: [i for i in x if i]
)

print("\n=== TOP OUTLIERS (WebNRJ vs EcoGrader) ===")

top = df_web_eco.sort_values("outlier_score", ascending=False).head(10)

for _, r in top.iterrows():
    print("\n----------------------------------------")
    print("URL:", r["URL"])
    print("Rendering Power:", round(r["rendering_power_w"], 3))
    print("Network Transfer:", round(r["network_transfer_mb"], 3))
    print("CO2:", round(r["co2_emissions"], 3))
    print("PC1:", round(r["pc1"], 3), "PC2:", round(r["pc2"], 3))
    print("Findings:")
    for f in r["findings"]:
        print(" -", f)

# --- Summary (2-source) ---

print("\n=== SUMMARY (WebNRJ vs EcoGrader) ===")
print("URLs analysed:", len(df_web_eco))
print("Pearson:", round(pearson_r, 4))
print("Spearman:", round(spearman_r, 4))
print("Kendall:", round(kendall_r, 4))

# --- Statistical Synthesis (2-source) ---

if abs(spearman_r) > 0.7:
    agreement_level = "high rank agreement"
elif abs(spearman_r) > 0.4:
    agreement_level = "moderate rank agreement"
else:
    agreement_level = "low rank agreement"

if ks_stat > 0.7:
    distribution_note = "strong distribution separation"
elif ks_stat > 0.4:
    distribution_note = "moderate distribution separation"
else:
    distribution_note = "weak distribution separation"

if w_p < 0.05:
    paired_note = "statistically significant difference between systems"
else:
    paired_note = "no statistically significant paired difference"

if perm_p < 0.05:
    perm_note = "correlation unlikely under null permutation"
else:
    perm_note = "correlation plausible under permutation null"

print("Agreement level:", agreement_level)
print("Distribution:", distribution_note)
print("Paired test:", paired_note)
print("Permutation test:", perm_note)

# =========================================================
# PART 2: 3-SOURCE ANALYSIS (EcoGrader + WebsiteCarbon + Green Coding)
# =========================================================


def find_categories(obj):
    """Recursively find 'categories' key in nested dict/list."""
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
    """Extract render and interaction scores from EcoGrader report JSON."""
    render_score = np.nan
    interaction_score = np.nan

    categories = find_categories(data)

    for cat in categories:
        if not isinstance(cat, dict):
            continue
        if cat.get("category") != "UX Design":
            continue
        metrics = cat.get("metrics", [])
        if not isinstance(metrics, list):
            continue
        for m in metrics:
            if not isinstance(m, dict):
                continue
            name = m.get("name", "")
            score = m.get("score", {}) if isinstance(m.get("score", {}), dict) else {}
            metricscore = score.get("metricscore", np.nan)
            if name == "Improve Page Rendering":
                render_score = metricscore
            if name == "Page Interactions":
                interaction_score = metricscore

    return render_score, interaction_score


def extract_gm_energy(stats, report_id):
    """Extract CPU + DRAM energy (kWh) and page weight (bytes) from GM stats.json."""
    visit = stats["data"]["data"]["Visit page and idle for 5 s"]["data"]
    cpu_energy_uJ = visit["cpu_energy_rapl_msr_component"]["data"]["Package_0"][
        "data"
    ][report_id]["mean"]
    ram_energy_uJ = visit["memory_energy_rapl_msr_component"]["data"]["DRAM_0"][
        "data"
    ][report_id]["mean"]
    total_energy_kwh = (cpu_energy_uJ + ram_energy_uJ) / 3_600_000_000_000
    page_weight_bytes = visit["network_total_cgroup_container"]["data"][
        "gmt-playwright-nodejs"
    ]["data"][report_id]["mean"]
    return float(total_energy_kwh), float(page_weight_bytes)


# --- Load 3-source CSVs ---

eco = pd.read_csv("ecograder.csv")
wc = pd.read_csv("websitecarbon.csv")
gc = pd.read_csv("greencoding.csv")

eco["url"] = eco["url"].astype(str).str.strip().str.lower()
wc["url"] = wc["url"].astype(str).str.strip().str.lower()
gc["url"] = gc["url"].astype(str).str.strip().str.lower()

eco["report_id"] = eco["report_id"].astype(str)
wc["report_key"] = wc["report_key"].astype(str)
gc["report_id"] = gc["report_id"].astype(str)

eco["co2_eco"] = pd.to_numeric(eco["co2_emissions"], errors="coerce")
wc["co2_wc"] = pd.to_numeric(wc["co2_grams"], errors="coerce")

eco = (
    eco.dropna(subset=["co2_eco"])
    .sort_values("scrape_date")
    .groupby("url", as_index=False)
    .tail(1)
)

wc = (
    wc.dropna(subset=["co2_wc"])
    .sort_values("scrape_date")
    .groupby("url", as_index=False)
    .tail(1)
)

eco_ids = set(eco["report_id"])
wc_ids = set(wc["report_key"])

# --- Extract EcoGrader render/interaction scores from JSON ---

PAGES_DIR = Path("data/ecograder")

eco_render = []
for f in PAGES_DIR.glob("*/report.json"):
    report_id = f.parent.name
    if report_id not in eco_ids:
        continue
    try:
        with f.open() as file:
            data = json.load(file)
        render_score, interaction_score = extract_scores(data)
        eco_render.append(
            {
                "report_id": report_id,
                "render_score": render_score,
                "interaction_score": interaction_score,
            }
        )
    except Exception:
        continue

eco_render = pd.DataFrame(eco_render)

# --- Extract WebsiteCarbon grams from JSON ---

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
                "report_key": key,
                "wc_page_g": data.get("grams"),
            }
        )
    except Exception:
        continue

wc_pages = pd.DataFrame(wc_pages)

# --- Merge EcoGrader + WebsiteCarbon ---

eco_metrics = eco.merge(eco_render, on="report_id", how="left")
wc_metrics = wc.merge(wc_pages, on="report_key", how="left")

df_3 = eco_metrics.merge(wc_metrics, on="url", how="inner")

# --- Extract Green Coding CPU/network from JSON ---

gc_map = gc.set_index("report_id")["url"].to_dict()
PAGESGM_DIR = Path("data/greenmetrics")

gm_pages = []
for stats_file in PAGESGM_DIR.glob("*/stats.json"):
    try:
        report_id = stats_file.parent.name
        if report_id not in gc_map:
            continue
        url = gc_map[report_id]
        with open(stats_file) as f:
            stats = json.load(f)
        gm_energy_kwh, page_weight_bytes = extract_gm_energy(stats, report_id)
        gm_pages.append(
            {
                "url": url,
                "report_id": report_id,
                "gm_energy_kwh": gm_energy_kwh,
                "page_weight_bytes": page_weight_bytes,
            }
        )
    except Exception:
        continue

gm = pd.DataFrame(gm_pages)
df_3 = df_3.merge(gm, on=["url"], how="left")

df_3 = df_3.dropna(subset=["co2_eco", "co2_wc"]).copy()

print("\n=== PART 2: 3-Source Analysis (EcoGrader + WebsiteCarbon + Green Coding) ===")
print("Rows after 3-source merge:", len(df_3))

# --- Stats helpers ---


def z(x):
    x = np.asarray(x, dtype=float)
    m = np.nanmean(x)
    s = np.nanstd(x)
    return (x - m) / s if s else np.zeros_like(x)


df_3["gap"] = df_3["co2_wc"] - df_3["co2_eco"]
df_3["abs_gap"] = df_3["gap"].abs()

df_3["render_pressure"] = z(-df_3["render_score"])
df_3["interaction_pressure"] = z(-df_3["interaction_score"])

# --- Agreement (3-source) ---

print("\n=== AGREEMENT (EcoGrader vs WebsiteCarbon CO₂) ===")
print("Pearson:", round(pearsonr(df_3["co2_wc"], df_3["co2_eco"])[0], 4))
print("Spearman:", round(spearmanr(df_3["co2_wc"], df_3["co2_eco"])[0], 4))
print("Kendall:", round(kendalltau(df_3["co2_wc"], df_3["co2_eco"])[0], 4))

# --- Outliers (3-source) ---

cpu_q95 = df_3["gm_energy_kwh"].quantile(0.95)
weight_q95 = df_3["page_weight_bytes"].quantile(0.95)

df_3["outlier"] = df_3["abs_gap"]

df_3["findings"] = df_3.apply(
    lambda r: [
        "low render score"
        if pd.notna(r["render_score"]) and r["render_score"] < 70
        else None,
        "low interaction score"
        if pd.notna(r["interaction_score"]) and r["interaction_score"] < 70
        else None,
        "high WC" if r["co2_wc"] > df_3["co2_wc"].quantile(0.95) else None,
        "high ECO" if r["co2_eco"] > df_3["co2_eco"].quantile(0.95) else None,
        "high GM energy"
        if pd.notna(r["gm_energy_kwh"]) and r["gm_energy_kwh"] > cpu_q95
        else None,
        "high page weight"
        if pd.notna(r["page_weight_bytes"]) and r["page_weight_bytes"] > weight_q95
        else None,
    ],
    axis=1,
)

df_3["findings"] = df_3["findings"].apply(lambda x: [i for i in x if i])

print("\n=== TOP OUTLIERS (3-Source) ===")

for _, r in df_3.sort_values("outlier", ascending=False).head(10).iterrows():
    print("\n---")
    print("URL:", r["url"])
    print("WC:", round(r["co2_wc"], 6))
    print("ECO:", round(r["co2_eco"], 6))
    print("Render:", r["render_score"])
    print("Interaction:", r["interaction_score"])
    print("GM kWh:", r.get("gm_energy_kwh"))
    print("Weight bytes:", r.get("page_weight_bytes"))
    for f in r["findings"]:
        print("-", f)

# --- Summary (3-source) ---

print("\n=== SUMMARY (3-Source) ===")
print("Rows:", len(df_3))
print("Mean WC:", round(df_3["co2_wc"].mean(), 6))
print("Mean ECO:", round(df_3["co2_eco"].mean(), 6))
print("Render avg:", df_3["render_score"].dropna().mean())
print("Interaction avg:", df_3["interaction_score"].dropna().mean())
print("GM avg (kWh):", df_3["gm_energy_kwh"].dropna().mean())
print("Page weight avg (KB):", df_3["page_weight_bytes"].dropna().mean() / 1000)
