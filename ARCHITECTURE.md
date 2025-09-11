# Architecture Overview (Initial)

This repository is a minimal monorepo scaffold. It will evolve as the design matures.

## Current Structure
- `backend/` — placeholder for the Python backend service
- `frontend/` — placeholder for the React frontend application
- Root files:
  - `README.md` — project overview and layout
  - `ARCHITECTURE.md` — architecture outline (this document)
  - `.gitignore` — repository ignore rules

Note: This document will be updated as we implement components and refine the architecture.

## Configuration & Secrets

- `backend/.env.example` lists required variables for the backend.
- `backend/.env` is local-only and git-ignored; do not commit real values.
- The frontend will use public keys later via its own env file (separate from backend).
