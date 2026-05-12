# Bridge Architecture

## Overview
Bridge is a FastAPI + React application that integrates with the llm-ontology-mapper library.

## Project Structure

### Backend (`/backend`)
- **app/api** - FastAPI route handlers
- **app/services** - Business logic layer
- **app/models** - Pydantic data models
- **app/storage** - Database and persistence layer
- **app/utils** - Utility functions and helpers
- **main.py** - FastAPI application entry point

### Frontend (`/frontend`)
- **src/pages** - Page components
- **src/components** - Reusable UI components
- **src/api** - API client utilities
- **src/types** - TypeScript type definitions

## Technology Stack

### Backend
- **Framework**: FastAPI
- **Package Manager**: uv
- **Language**: Python 3.10+
- **Database**: TBD
- **ORM**: TBD

### Frontend
- **Framework**: React 18
- **Language**: TypeScript
- **Build Tool**: Vite
- **HTTP Client**: Axios
- **Styling**: TBD

## Integration with llm-ontology-mapper
The backend service layer will eventually wrap and utilize the llm-ontology-mapper library. This is a separate dependency that will be added during implementation.

## Development Status
- ⏳ Initial setup: folder structure and placeholder files only
- 🔜 Backend development
- 🔜 Frontend development
- 🔜 Integration with llm-ontology-mapper
