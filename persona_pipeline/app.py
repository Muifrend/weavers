from __future__ import annotations

import argparse
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .pipeline import PersonaPipeline
from .population import PopulationPipeline
from .weave_support import init_weave


DEFAULT_OUTPUT_DIR = "generated_personas"


class PersonaAppHandler(BaseHTTPRequestHandler):
    server_version = "PersonaPipelineApp/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(app_html())
            return
        if parsed.path == "/api/health":
            self.send_json({"status": "ok"})
            return
        if parsed.path == "/api/personas":
            query = parse_qs(parsed.query)
            output_dir = query.get("output_dir", [DEFAULT_OUTPUT_DIR])[0]
            self.send_json(list_persona_files(output_dir))
            return
        if parsed.path.startswith("/api/personas/"):
            persona_id = unquote(parsed.path.removeprefix("/api/personas/"))
            output_dir = parse_qs(parsed.query).get("output_dir", [DEFAULT_OUTPUT_DIR])[0]
            persona = read_persona_file(output_dir, persona_id)
            if persona is None:
                self.send_json({"error": "persona_not_found"}, status=HTTPStatus.NOT_FOUND)
                return
            self.send_json(persona)
            return
        self.send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self.read_json_body()
        except ValueError as error:
            self.send_json({"error": "invalid_json", "message": str(error)}, status=HTTPStatus.BAD_REQUEST)
            return

        if parsed.path == "/api/population":
            location = str(body.get("location") or "").strip()
            if not location:
                self.send_json({"error": "location_required"}, status=HTTPStatus.BAD_REQUEST)
                return
            output_dir = str(body.get("output_dir") or DEFAULT_OUTPUT_DIR)
            pipeline = PopulationPipeline()
            configure_population_pipeline(pipeline, body)
            result = pipeline.initialize(location, output_dir=output_dir)
            self.send_json(result, status=HTTPStatus.OK if result["status"] == "complete" else HTTPStatus.ACCEPTED)
            return

        if parsed.path == "/api/persona":
            request = str(body.get("request") or "").strip()
            if not request:
                self.send_json({"error": "request_required"}, status=HTTPStatus.BAD_REQUEST)
                return
            pipeline = PersonaPipeline()
            configure_persona_pipeline(pipeline, body)
            result = pipeline.run(
                request,
                source_urls=body.get("source_urls") or [],
                include_packet=bool(body.get("include_packet", True)),
            )
            self.send_json(result, status=HTTPStatus.OK if result["status"] == "complete" else HTTPStatus.ACCEPTED)
            return

        self.send_json({"error": "not_found"}, status=HTTPStatus.NOT_FOUND)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(error.msg) from error
        if not isinstance(parsed, dict):
            raise ValueError("JSON body must be an object.")
        return parsed

    def send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def send_html(self, html: str) -> None:
        payload = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def configure_population_pipeline(pipeline: PopulationPipeline, body: dict[str, Any]) -> None:
    if body.get("census_api_key"):
        pipeline.census.api_key = str(body["census_api_key"])
    if body.get("openai_api_key"):
        pipeline.persona_set_agent.client.api_key = str(body["openai_api_key"])
    if body.get("model"):
        pipeline.persona_set_agent.client.model = str(body["model"])


def configure_persona_pipeline(pipeline: PersonaPipeline, body: dict[str, Any]) -> None:
    if body.get("census_api_key"):
        key = str(body["census_api_key"])
        pipeline.geo_agent.census.api_key = key
        pipeline.demographic_agent.census.api_key = key
    if body.get("openai_api_key"):
        pipeline.generator.client.api_key = str(body["openai_api_key"])
    if body.get("model"):
        pipeline.generator.client.model = str(body["model"])


def list_persona_files(output_dir: str) -> dict[str, Any]:
    root = Path(output_dir)
    if not root.exists():
        return {"output_dir": str(root.resolve()), "personas": []}
    personas = []
    for path in sorted(root.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        personas.append(
            {
                "persona_id": data.get("persona_id") or path.stem,
                "name": data.get("name"),
                "representation_pct": data.get("representation_pct"),
                "path": str(path.resolve()),
            }
        )
    return {"output_dir": str(root.resolve()), "personas": personas}


def read_persona_file(output_dir: str, persona_id: str) -> dict[str, Any] | None:
    safe_id = "".join(char for char in persona_id if char.isalnum() or char in {"_", "-"})
    if not safe_id:
        return None
    path = Path(output_dir) / f"{safe_id}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def app_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Persona Pipeline</title>
  <style>
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #172026; background: #f6f7f4; }
    main { max-width: 1120px; margin: 0 auto; padding: 28px; }
    h1 { font-size: 28px; margin: 0 0 20px; }
    h2 { font-size: 18px; margin: 0 0 12px; }
    section { border-top: 1px solid #d7dbd2; padding: 22px 0; }
    label { display: block; font-size: 13px; font-weight: 650; margin-bottom: 6px; }
    input, textarea { width: 100%; box-sizing: border-box; padding: 10px 12px; border: 1px solid #bfc7bc; border-radius: 6px; background: white; color: #172026; font: inherit; }
    textarea { min-height: 84px; resize: vertical; }
    button { margin-top: 12px; border: 0; border-radius: 6px; background: #245b47; color: white; padding: 10px 14px; font: inherit; font-weight: 700; cursor: pointer; }
    button:disabled { opacity: .6; cursor: wait; }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; }
    .stack { display: grid; gap: 12px; }
    pre { overflow: auto; background: #172026; color: #e7efe7; padding: 16px; border-radius: 6px; min-height: 260px; }
    .muted { color: #607064; font-size: 13px; }
    @media (max-width: 760px) { main { padding: 18px; } .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<main>
  <h1>Persona Pipeline</h1>
  <div class="grid">
    <section>
      <h2>State Persona Set</h2>
      <div class="stack">
        <div><label for="location">Location</label><input id="location" value="California"></div>
        <div><label for="output">Output Directory</label><input id="output" value="generated_personas"></div>
      </div>
      <button id="populationButton">Generate Personas</button>
      <p class="muted">Uses Census ACS plus OpenAI. Persona JSON files are written locally.</p>
    </section>
    <section>
      <h2>Single Persona</h2>
      <label for="request">Request</label>
      <textarea id="request">Create a suburban Milwaukee Latina union electrician persona focused on reproductive rights.</textarea>
      <button id="personaButton">Generate Persona</button>
      <p class="muted">Uses the evidence packet flow and OpenAI structured output.</p>
    </section>
  </div>
  <section>
    <h2>Output</h2>
    <pre id="outputPane">{}</pre>
  </section>
</main>
<script>
const outputPane = document.querySelector("#outputPane");
async function postJson(url, body) {
  const response = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  outputPane.textContent = JSON.stringify(data, null, 2);
}
document.querySelector("#populationButton").addEventListener("click", async event => {
  event.target.disabled = true;
  try { await postJson("/api/population", { location: location.value, output_dir: output.value }); }
  finally { event.target.disabled = false; }
});
document.querySelector("#personaButton").addEventListener("click", async event => {
  event.target.disabled = true;
  try { await postJson("/api/persona", { request: request.value, include_packet: true }); }
  finally { event.target.disabled = false; }
});
</script>
</body>
</html>"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Persona Pipeline local app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--weave-project", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    init_weave(args.weave_project)
    server = ThreadingHTTPServer((args.host, args.port), PersonaAppHandler)
    print(f"Persona Pipeline app running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

