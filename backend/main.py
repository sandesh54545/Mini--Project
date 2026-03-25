from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import mysql.connector
import json
import os
import io
import uuid
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import warnings
warnings.filterwarnings('ignore')

app = FastAPI(title="Data Quality & Anomaly Detection System", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

UPLOAD_DIR = "uploads"
REPORT_DIR = "reports"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(REPORT_DIR, exist_ok=True)

# ─── DB helpers (optional – graceful fallback if MySQL not running) ─────────
def get_db():
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "data_quality_db"),
        )
        return conn
    except Exception:
        return None


def save_analysis_to_db(filename: str, quality_score: float, total_rows: int, issues: int):
    conn = get_db()
    if not conn:
        return
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS analysis_reports (
                id INT AUTO_INCREMENT PRIMARY KEY,
                filename VARCHAR(255),
                quality_score FLOAT,
                total_rows INT,
                issues_found INT,
                created_at DATETIME
            )
        """)
        cur.execute(
            "INSERT INTO analysis_reports (filename, quality_score, total_rows, issues_found, created_at) VALUES (%s,%s,%s,%s,%s)",
            (filename, quality_score, total_rows, issues, datetime.now())
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ─── Core Analysis ──────────────────────────────────────────────────────────
def analyse_dataset(df: pd.DataFrame):
    result = {}

    # ── Overview ──────────────────────────────────────────────────────────
    result["overview"] = {
        "total_rows": int(len(df)),
        "total_columns": int(len(df.columns)),
        "columns": list(df.columns),
        "dtypes": {c: str(df[c].dtype) for c in df.columns},
        "memory_usage_kb": round(df.memory_usage(deep=True).sum() / 1024, 2),
    }

    # ── Missing Values ─────────────────────────────────────────────────────
    missing = df.isnull().sum()
    missing_pct = (missing / len(df) * 100).round(2)
    missing_cols = {}
    for col in df.columns:
        if missing[col] > 0:
            missing_cols[col] = {
                "count": int(missing[col]),
                "percentage": float(missing_pct[col]),
                "suggestions": _missing_suggestions(df[col], col),
            }
    result["missing_values"] = {
        "total_missing": int(missing.sum()),
        "columns_with_missing": missing_cols,
    }

    # ── Duplicates ─────────────────────────────────────────────────────────
    dup_mask = df.duplicated(keep=False)
    dup_rows = df[dup_mask].copy()
    dup_rows["_dup_group"] = df[dup_mask].groupby(list(df.columns)).ngroup()
    result["duplicates"] = {
        "total_duplicate_rows": int(df.duplicated().sum()),
        "duplicate_percentage": round(df.duplicated().sum() / len(df) * 100, 2),
        "suggestions": _duplicate_suggestions(df),
        "sample_rows": dup_rows.head(10).drop(columns=["_dup_group"], errors="ignore").to_dict(orient="records"),
    }

    # ── Column-level stats ─────────────────────────────────────────────────
    col_stats = {}
    for col in df.columns:
        s = df[col]
        info = {
            "dtype": str(s.dtype),
            "missing": int(s.isnull().sum()),
            "unique": int(s.nunique()),
        }
        if pd.api.types.is_numeric_dtype(s):
            info.update({
                "min": float(s.min()) if not s.isnull().all() else None,
                "max": float(s.max()) if not s.isnull().all() else None,
                "mean": float(s.mean()) if not s.isnull().all() else None,
                "std": float(s.std()) if not s.isnull().all() else None,
                "median": float(s.median()) if not s.isnull().all() else None,
                "skewness": float(s.skew()) if not s.isnull().all() else None,
            })
        else:
            top = s.value_counts().head(5).to_dict()
            info["top_values"] = {str(k): int(v) for k, v in top.items()}
        col_stats[col] = info
    result["column_stats"] = col_stats

    # ── Anomaly Detection ──────────────────────────────────────────────────
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    anomaly_result = {"numeric_columns_analysed": numeric_cols, "anomalies": {}}

    if len(numeric_cols) >= 1:
        X = df[numeric_cols].dropna()
        if len(X) > 10:
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X)
            iso = IsolationForest(contamination=0.05, random_state=42, n_estimators=100)
            labels = iso.fit_predict(X_scaled)
            scores = iso.score_samples(X_scaled)

            anomaly_indices = X.index[labels == -1].tolist()
            anomaly_result["total_anomalies"] = int(len(anomaly_indices))
            anomaly_result["anomaly_percentage"] = round(len(anomaly_indices) / len(X) * 100, 2)
            anomaly_result["anomaly_row_indices"] = anomaly_indices[:50]
            anomaly_result["anomaly_scores"] = [round(float(s), 4) for s in scores[:50]]
            anomaly_result["sample_anomalies"] = df.loc[anomaly_indices[:10]].to_dict(orient="records")
            anomaly_result["suggestions"] = _anomaly_suggestions(df, numeric_cols, anomaly_indices)

            # Per-column IQR outliers
            col_outliers = {}
            for col in numeric_cols:
                s = df[col].dropna()
                Q1, Q3 = s.quantile(0.25), s.quantile(0.75)
                IQR = Q3 - Q1
                out = s[(s < Q1 - 1.5 * IQR) | (s > Q3 + 1.5 * IQR)]
                col_outliers[col] = {
                    "outlier_count": int(len(out)),
                    "lower_bound": round(float(Q1 - 1.5 * IQR), 4),
                    "upper_bound": round(float(Q3 + 1.5 * IQR), 4),
                    "sample_outlier_values": [round(float(v), 4) for v in out.head(5).tolist()],
                }
            anomaly_result["column_outliers"] = col_outliers
        else:
            anomaly_result["note"] = "Not enough numeric rows for anomaly detection (need > 10)."
    else:
        anomaly_result["note"] = "No numeric columns found."
    result["anomaly_detection"] = anomaly_result

    # ── Quality Score ──────────────────────────────────────────────────────
    score = 100.0
    total = len(df)
    if total > 0:
        score -= (missing.sum() / (total * len(df.columns))) * 40
        score -= (df.duplicated().sum() / total) * 30
        if "total_anomalies" in anomaly_result:
            score -= (anomaly_result["total_anomalies"] / total) * 30
    score = max(0.0, min(100.0, round(score, 2)))

    if score >= 85:
        rating = "Excellent"
        color = "green"
    elif score >= 70:
        rating = "Good"
        color = "blue"
    elif score >= 50:
        rating = "Fair"
        color = "orange"
    else:
        rating = "Poor"
        color = "red"

    result["quality_score"] = {
        "score": score,
        "rating": rating,
        "color": color,
        "breakdown": {
            "missing_penalty": round((missing.sum() / max(total * len(df.columns), 1)) * 40, 2),
            "duplicate_penalty": round((df.duplicated().sum() / max(total, 1)) * 30, 2),
            "anomaly_penalty": round((anomaly_result.get("total_anomalies", 0) / max(total, 1)) * 30, 2),
        },
    }

    # ── Global recommendations ─────────────────────────────────────────────
    result["recommendations"] = _global_recommendations(result)

    return result


def sanitize_for_json(obj):
    """Recursively replace NaN, inf, -inf with None for JSON serialization."""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    elif isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return obj
    else:
        return obj


# ─── Suggestion helpers ──────────────────────────────────────────────────────
def _missing_suggestions(series: pd.Series, col: str) -> list:
    tips = []
    pct = series.isnull().mean() * 100
    if pd.api.types.is_numeric_dtype(series):
        mean_val = series.mean()
        median_val = series.median()
        tips.append(f"Fill with mean ({round(mean_val, 2) if not pd.isna(mean_val) else 'N/A'}) for normally distributed data.")
        tips.append(f"Fill with median ({round(median_val, 2) if not pd.isna(median_val) else 'N/A'}) if data is skewed.")
        tips.append("Use KNN or iterative imputation for correlated columns.")
    else:
        mode_val = series.mode()[0] if not series.mode().empty else "N/A"
        tips.append(f"Fill with mode ('{mode_val}') for categorical data.")
        tips.append("Use 'Unknown' or a dedicated placeholder category.")
        tips.append("Apply forward/backward fill if data is time-ordered.")
    if pct > 50:
        tips.append(f"⚠️  {round(pct, 1)}% missing – consider dropping this column entirely.")
    elif pct > 20:
        tips.append(f"⚠️  {round(pct, 1)}% missing – investigate data collection pipeline.")
    return tips


def _duplicate_suggestions(df: pd.DataFrame) -> list:
    dup_count = df.duplicated().sum()
    tips = []
    if dup_count == 0:
        return ["No duplicates found – dataset is clean on this dimension."]
    tips.append(f"Remove {dup_count} exact duplicate rows using df.drop_duplicates().")
    tips.append("Verify whether duplicates are intentional (e.g., repeated measurements).")
    tips.append("Check for near-duplicates using fuzzy matching on key columns.")
    tips.append("Audit the data pipeline / ETL process that produced duplicates.")
    if dup_count / len(df) > 0.1:
        tips.append("⚠️  >10% duplicates – likely a systemic ingestion issue.")
    return tips


def _anomaly_suggestions(df: pd.DataFrame, numeric_cols: list, anomaly_indices: list) -> list:
    tips = [
        "Inspect flagged rows manually – anomalies may be genuine rare events or data errors.",
        "Use domain knowledge to set realistic value bounds per column.",
        "Apply Winsorization (capping at 1st/99th percentile) for statistical robustness.",
        "Log-transform highly skewed columns before re-running detection.",
        "Cross-validate anomalies against source systems or raw data files.",
    ]
    if len(anomaly_indices) / max(len(df), 1) > 0.1:
        tips.append("⚠️  High anomaly rate – consider adjusting contamination parameter or reviewing data source.")
    return tips


def _global_recommendations(result: dict) -> list:
    recs = []
    score = result["quality_score"]["score"]
    missing_total = result["missing_values"]["total_missing"]
    dup_total = result["duplicates"]["total_duplicate_rows"]
    anomaly_total = result["anomaly_detection"].get("total_anomalies", 0)

    if missing_total > 0:
        recs.append({
            "priority": "High" if missing_total > 100 else "Medium",
            "category": "Missing Data",
            "action": f"Address {missing_total} missing values using imputation or removal.",
        })
    if dup_total > 0:
        recs.append({
            "priority": "High" if dup_total > 50 else "Low",
            "category": "Duplicates",
            "action": f"Remove or investigate {dup_total} duplicate rows.",
        })
    if anomaly_total > 0:
        recs.append({
            "priority": "Medium",
            "category": "Anomalies",
            "action": f"Review {anomaly_total} anomalous records flagged by Isolation Forest.",
        })
    if score >= 85:
        recs.append({"priority": "Info", "category": "Overall", "action": "Dataset quality is excellent. Proceed with analysis."})
    else:
        recs.append({"priority": "High", "category": "Overall", "action": "Apply all fixes above before using this dataset in ML models."})
    return recs


# ─── PDF Report Generator ────────────────────────────────────────────────────
def generate_pdf_report(analysis: dict, filename: str, report_path: str):
    doc = SimpleDocTemplate(report_path, pagesize=A4,
                            rightMargin=0.75*inch, leftMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title", parent=styles["Title"], fontSize=20,
                                 textColor=colors.HexColor("#1a1a2e"), spaceAfter=6)
    h1_style = ParagraphStyle("H1", parent=styles["Heading1"], fontSize=14,
                               textColor=colors.HexColor("#16213e"), spaceBefore=14, spaceAfter=4)
    h2_style = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=11,
                               textColor=colors.HexColor("#0f3460"), spaceBefore=8, spaceAfter=3)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9,
                                leading=14, textColor=colors.HexColor("#333333"))
    tag_style = ParagraphStyle("Tag", parent=styles["Normal"], fontSize=8,
                               textColor=colors.HexColor("#555555"), leftIndent=12)

    story = []

    # Header
    story.append(Paragraph("Data Quality & Anomaly Detection", title_style))
    story.append(Paragraph("Analysis Report", ParagraphStyle("Sub", parent=styles["Normal"],
                 fontSize=13, textColor=colors.HexColor("#0f3460"), spaceAfter=4)))
    story.append(Paragraph(f"File: <b>{filename}</b> &nbsp;|&nbsp; Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                 ParagraphStyle("Meta", parent=styles["Normal"], fontSize=8,
                                textColor=colors.grey, spaceAfter=8)))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#0f3460")))
    story.append(Spacer(1, 10))

    # Quality Score Banner
    qs = analysis["quality_score"]
    score_color = {"Excellent": "#27ae60", "Good": "#2980b9", "Fair": "#e67e22", "Poor": "#e74c3c"}.get(qs["rating"], "#888")
    score_table = Table([[
        Paragraph(f"<b>{qs['score']}/100</b>", ParagraphStyle("Score", fontSize=26,
                  textColor=colors.white, alignment=TA_CENTER)),
        Paragraph(f"<b>{qs['rating']}</b><br/><font size=8>Quality Rating</font>",
                  ParagraphStyle("Rating", fontSize=16, textColor=colors.white, alignment=TA_CENTER)),
    ]], colWidths=[2*inch, 4.5*inch])
    score_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(score_color)),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.HexColor(score_color)]),
        ("BOX", (0, 0), (-1, -1), 1, colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(score_table)
    story.append(Spacer(1, 10))

    # Penalty breakdown
    bd = qs["breakdown"]
    pen_data = [
        ["Penalty Category", "Points Deducted"],
        ["Missing Values Penalty", f"-{bd['missing_penalty']}"],
        ["Duplicate Rows Penalty", f"-{bd['duplicate_penalty']}"],
        ["Anomaly Penalty", f"-{bd['anomaly_penalty']}"],
        ["Final Score", f"{qs['score']}/100"],
    ]
    pen_table = Table(pen_data, colWidths=[3.5*inch, 3*inch])
    pen_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (1, 1), (-1, -2), [colors.HexColor("#f8f9fa"), colors.white]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#eaf4fb")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
        ("ALIGN", (1, 0), (1, -1), "CENTER"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(pen_table)
    story.append(Spacer(1, 12))

    # Dataset Overview
    story.append(Paragraph("1. Dataset Overview", h1_style))
    ov = analysis["overview"]
    ov_data = [
        ["Metric", "Value"],
        ["Total Rows", str(ov["total_rows"])],
        ["Total Columns", str(ov["total_columns"])],
        ["Memory Usage", f"{ov['memory_usage_kb']} KB"],
        ["Columns", ", ".join(ov["columns"])],
    ]
    ov_table = Table(ov_data, colWidths=[2.5*inch, 4*inch])
    ov_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#16213e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8f9fa"), colors.white]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("WORDWRAP", (1, -1), (1, -1), True),
    ]))
    story.append(ov_table)
    story.append(Spacer(1, 10))

    # Missing Values
    story.append(Paragraph("2. Missing Values Analysis", h1_style))
    mv = analysis["missing_values"]
    story.append(Paragraph(f"Total missing cells: <b>{mv['total_missing']}</b>", body_style))
    if mv["columns_with_missing"]:
        for col, info in mv["columns_with_missing"].items():
            story.append(Spacer(1, 4))
            story.append(Paragraph(f"<b>{col}</b> — {info['count']} missing ({info['percentage']}%)", h2_style))
            for tip in info["suggestions"]:
                story.append(Paragraph(f"• {tip}", tag_style))
    else:
        story.append(Paragraph("✅ No missing values found.", body_style))
    story.append(Spacer(1, 10))

    # Duplicates
    story.append(Paragraph("3. Duplicate Records Analysis", h1_style))
    dup = analysis["duplicates"]
    story.append(Paragraph(f"Duplicate rows: <b>{dup['total_duplicate_rows']}</b> ({dup['duplicate_percentage']}%)", body_style))
    story.append(Spacer(1, 4))
    for tip in dup["suggestions"]:
        story.append(Paragraph(f"• {tip}", tag_style))
    story.append(Spacer(1, 10))

    # Anomaly Detection
    story.append(Paragraph("4. Anomaly Detection Results", h1_style))
    ad = analysis["anomaly_detection"]
    if "total_anomalies" in ad:
        story.append(Paragraph(
            f"Anomalies detected: <b>{ad['total_anomalies']}</b> ({ad['anomaly_percentage']}%) "
            f"out of {ov['total_rows']} rows using Isolation Forest.", body_style))
        story.append(Spacer(1, 6))
        if "column_outliers" in ad:
            story.append(Paragraph("Column-level Outlier Summary (IQR method):", h2_style))
            out_header = ["Column", "Outliers", "Lower Bound", "Upper Bound"]
            out_rows = [[col,
                         str(info["outlier_count"]),
                         str(info["lower_bound"]),
                         str(info["upper_bound"])]
                        for col, info in ad["column_outliers"].items()]
            out_table = Table([out_header] + out_rows,
                              colWidths=[2*inch, 1.2*inch, 1.7*inch, 1.7*inch])
            out_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f3460")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#fef9e7"), colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.append(out_table)
        story.append(Spacer(1, 6))
        story.append(Paragraph("Anomaly Suggestions:", h2_style))
        for tip in ad.get("suggestions", []):
            story.append(Paragraph(f"• {tip}", tag_style))
    else:
        story.append(Paragraph(ad.get("note", "No anomaly results available."), body_style))
    story.append(Spacer(1, 10))

    # Recommendations
    story.append(Paragraph("5. Priority Recommendations", h1_style))
    priority_colors = {"High": "#e74c3c", "Medium": "#e67e22", "Low": "#27ae60", "Info": "#2980b9"}
    rec_data = [["Priority", "Category", "Action"]]
    for rec in analysis["recommendations"]:
        rec_data.append([rec["priority"], rec["category"], rec["action"]])
    rec_table = Table(rec_data, colWidths=[1*inch, 1.4*inch, 4.2*inch])
    rec_style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dee2e6")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    for i, rec in enumerate(analysis["recommendations"], start=1):
        c = colors.HexColor(priority_colors.get(rec["priority"], "#888"))
        rec_style.append(("TEXTCOLOR", (0, i), (0, i), c))
        rec_style.append(("FONTNAME", (0, i), (0, i), "Helvetica-Bold"))
    rec_table.setStyle(TableStyle(rec_style))
    story.append(rec_table)
    story.append(Spacer(1, 12))

    # Column stats
    story.append(Paragraph("6. Column-Level Statistics", h1_style))
    for col, info in analysis["column_stats"].items():
        story.append(Paragraph(f"<b>{col}</b> ({info['dtype']})", h2_style))
        rows = [["Attribute", "Value"]]
        for k, v in info.items():
            if k in ("dtype",):
                continue
            rows.append([k.replace("_", " ").title(), str(v)])
        ct = Table(rows, colWidths=[2*inch, 4.5*inch])
        ct.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf4fb")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#dee2e6")),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(ct)
        story.append(Spacer(1, 6))

    # Footer
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#dee2e6")))
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        "Generated by Data Quality & Anomaly Detection System | Swizosoft (OPC) Pvt Ltd",
        ParagraphStyle("Footer", parent=styles["Normal"], fontSize=7,
                       textColor=colors.grey, alignment=TA_CENTER)))

    doc.build(story)


# ─── Routes ──────────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return FileResponse("frontend/index.html")


@app.post("/api/analyse")
async def analyse(file: UploadFile = File(...)):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files are supported currently.")

    content = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(content))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")

    if df.empty:
        raise HTTPException(status_code=400, detail="Uploaded CSV is empty.")

    analysis = analyse_dataset(df)

    # Sanitize NaN/inf values for JSON serialization
    analysis = sanitize_for_json(analysis)

    # Save to DB (no-op if DB unavailable)
    save_analysis_to_db(
        file.filename,
        analysis["quality_score"]["score"],
        analysis["overview"]["total_rows"],
        analysis["missing_values"]["total_missing"]
        + analysis["duplicates"]["total_duplicate_rows"]
        + analysis["anomaly_detection"].get("total_anomalies", 0),
    )

    # Generate PDF
    report_id = str(uuid.uuid4())[:8]
    report_filename = f"report_{report_id}.pdf"
    report_path = os.path.join(REPORT_DIR, report_filename)
    try:
        generate_pdf_report(analysis, file.filename, report_path)
        analysis["report_id"] = report_filename
    except Exception as e:
        analysis["report_error"] = str(e)

    return JSONResponse(content=analysis)


@app.get("/api/download/{report_filename}")
async def download_report(report_filename: str):
    path = os.path.join(REPORT_DIR, report_filename)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Report not found.")
    return FileResponse(path, media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{report_filename}"'})
