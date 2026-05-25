# Bridge — Ontology Mapping Tool

Bridge is a browser-based tool that helps clinical researchers map study field names to standardised ontology codes (HPO, MONDO, LOINC, ICD-10, SNOMED, and others). It wraps the [llm-ontology-mapper](https://github.com/courtotlab/llm-ontology-mapper) Python library in a full-stack web UI so researchers can run mappings interactively without writing any code.

---

## Project structure

```
courtotlab/llm-ontology-mapper  — the mapping library (separate repo)
courtotlab/bridge               — this repo, the full-stack app
```

```
backend/    FastAPI Python backend
frontend/   React TypeScript frontend
```

---

## Prerequisites

- Python 3.10+
- Node.js 18+
- uv — https://docs.astral.sh/uv/getting-started/installation/
- Ollama (for local AI) — https://ollama.com/download
- Git (required by uv to install the llm-ontology-mapper dependency from GitHub)

> The llm-ontology-mapper library is installed automatically from GitHub by uv — you do NOT need to clone it separately.

---

## Running locally

### 1. Clone the repo

```sh
git clone https://github.com/courtotlab/bridge.git
cd bridge
```

### 2. Install backend dependencies

```sh
cd backend
uv sync
```

This installs all Python dependencies including llm-ontology-mapper directly from GitHub.

### 3. Install frontend dependencies

```sh
cd frontend
npm install
```

### 4. Pull an Ollama model (for local AI — recommended for first run)

```sh
ollama pull llama3.2
```

If you already have one installed, then run ollama serve and it should autopopulate models on frontend automatically, and the server url by default is typically 11434 for Ollama unless explicitly hosting on a different port

### 5. Start the backend

```sh
cd backend
uv run uvicorn app.main:app --reload --port 8000
```

### 6. Start the frontend

```sh
cd frontend
npm run dev
```

### 7. Open the app

```
http://localhost:5173
```

---

## First-time setup

The app opens on the Settings page. Complete these steps before running a search:

1. **Choose an AI provider**
   - Ollama Local is recommended for first run — free, no API key needed, runs on your machine
   - OpenAI, Anthropic, and Ollama Cloud require an API key

2. **Click Test Connection**
   - For Ollama Local: confirms the server is reachable and the model is available
   - For cloud providers: validates the API key and populates the model dropdown

3. **Select a model** from the dropdown that appears after a successful test

4. **Click Save Settings**

5. Layer 3 — LLM in the sidebar should turn green

6. Go to **Term Search** to run your first mapping

> API keys are held in memory only and must be re-entered after the backend restarts. All other settings are saved to `~/.ontology_mapper/config.json`.

---

## Pipeline layers

The three layers shown in the sidebar correspond to the three stages of the mapping pipeline:

**Layer 1 — Smart Term Extraction**
Uses scispaCy NER to extract the key biomedical concept from abbreviated field names before mapping (e.g. extracts "hypertension" from "htn_diag_age"). Requires scispaCy to be installed. Disable if not installed.

**Layer 2 — Candidate Retrieval**
Finds candidate ontology codes before asking the AI:
- Public ontology databases — queries EBI OLS4, LOINC, RxNav, NIH Clinical Tables (no setup required)
- Local semantic search — uses a SapBERT+FAISS server for faster offline-capable retrieval
- Disabled — AI maps directly without candidate lookup

**Layer 3 — AI Model**
The LLM that selects the best ontology code from candidates. Supports Ollama Local, Ollama Cloud, OpenAI, and Anthropic.

---

## Running with Docker (backend only)

```sh
docker build -t bridge-backend -f backend/Dockerfile backend/
docker run -p 8000:8000 bridge-backend
```

The frontend is not Dockerised yet — run it separately with `npm run dev`.

> The Docker image requires internet access during the build to clone llm-ontology-mapper from GitHub. Git is installed in the image for this purpose.

---

## Current status

### Built and working

- **Settings & configuration page** — all three layers configurable, real connection testing, model dropdown population, layer status indicators in sidebar
- **Single term search** — form with field name, label, data type, clinical area, target ontologies; best match card with confidence badge, AI reasoning, copy code, download CSV; alternatives table with click-to-promote

### Not yet implemented

- **Batch upload** (UC2) — stub page only
- **Review table** (UC3) — stub page only
- **Validator** (UC3) — stub page only
- **Export** (UC4) — stub page only
- **History** (UC4) — stub page only

### Known limitations

- LLM output parser — some models return markdown-wrapped JSON which the library parser does not handle; workaround in progress
- Model name matching — configure model names with the `:latest` tag (e.g. `llama3.2:latest`) to match Ollama's naming exactly

### In progress

- Output parser fix for llm-ontology-mapper
- Improved retrieval using human-readable label as query

---

## Development notes

The llm-ontology-mapper dependency is pinned to a specific commit hash in [backend/pyproject.toml](backend/pyproject.toml). To update to a newer version of the library, update the `rev` value in `pyproject.toml` and re-run `uv lock`.

CORS is configured via the `CORS_ORIGINS` environment variable. The default allows `localhost:5173` for local development.
