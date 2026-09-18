# Agent Service Boilerplate

A starting point for LangGraph services on FastAPI. The
plumbing you would otherwise rebuild every time — settings, structured logging,
request correlation, tracing, error envelopes, a model gateway, Docker — is
already here, so a new project is a state model and a few prompts.

The bundled example is a **poet and a critic**: the poet writes a draft, the
critic judges it, the poet revises, and the loop stops on approval or when it
runs out of attempts. That generate → judge → revise shape is the reusable
piece; the poem is just the demonstration.

## Quick start

```bash
cp .env.example .env
cp deploy/litellm/.env.example deploy/litellm/.env   # set OPENAI_API_KEY
cp deploy/otel/.env.example deploy/otel/.env         # set the Langfuse keys
docker compose up --build
```

- API docs: <http://localhost:8000/docs>
- Health probe: `GET /health` (unversioned)
- Write a poem: `POST /api/v1/poems`
- LiteLLM UI (spend, keys, models): <http://localhost:4000/ui>
- Langfuse (traces): [US cloud](https://us.cloud.langfuse.com) or [EU cloud](https://cloud.langfuse.com) — this stack does not run Langfuse locally, you set an env variable in otel collector to send the metrics to Langfuse or any other backend.

```bash
curl -X POST http://localhost:8000/api/v1/poems \
  -H 'Content-Type: application/json' \
  -d '{"topic": "a lighthouse in fog", "max_iterations": 3}'
```

To run the API on the host instead, start the gateway with
`docker compose up litellm litellm-db otel-collector`, point the app at it with
`LLM_BASE_URL=http://localhost:4000/v1` and
`OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318`, then:

```bash
uv sync
uv run uvicorn --factory app.api.server:create_app --reload
```

## Layout

```
src/app/
  api/                      app factory, ASGI middleware, DI, error envelope
    v1/                     versioned routes and request/response schemas
  config/                   settings, logging, telemetry
  orchestrator/
    critique_loop.py        the generate/judge/revise graph, shared by all workflows
    llm.py                  the chat model, pointed at the gateway
    registry.py             the one place workflows are declared
    workflows/poetry/       the worked example: state, prompts, graph
deploy/
  litellm/                  model gateway config (not shipped in the app image)
  otel/                     collector config
```

## Adding a workflow

`build_critique_loop` owns the graph topology, the iteration cap, the approval
bookkeeping and the tracing. A workflow supplies a state model, an output model
and prompts.

1. Create `src/app/orchestrator/workflows/<name>/`.
2. Define a state model inheriting `CritiqueLoopState` and an output model.
3. Write `generate_prompt(state)` and `judge_prompt(state)`. The generator gets
   the whole state, so it branches on `state.feedback` to choose between a
   first-pass and a revision prompt.
4. Expose `build_<name>_graph(llm=None)` returning `build_critique_loop(...)`.
5. Register it in `registry.py`, add a `graph_dependency("<name>")` in
   `api/dependencies.py`, and add a route.

Graphs are compiled once in the app lifespan and stored on `app.state.graphs`,
so nothing is built at import time and routes can be tested with a stub graph.
The `llm` argument is what makes the loop testable: pass a fake chat model and
the whole poet/critic cycle runs without a network. See
`tests/test_critique_loop.py`.

## The model gateway

Every model call goes through a [LiteLLM](https://docs.litellm.ai) proxy. The
application authenticates to the proxy with `LLM_API_KEY` and holds **no
provider credentials**; the proxy holds those and handles routing, fallbacks,
rate limits and cost accounting.

Models are referenced by alias (`default`, `fast`) declared in
`deploy/litellm/config.yaml`, never by vendor model name, so switching provider
is a change to that one file. Provider keys must always be written as
`os.environ/NAME` — `tests/test_deploy_config.py` fails otherwise.

### Checking spend and settings locally

`docker compose up` publishes the proxy at <http://localhost:4000/ui> (the
override file is what opens that port). Sign in with
`LITELLM_MASTER_KEY` from `deploy/litellm/.env` — the same value as
`LLM_API_KEY` in the root `.env`. From the UI you can:

- inspect **Usage / spend** per key, model and request
- see which aliases are live and edit virtual keys
- confirm the proxy is the only place holding `OPENAI_API_KEY`

Port 4000 is a local convenience. `docker compose -f compose.yml up` does not
publish it; the API still reaches the proxy on the internal Compose network.

## Configuration

All settings come from the environment (see `.env.example`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_API_KEY` | required | Shared secret for the gateway; matches `LITELLM_MASTER_KEY` |
| `LLM_BASE_URL` | `http://litellm:4000/v1` | Gateway endpoint |
| `LLM_MODEL` | `default` | Model alias from `deploy/litellm/config.yaml` |
| `MAX_ITERATIONS` | `3` | Default cap on generate/judge rounds |
| `LOG_LEVEL` | `INFO` | Level for the `app` logger tree |
| `LOG_FORMAT` | `text` | `text` locally, `json` when deployed |
| `CORS_ALLOW_ORIGINS` | `["*"]` | JSON array of allowed origins |
| `OTEL_ENABLED` | `true` | Enable OTLP trace and metric export |
| `OTEL_SERVICE_NAME` | `agent-service` | Service name attached to telemetry |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4318` | Collector OTLP/HTTP endpoint |

## Observability

Traces go to an OpenTelemetry Collector, which forwards them to Langfuse and
mirrors everything to its own logs. Three things are instrumented:

- **HTTP**, by `FastAPIInstrumentor`.
- **Model calls**, by `LangChainInstrumentor`, which is what puts prompts,
  model names, token counts and latency inside the request span.
- **Loop structure**, by explicit `<workflow>.generate` and `<workflow>.judge`
  spans carrying the iteration number and the approval decision, so a trace
  shows how many revisions a request took.

The LiteLLM proxy also reports to the collector, so gateway latency lands in
the same traces. Dollar spend is tracked in the LiteLLM UI, not in Langfuse.

### Looking at traces in Langfuse

Langfuse is a **hosted** project, not a container in this compose file. Create
a project at [Langfuse Cloud](https://langfuse.com), copy the public and secret
keys into `deploy/otel/.env`, and point `LANGFUSE_OTEL_ENDPOINT` at the region
you signed up in (the example defaults to US:
`https://us.cloud.langfuse.com/api/public/otel`; EU is
`https://cloud.langfuse.com/api/public/otel`).

After a request to `/api/v1/poems`, open the matching cloud UI:

- US: <https://us.cloud.langfuse.com>
- EU: <https://cloud.langfuse.com>

You should see an HTTP span for the request, `poetry.generate` /
`poetry.judge` spans for each loop iteration, and nested LangChain spans with
model name, prompt and token counts. If traces are missing, the collector
printed what it received:

```bash
docker compose logs -f otel-collector
```

Langfuse ingests OTLP traces, not general-purpose metrics or logs. Those stay on
the debug exporter; route them to a dedicated backend for production.

## Logging

`setup_logging()` loads `src/app/config/logging/logging.yaml` and applies
`LOG_LEVEL` and `LOG_FORMAT` at runtime. Every request gets an `X-Request-ID`
(generated, or reused from the incoming header) bound to a `ContextVar` and
stamped on every log line, including uvicorn's access logs. In `json` mode each
line also carries `trace_id` and `span_id`, so a log line can be opened as a
trace.

Every failure returns the same envelope, and `request_id` in the body matches
the response header:

```json
{"error": "workflow_failed", "detail": "...", "request_id": "6f1c..."}
```

## Development

```bash
uv sync
uv run pre-commit install   # optional: runs the fast checks on commit

uv run pytest               # tests, with a 90% coverage gate
uv run ruff check .         # lint
uv run ruff format .        # format
uv run mypy                 # types
```

There is no CI pipeline: this is a template, so the checks are yours to run and
yours to wire up however your project does it. The pre-commit hooks above are
the fast subset, including a `gitleaks` scan so a key never reaches a commit.

## Before you deploy this

The defaults are tuned for a first local run, not for production. At minimum:

- Replace `LITELLM_MASTER_KEY` and `LITELLM_SALT_KEY` with generated secrets,
  and narrow `CORS_ALLOW_ORIGINS`.
- Pin the `litellm`, `postgres` and collector images to digests.
- Add authentication and rate limiting to the API. There is no auth layer here;
  `api/dependencies.py` is where it belongs.
- Add a LangGraph checkpointer if you want resumable or streamable runs.
- Set `LOG_FORMAT=json`.
