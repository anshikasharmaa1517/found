# Found

Sourced disaster reports with a provenance agent, built on AWS.

Every report is stored as a claim made by a source. Claims are never overwritten.
A watcher alerts followers when a new claim changes what is known about someone,
and an agent traces where a report got its information, with every step cited.

## Layout

| Path | Contents |
| --- | --- |
| `backend/found_core` | Domain package shared by every Lambda |
| `backend/handlers` | Lambda entry points |
| `infra` | AWS CDK app |
| `agent` | Provenance agent and evals |
| `web` | React web app |
| `data` | Dataset generator and demo fixtures |
| `docs/PROJECT_DESIGN.md` | Full design |

## Backend tests

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest -q
```
