# 🏠 California House Price Prediction

> An end-to-end Machine Learning pipeline that trains, tunes, and deploys multiple regression models to predict California median house prices, with a live Streamlit web application and full SHAP explainability.

---

## 📋 Table of Contents
- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Dataset](#dataset)
- [Results](#results)
- [Installation](#installation)
- [Usage](#usage)
- [Project Structure](#project-structure)
- [Screenshots](#screenshots)
- [Future Improvements](#future-improvements)

---

## 🎯 Project Overview

This project builds a production-quality ML system for house price regression, covering:

- **Exploratory Data Analysis** with 7 professional figures
- **Feature Engineering** — 5 derived interaction features
- **Model Benchmarking** — Linear Regression, Ridge, Decision Tree, Random Forest, Gradient Boosting, XGBoost
- **Hyperparameter Tuning** via RandomizedSearchCV
- **Cross-Validation** — 5-fold CV on all models
- **Explainable AI** — SHAP values and feature importance
- **Streamlit App** — interactive web UI for live predictions

---

## 🏗️ Architecture

```
Raw Data (California Housing)
        │
        ▼
  Data Loading & Validation
        │
        ▼
  Exploratory Data Analysis ──────► reports/figures/
        │
        ▼
  Feature Engineering (5 new features)
        │
        ▼
  Train / Test Split (80/20)
        │
        ▼
  StandardScaler
        │
        ▼
  Train 5-6 Models ──► Cross-Validation ──► Baseline Results
        │
        ▼
  RandomizedSearchCV Tuning (top 2 models)
        │
        ▼
  Best Model Selection (by CV R²)
        │
        ▼
  SHAP Explainability ──────────────► reports/figures/
        │
        ▼
  Save Pipeline (Joblib) ──────────► models/best_model.joblib
        │
        ▼
  Streamlit Web App ◄──── models/ + reports/
```

---

## 📊 Dataset

**California Housing Dataset** (scikit-learn built-in)

| Feature | Description |
|---------|-------------|
| MedInc | Median household income (tens of $1000s) |
| HouseAge | Median house age in block group |
| AveRooms | Average rooms per household |
| AveBedrms | Average bedrooms per household |
| Population | Block group population |
| AveOccup | Average occupants per household |
| Latitude | Block group latitude |
| Longitude | Block group longitude |
| **MedHouseVal** | **Target — median house value ($100,000s)** |

- **Rows:** 20,640 &nbsp;|&nbsp; **Columns:** 8 features + 1 target
- **No missing values**

**Engineered features:** RoomsPerPerson, BedroomsPerRoom, BedroomsPerPerson, PopPerRoom, IncomePerOccupant

---

## 🏆 Results

| Model | MAE | RMSE | R² | CV R² |
|-------|-----|------|----|-------|
| Linear Regression | ~$53K | ~$75K | 0.576 | 0.574 |
| Ridge Regression | ~$53K | ~$75K | 0.576 | 0.575 |
| Decision Tree | ~$45K | ~$70K | 0.622 | 0.590 |
| Random Forest | ~$33K | ~$50K | 0.805 | 0.800 |
| Gradient Boosting | ~$37K | ~$54K | 0.776 | 0.772 |
| **XGBoost (Tuned)** | **~$31K** | **~$47K** | **0.830** | **0.825** |

> Actual numbers vary slightly by run. Best model is auto-selected by cross-validation R².

---

## ⚙️ Installation

```bash
# 1. Clone the repository
git clone https://github.com/YOUR_USERNAME/house-price-prediction.git
cd house-price-prediction

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac / Linux

# 3. Install dependencies
pip install -r requirements.txt
```

---

## 🚀 Usage

### Step 1 — Train the full pipeline
```bash
python train.py
```
This runs EDA, trains all models, tunes the best ones, generates all figures, and saves the model.

### Step 2 — Launch the web app
```bash
streamlit run app/streamlit_app.py
```
Open http://localhost:8501 in your browser.

---

## 📁 Project Structure

```
house-price-prediction/
│
├── data/
│   └── housing.csv                  # Auto-generated on first run
│
├── src/
│   ├── data_loader.py               # Dataset loading
│   ├── eda.py                       # Exploratory Data Analysis
│   ├── preprocessing.py             # Feature engineering + scaling
│   ├── models.py                    # Model training + tuning
│   ├── visualizations.py            # Post-training charts
│   └── save_model.py                # Persist / load pipeline
│
├── app/
│   └── streamlit_app.py             # Web application
│
├── models/
│   ├── best_model.joblib            # Saved pipeline
│   └── metrics.json                 # Model metrics
│
├── reports/
│   └── figures/                     # All generated plots (13 PNG files)
│
├── train.py                         # Master orchestrator
├── requirements.txt
└── README.md
```

---

## 📸 Screenshots

> <img width="1896" height="823" alt="Screenshot 2026-06-10 170750" src="https://github.com/user-attachments/assets/448bfe95-79f5-403f-89fd-9f333cb712ba" />
<img width="1915" height="822" alt="Screenshot 2026-06-10 170934" src="https://github.com/user-attachments/assets/c658892b-ab71-495a-b82d-cac0b535cf6f" />




---

## 🔮 Future Improvements

- [ ] Add neural network regressor (PyTorch / Keras)
- [ ] Integrate real-time Zillow / Redfin data via API
- [ ] Add neighbourhood-level features using geopy
- [ ] Deploy to Streamlit Cloud / Hugging Face Spaces
- [ ] Add model drift monitoring with Evidently AI
- [ ] Add unit tests (pytest) and CI/CD pipeline (GitHub Actions)
- [ ] Dockerize the application

---

## 📄 License

MIT License — free to use, modify, and distribute.
