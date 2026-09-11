# Bridge

Bridge is a browser-based ontology mapping application for clinical researchers,
data managers, and developers working with study data dictionaries. It provides a
React UI and FastAPI backend over the
[`llm-ontology-mapper`](https://github.com/courtotlab/llm-ontology-mapper)
Python library so users can map individual variables or whole data dictionaries
to ontology codes, review suggestions, validate existing codes, and export the
results.

The repository is a full-stack app:

```text
backend/   FastAPI application, mapper integration, local config, history, export
frontend/  React + TypeScript + Vite application
```

## Features

- Configure candidate retrieval and AI provider/model settings.
- Run single term mapping from a field name, optional label, data type, clinical
  area, and target ontology allow-list.
- Run batch mapping from CSV, TSV, or XLSX data dictionaries.
- Select upload columns for field name, label, description, data type, and
  optional per-row target ontology.
- Review best matches, explanations, confidence, alternatives, and accepted /
  rejected / pending decisions.
- Promote alternative mappings in single and batch results.
- Cancel running batch jobs; completed partial results are retained as
  interrupted sessions.
- Export enriched batch CSV files that preserve original upload columns and add
  mapping, alternatives, explanations, and decision columns.
- Browse history for term search, batch map, and validation sessions.
- Validate ontology codes against OLS4 and, when environment credentials are
  available, LOINC FHIR lookup.

## Architecture

### Frontend

The frontend is a React 18, TypeScript, Vite app in `frontend/`.

- Routing is defined in `frontend/src/App.tsx` with `react-router-dom`.
- The sidebar links to **Term Search**, **Batch Map**, **Validator**,
  **History**, and **Settings**.
- API calls live in `frontend/src/api/` and use a shared Axios client pointed at
  `http://localhost:8000/api`.
- Shared response/request shapes live in `frontend/src/types/`.
- Session logging is coordinated through `frontend/src/context/SessionContext.tsx`.
- Single term results are also cached in `window.sessionStorage` so the current
  result survives route changes within the browser session.

The current standalone `ReviewPage` and `ExportPage` are placeholder routes and
are not linked from the sidebar. Review and export are implemented inside the
Batch Map and History workflows.

### Backend

The backend is a FastAPI app in `backend/`.

- `app/main.py` loads `.env`, configures CORS, installs exception handlers, and
  mounts route groups under `/api`.
- `app/api/config.py` handles settings, model discovery, connection tests, and
  layer status.
- `app/api/mapping.py` exposes single term mapping at `/api/map/single`.
- `app/api/batch.py` handles upload preview, batch start/status/cancel, review
  decisions, alternative promotion, and CSV export.
- `app/api/history.py` stores and serves session history, JSON exports, and
  history batch CSV exports.
- `app/api/validate.py` validates ontology codes.
- `app/services/mapper_service.py` is the Bridge integration layer around
  `llm-ontology-mapper`.
- `app/storage/config_store.py` persists non-sensitive config to
  `~/.ontology_mapper/config.json` and holds API keys/passwords in backend
  memory only.
- `app/storage/session_store.py` stores session records under
  `~/.ontology_mapper/session_logs/`.

### Ontology Mapping Library

Bridge delegates mapping work to `llm-ontology-mapper`. The dependency source
and pinned git revision are defined in `backend/pyproject.toml` under
`[tool.uv.sources]`. To update it, change the `rev` there and run:

```sh
cd backend
uv lock
uv sync
```

Bridge currently constructs `OntologyMapper` with `use_planned_pipeline=True`.
For every mapping, Bridge builds an LLM provider from the saved settings and
wires it into a `PlannedPipeline`. Public mode uses the mapper's public
retriever. Local mode additionally injects a `LocalSemanticRetriever` configured
with the Settings page SapBERT URL. Disabled mode uses the mapper's disabled
mapping runner instead of a retriever.

## Mapping Flow

For single mapping:

1. The frontend sends `source_term`, optional `source_label`, optional
   `source_type`, optional `entity_type`, and optional `target_ontologies` to
   `/api/map/single`.
2. Bridge validates that a provider and model are configured, and that cloud
   providers have an API key in memory.
3. Bridge uses the human-readable label as the effective retrieval/mapping query
   when a label is provided; otherwise it uses the source term.
4. Bridge normalizes frontend clinical-area values such as
   `phenotype_symptom` to mapper entity types such as `phenotype`.
5. Bridge constructs `OntologyMapper` with the selected retrieval mode, target
   ontology allow-list, `rag_top_k=15`, `max_candidates=20`, and
   `max_alternatives=5`.
6. The mapper planned pipeline performs query planning, routing, retrieval,
   candidate normalization, candidate merging, LLM reranking, and result
   building for public/local retrieval. In disabled mode it uses the disabled
   mapping runner instead of candidate retrieval.
7. Bridge returns the best mapping, confidence, ontology, explanation notes,
   alternatives, provider/model metadata, and retrieval mode for display and
   history.

For batch mapping, Bridge starts an in-memory background job and maps each row
through the same planned mapper integration. Batch jobs reuse mapper instances
for the same target ontology allow-list, record row-level errors as `UNMAPPED`,
auto-accept rows above the configured threshold, reject unmapped rows, and retain
completed rows if cancellation interrupts the job.

## Retrieval Modes

The Settings page exposes **Candidate Retrieval: Finding Ontology Matches** with
these UI labels and backend values:

| UI label | Backend value | Behavior |
| --- | --- | --- |
| Public ontology databases | `public` | Grounded mapping through public ontology services exposed by `llm-ontology-mapper`: EBI OLS4 for OBO-style ontologies, LOINC Search API for LOINC, RxNav for RxNorm, and NIH Clinical Tables for ICD-10. |
| Local semantic search | `local` | Grounded mapping through a local SapBERT/FAISS-compatible service configured by **SapBERT server URL**. Bridge checks the configured URL at `/health` or `/` during Test connection and does not fall back to public APIs for local retrieval. |
| Disabled | `disabled` | Ungrounded mapping. The mapper plans the query but skips candidate retrieval and asks the configured AI model to produce the mapping directly. |

Supported target ontology selections in Bridge are `HPO`, `MONDO`, `EFO`,
`NCIT`, `LOINC`, `ICD10`, `CHEBI`, `SNOMED`, and `RxNorm`. Leaving all target
ontologies unselected allows automatic mapper behavior. Selecting multiple
ontologies creates an allow-list. In batch uploads, a **Target ontology** column
can supply one supported target ontology per row; when that column is selected,
the global target ontology checkboxes are ignored.

Public LOINC retrieval requires LOINC credentials validated in the Settings page
for the current backend process. If public mode includes only LOINC and no
validated credentials are available, mapping fails with a clear error. If public
mode includes LOINC plus non-LOINC targets and credentials are not validated,
Bridge omits LOINC retrieval and includes a warning in mapping notes. Environment
variables are not used as an implicit substitute for Settings-page validation in
interactive mapping.

## Provider And Model Configuration

Settings are split into candidate retrieval and AI model sections. The backend
model is `AppConfig` in `backend/app/models/config.py`.

Supported providers:

- **Ollama Local** (`ollama`): no API key. Uses **Server URL** from `base_url`,
  defaulting to `http://localhost:11434`. The frontend discovers models from
  `/api/tags`; the model field is disabled until models are loaded. Test
  connection verifies the server, checks the exact selected model is installed,
  optionally reads `/api/ps` for the resident model, then runs a short `/api/chat`
  inference test.
- **Ollama Cloud** (`ollama_cloud`): requires an API key. If the configured base
  URL is local or empty, Bridge uses `https://ollama.com`; custom non-local URLs
  are preserved. The first test with no model loads the cloud model catalog but
  does not claim the key is valid. After selecting a model, test connection runs
  `/api/chat` to validate API access and model usability.
- **OpenAI** (`openai`): requires an API key. Test connection lists models,
  filters to chat/text-capable models, and, after a model is selected, validates
  it through the mapper library provider.

  When the provider is OpenAI, Settings also exposes a **Reasoning effort**
  control. Its availability and allowed values depend on a per-model
  capability table Bridge maintains in
  `backend/app/utils/openai_reasoning.py`, since neither the OpenAI API nor
  the `openai` SDK expose this metadata; unrecognized models resolve to "not
  currently supported" rather than a guessed value. Test connection validates
  the configured reasoning effort strictly against the selected model and
  fails with a clear error rather than silently ignoring an unsupported
  choice. The setting is not cosmetic: whenever the provider is OpenAI and a
  reasoning effort is configured, it is forwarded into the planned pipeline
  for real single-term and batch mapping calls, not just the Test connection
  check.
- **Anthropic** (`anthropic`): requires an API key. Test connection lists models
  and, after a model is selected, sends a short message to validate the model.

The **Test connection** button tests both the selected retrieval mode and the AI
provider/model. Saving settings invalidates prior connection and retrieval
validation status. API keys, BioPortal API key, and LOINC password are held only
in backend memory and must be re-entered after the backend restarts. Non-sensitive
settings, including LOINC username, are saved in
`~/.ontology_mapper/config.json`.

`bioportal_api_key` exists in the config model but is not currently used by the
mapping integration.

The Settings page also persists an `rag_auto_accept_threshold` value, but the
mapping backend does not currently read or apply it. Batch Map's own
**Auto-accept above** control (see below) is a separate, page-local threshold
and is not wired to this Settings-page value.

## User Workflows

### Term Search

The **Term Search** page sends a single mapping request with:

- **Field name / variable** (required)
- **The label of the field/variable from your dataset** (optional)
- **Description** (optional contextual information passed to the ontology mapper/query planner to help disambiguate the source field)
- **Data type** (optional)
- **Clinical area** (optional)
- **Target ontologies** (optional multi-select)

The **Strict target ontology** toggle is shown only when EFO is selected as a
target ontology; when enabled, it is forwarded to the mapper.

The result view shows the best match, confidence, ontology, retrieval method,
configured provider/model, explanation details, and alternatives. Users can copy
the selected code, download a CSV for the term result, or click an alternative to
promote it client-side.

### Batch Map

The **Batch Map** page accepts `.csv`, `.tsv`, and `.xlsx` files. Upload preview
returns the row count, columns, and first three records. The frontend attempts to
detect column mappings, then lets the user choose:

- **Field variable name** (required)
- **Human-readable label** (optional)
- **Description** (optional)
- **Data type** (optional)
- **Target ontology** (optional per-row ontology column)

Mapping options include target ontology multi-select and **Auto-accept above**,
a page-local threshold (default 85%) that is separate from the Settings-page
`rag_auto_accept_threshold` described above. Retrieval is controlled entirely
by `Settings.retrieval_mode`.

Batch status is polled every 1.5 seconds while running. Leaving the page or
unmounting the batch component sends a cancellation request; the UI warns users
that leaving the page interrupts the run. Manual cancellation sets the backend
job to `interrupted` and preserves completed rows.

The review table supports:

- filtering by accepted/rejected/pending,
- searching field names, labels, suggested codes, and suggested terms,
- accepting/rejecting individual rows,
- bulk accept high-confidence rows,
- bulk reject unmapped rows,
- resetting decisions,
- expanding alternatives,
- promoting an alternative to the suggested mapping.

### History

History records are created for term searches, batch maps, and validation runs.
Each session stores an input summary, events, status, timestamps, and a result
snapshot when available. History can show complete, error, interrupted, and
in-progress sessions. Users can reopen details, delete sessions, download session
JSON, download term/validation CSVs from the browser, and download enriched batch
CSV from the backend.

### Validator

The **Validator** page accepts ontology codes separated by newlines or commas,
deduplicates them, and submits at most 200 codes to `/api/validate`.
Colon-separated OBO-style codes are looked up through EBI OLS4. Bare LOINC codes
and `LOINC:` codes are looked up through LOINC FHIR only when `LOINC_USERNAME`
and `LOINC_PASSWORD` are present in the backend environment; otherwise they are
reported as not found.

## API Overview

```text
GET    /api/health

GET    /api/config
POST   /api/config
GET    /api/config/status
POST   /api/config/test
POST   /api/config/retrieval-validation/invalidate
GET    /api/config/openai-models
GET    /api/config/anthropic-models
GET    /api/config/ollama-models
POST   /api/config/ollama/models
GET    /api/config/ollama-loaded

POST   /api/map/single

POST   /api/batch/upload-preview
POST   /api/batch/start
GET    /api/batch/status/{job_id}
POST   /api/batch/cancel/{job_id}
PATCH  /api/batch/decision/{job_id}/{row_index}
PATCH  /api/batch/promote/{job_id}/{row_index}
GET    /api/batch/export/{job_id}

POST   /api/history
GET    /api/history
GET    /api/history/{session_id}
PATCH  /api/history/{session_id}/event
PATCH  /api/history/{session_id}/complete
DELETE /api/history/{session_id}
GET    /api/history/{session_id}/export
GET    /api/history/{session_id}/batch-csv

POST   /api/validate
```

## Running Locally

Prerequisites:

- Python 3.10+
- Node.js 18+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Git, because `uv` installs `llm-ontology-mapper` from GitHub
- Ollama, OpenAI, Anthropic, or Ollama Cloud access for AI model calls
- Optional: a SapBERT/FAISS retrieval service for local retrieval

Install backend dependencies:

```sh
cd backend
uv sync
```

Install frontend dependencies:

```sh
cd frontend
npm install
```

Run the backend:

```sh
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Run the frontend:

```sh
cd frontend
npm run dev
```

Open:

```text
http://localhost:5173
```

The backend allows `http://localhost:5173` by default. Override CORS with the
`CORS_ORIGINS` environment variable, using a comma-separated list.

### Optional `.env`

`backend/app/main.py` calls `load_dotenv()`, so a local `backend/.env` can provide
environment variables. Do not commit real secrets. Useful variables include:

```sh
CORS_ORIGINS=http://localhost:5173
LOINC_USERNAME=...
LOINC_PASSWORD=...
```

Provider API keys used by Settings are normally entered in the UI and cached only
in backend memory.

## Docker Compose

The repository includes development Dockerfiles for both services and a
development-only `docker-compose.yml`:

```sh
docker compose up --build
```

This exposes the backend on `http://localhost:8000` and the frontend on
`http://localhost:5173`. The backend image installs dependencies with
`uv sync --frozen`; the frontend image runs Vite with `npm run dev -- --host`.

## Testing

Run backend tests:

```sh
cd backend
uv run pytest
```

Run frontend tests:

```sh
cd frontend
npm test
```

Useful frontend build check:

```sh
cd frontend
npm run build
```

The backend tests cover configuration and connection behavior, planned mapper
integration, ontology normalization, batch API behavior, cancellation,
interrupted history snapshots, enriched exports, validator behavior, and error
translation. Frontend tests cover Settings, Term Search, Batch Map, History,
ontology multi-select, payload normalization, column detection, and batch
alternative promotion.
