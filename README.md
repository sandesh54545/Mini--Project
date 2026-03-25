# Data Quality & Anomaly Detection System
**Swizosoft (OPC) Pvt Ltd** | Sandesh Walvekar & Shrinivas Motar | MMEC CSE

---

## Project Structure

```
data_quality_system/
├── backend/
│   └── main.py              # FastAPI app — all routes, analysis, PDF generation
├── frontend/
│   ├── index.html           # Main SPA page
│   └── static/
│       ├── css/style.css    # Dark navy + cyan theme
│       └── js/app.js        # Fetch, render, tab logic
├── uploads/                 # Temporary CSV uploads (auto-created)
├── reports/                 # Generated PDF reports (auto-created)
├── requirements.txt
└── README.md
```

---

## Setup in VS Code

### 1. Open project
```bash
cd data_quality_system
code .
```

### 2. Create virtual environment (recommended)
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. (Optional) MySQL setup
Create a database named `data_quality_db`. The app gracefully skips DB
persistence if MySQL is unavailable.
```sql
CREATE DATABASE data_quality_db;
```
Set environment variables if your MySQL credentials differ from defaults:
```bash
export DB_HOST=localhost
export DB_USER=root
export DB_PASSWORD=yourpassword
export DB_NAME=data_quality_db
```

### 5. Run the server
```bash
cd data_quality_system          # make sure you're here
uvicorn backend.main:app --reload --port 8000
```

Open → http://localhost:8000

---

## Usage

1. Open http://localhost:8000 in your browser
2. **Upload** any CSV file (drag & drop or browse)
3. Click **Analyse Dataset**
4. Review tabs:
   - **Missing Values** — per-column count, % and fix suggestions
   - **Duplicates** — count, % and clean-up suggestions + sample rows
   - **Anomaly Detection** — Isolation Forest + IQR outliers per column
   - **Column Stats** — min/max/mean/std/skewness for numeric; top-values for categorical
   - **Recommendations** — prioritised action list
5. Click **⬇ Download PDF Report** for a structured, printable report

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| Backend | FastAPI |
| Data Processing | Pandas, NumPy |
| Machine Learning | Scikit-learn (IsolationForest) |
| PDF Generation | ReportLab |
| Database | MySQL (optional) |
| Frontend | HTML, CSS, Vanilla JS |
| Dev Tools | VS Code + Uvicorn |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve frontend |
| POST | `/api/analyse` | Upload CSV → full analysis JSON |
| GET | `/api/download/{id}` | Download PDF report |

---

## Future Enhancements
- Excel & JSON dataset support
- Real-time data quality monitoring
- Interactive chart visualisations
- Automated data cleaning export
- User authentication & history
