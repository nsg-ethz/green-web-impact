import json
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

# Configuration
LM_STUDIO_URL = "http://localhost:1234/v1/chat/completions"
MODEL_NAME = "google/gemma-4-26b-a4b"
TIMEOUT_SEC = 15
MAX_HTML_CHARS = 10000  # CRITICAL: Prevents crashing the local LLM with massive HTML

# 1. Load Data
print("Loading dataset...")
try:
    df = pd.read_csv("dataExtracted.csv")
    df.columns = df.columns.str.strip()
    urls = df["url"].tolist()
except FileNotFoundError:
    print("Error: dataExtracted.csv not found.")
    exit()


def extract_technical_signals(url):
    """Downloads page, extracts basic technical metrics and raw HTML."""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Green Audit Bot)"}
        resp = requests.get(url, headers=headers, timeout=TIMEOUT_SEC)
        resp.raise_for_status()  # Check if request was successful

        soup = BeautifulSoup(resp.content, "lxml")

        # Basic Metrics
        word_count = len(soup.get_text(strip=True).split())
        script_tags = len(soup.find_all("script"))
        style_tags = len(soup.find_all("style"))
        img_tags = len(soup.find_all("img"))
        link_tags = len(soup.find_all("a"))

        # Estimate complexity
        js_ratio = script_tags / max(link_tags, 1)

        # Capture HTML (Truncated to avoid overwhelming the LLM)
        # We use soup.prettify() to give the model a cleaner structure than raw bytes
        raw_html = soup.prettify()[:MAX_HTML_CHARS]

        return {
            "word_count": word_count,
            "scripts": script_tags,
            "styles": style_tags,
            "images": img_tags,
            "js_ratio": round(js_ratio, 2),
            "html_snippet": raw_html,  # Added HTML content
        }
    except Exception as e:
        return {"error": str(e)}


def ask_gemma_cluster(url, metrics):
    """Sends data + HTML to local LM Studio for clustering and analysis."""

    html_content = metrics.get("html_snippet", "No HTML content available.")
    # print(metrics)
    # Construct the enriched prompt
    prompt = f"""
    You are a web architecture expert. Analyze this website based on both its metadata and its raw HTML structure.

    --- METRICS ---
    - URL: {url}
    - Word Count: {metrics.get("word_count")}
    - Script Tags: {metrics.get("scripts")}
    - Style Tags: {metrics.get("styles")}
    - Image Tags: {metrics.get("images")}
    - JS Ratio: {metrics.get("js_ratio")}

    --- HTML CONTENT (Snippet) ---
    {html_content}
    --- END OF HTML ---

    Task:
    1. Assign a CLUSTER name for the page type (e.g., "Media", "Static Docs", "SaaS App", "Gov/Edu", "E-commerce", "Social Media", ...). Use the HTML structure to identify if it's a Single Page App (SPA), a blog, heavy landing page or similar.
    2. Provide a brief TECHNICAL ANALYSIS of why it fits this cluster based on both metrics and the HTML tags observed (e.g., presence of specific frameworks like React/Vue in scripts, or heavy use of div nesting).
    3. Analyze the TECHNICAL QUALITY. Look for: heavy script loading, large asset calls or any suboptimal coding style. Remain short.
    4. Assign a RATING from 1-5 (5 being optimal/green-friendly, 1 being inefficient/high-carbon).

    Output Format strictly as JSON:
    {{
        "cluster": "String",
        "technical_analysis": "String",
        "technical_quality": "String",
        "quality_rating": integer
    }}
    """
    # print(prompt)
    try:
        response = requests.post(
            LM_STUDIO_URL,
            json={
                "model": MODEL_NAME,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,  # Lowered temperature for more consistent JSON
                "max_tokens": 2000,
            },
            timeout=90,  # Increased timeout because processing HTML takes longer
        )

        if response.status_code == 200:
            content = response.json()["choices"][0]["message"]["content"]
            # Clean markdown code blocks if present
            content = content.replace("```json", "").replace("```", "").strip()
            return json.loads(content)
        else:
            return {
                "cluster": "Error",
                "technical_analysis": f"API Error: {response.status_code}",
                "technical_quality": "Unknown",
                "quality_rating": None,
            }

    except json.JSONDecodeError as je:
        return {
            "cluster": "Error",
            "technical_analysis": f"JSON Parse Error: {je}",
            "technical_quality": "Unknown",
            "quality_rating": None,
        }
    except Exception as e:
        return {
            "cluster": "Error",
            "technical_analysis": str(e),
            "technical_quality": "Unknown",
            "quality_rating": None,
        }


# 2. Process Loop
results = []
total = len(urls)

for i, url in enumerate(urls):
    print(f"[{i + 1}/{total}] Processing: {url}")

    tech_data = extract_technical_signals(url)

    if "error" in tech_data:
        print(f"   ❌ Failed to fetch: {tech_data['error']}")
        ai_result = {
            "cluster": "Error",
            "technical_analysis": tech_data["error"],
            "technical_quality": "N/A",
            "quality_rating": None,
        }
    else:
        ai_result = ask_gemma_cluster(url, tech_data)

    print(f"   🤖 Result: {ai_result}")

    results.append(
        {
            "url": url,
            "tech_metrics": tech_data,
            "ai_cluster": ai_result.get("cluster"),
            "ai_analysis": ai_result.get("technical_analysis"),
            "ai_quality": ai_result.get("technical_quality"),
            "quality_rating": ai_result.get("quality_rating"),
        }
    )

    time.sleep(0.5)

# 3. Finalize DataFrame
final_df = pd.DataFrame(results)

# Flatten tech metrics into columns (excluding the large HTML snippet to keep CSV clean)
tech_cols = ["word_count", "scripts", "styles", "images", "js_ratio"]
for col in tech_cols:
    final_df[col] = final_df["tech_metrics"].apply(lambda x: x.get(col, 0))

# Drop the nested dict and the heavy HTML snippet column from the final CSV
final_df = final_df.drop(columns=["tech_metrics"])

output_file = "audited_clusters_enriched.csv"
final_df.to_csv(output_file, index=False)
print(f"\n✅ Done! Saved results to {output_file}")
