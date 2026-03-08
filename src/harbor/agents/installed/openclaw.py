"""Harbor agent adapter for the openclaw personal-assistant CLI.

openclaw (https://github.com/openclaw/openclaw) can run in two modes:
  - Gateway mode (default): requires a background daemon – incompatible with Harbor.
  - Local-embedded mode (``--local``): runs the LLM call in-process – used here.

Invocation pattern
------------------
openclaw agent --local --json --agent harbor-task --message "<instruction>"

The ``--json`` flag makes openclaw write a single JSON object to stdout instead
of streaming human-readable text.  The JSON is tee'd to
/logs/agent/openclaw.txt so ``populate_context_post_run`` can read it back
from the host-side ``logs_dir``.

Multi-provider support
----------------------
The model_name follows Harbor's ``"provider/model"`` convention.  Supported
providers:

  * ``anthropic``   → anthropic-messages API (ANTHROPIC_API_KEY)
  * ``openai``      → openai-chat API (OPENAI_API_KEY; OPENAI_BASE_URL optional)
  * ``openrouter``  → openai-chat API via openrouter.ai (OPENROUTER_API_KEY)
  * ``<other>``     → openai-chat API with OPENAI_BASE_URL / <PROVIDER>_BASE_URL
                      and <PROVIDER>_API_KEY

MCP servers
-----------
**EXPERIMENTAL / UNVERIFIED** — openclaw's ACP translator currently logs
``ignoring N MCP servers`` and sets ``mcpCapabilities: {http: false, sse: false}``.
This means external MCP tool servers may NOT be available to the agent during
task execution.  The mcporter bridge (npm i -g mcporter) is used internally by
openclaw's memory/QMD subsystem, not for general MCP tool integration.

The ``_build_register_mcp_servers_command()`` hook is kept as a forward-
compatibility placeholder in case openclaw adds native MCP support.

Skills
------
Skills (SKILL.md files) are copied from ``self.skills_dir`` into the openclaw
workspace at ``$STATE_DIR/workspace/skills/``.  openclaw auto-scans that path
when ``workspace`` is set in the agent config.

ATIF trajectory
---------------
Session transcripts are written by openclaw to::

    $OPENCLAW_STATE_DIR/agents/harbor-task/sessions/<sessionId>.jsonl

Each line is a JSON object (``SessionEvent``).  ``populate_context_post_run``
parses these to produce an ATIF-v1.2 ``trajectory.json``.

Known limitations
-----------------
  • ``cost_usd`` is not populated: openclaw's ``--json`` output does not
    include pricing information.
  • ``baseUrl`` in openclaw's provider config only accepts a plain string
    (not an env-var reference), so base URLs are resolved from host env at
    config-write time and embedded as literal strings in ``openclaw.json``.
"""

import json
import os
import shlex
from pathlib import Path
from typing import Any

from harbor.agents.installed.base import BaseInstalledAgent, ExecInput
from harbor.models.agent.context import AgentContext
from harbor.models.agent.name import AgentName
from harbor.models.trajectories import (
    Agent,
    FinalMetrics,
    Metrics,
    Observation,
    ObservationResult,
    Step,
    ToolCall,
    Trajectory,
)
from harbor.utils.trajectory_utils import format_trajectory_json

# Container-side path used as OPENCLAW_STATE_DIR.
# Config + session transcripts both live here so they end up in /logs/agent.
_STATE_DIR = "/logs/agent/openclaw-state"

# Within the state dir, openclaw stores session transcripts at:
#   agents/<agentId>/sessions/<sessionId>.jsonl
# (the path is derived from resolveAgentSessionsDir inside openclaw)
_AGENT_ID = "harbor-task"

# Harbor task working directory — this is where the verifier checks results.
_WORKSPACE_DIR = "/app"

# Skills directory: openclaw scans <workspace>/skills/**/SKILL.md.
_SKILLS_DIR = f"{_WORKSPACE_DIR}/skills"

# mcporter config path (file is read by the `mcporter` CLI/library,
# which openclaw uses as its MCP bridge).
_MCPORTER_CONFIG = "/root/.mcporter/mcporter.json"


class Openclaw(BaseInstalledAgent):
    """Harbor agent adapter for the openclaw personal-assistant CLI.

    Runs openclaw in ``--local`` mode (no gateway daemon required) with
    ``--json`` output so metrics can be parsed without reading transcript files.
    """

    SUPPORTS_ATIF: bool = True

    _OUTPUT_FILENAME = "openclaw.txt"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Backward compatibility: older harbor releases did not include
        # ``skills_dir`` (and possibly ``mcp_servers``) in BaseAgent.__init__.
        # If the base class hasn't set them we fall back to the values that
        # were passed to us via kwargs (or safe defaults).
        if not hasattr(self, "skills_dir"):
            self.skills_dir: str | None = kwargs.get("skills_dir")
        if not hasattr(self, "mcp_servers"):
            self.mcp_servers: list = list(kwargs.get("mcp_servers") or [])

    @staticmethod
    def name() -> str:
        return AgentName.OPENCLAW.value

    def version(self) -> str:
        return self._version or "latest"

    @property
    def _install_agent_template_path(self) -> Path:
        return Path(__file__).parent / "install-openclaw.sh.j2"

    # ------------------------------------------------------------------
    # Config generation
    # ------------------------------------------------------------------

    def _build_openclaw_config(self) -> dict[str, Any]:
        """Return the ``openclaw.json`` config dict for the current model.

        The ``apiKey`` field uses the env-var-reference format so that the
        actual secret is injected at runtime – never stored in the file.

        Raises:
            ValueError: If ``model_name`` is not in ``"provider/model"`` format,
                or if the base URL for an unknown provider cannot be resolved.
        """
        if not self.model_name or "/" not in self.model_name:
            raise ValueError(
                "model_name must be in 'provider/model' format, "
                f"got: {self.model_name!r}"
            )

        provider, model = self.model_name.split("/", 1)

        # Merge extra_env over os.environ so that callers who pass base URLs
        # via extra_env get the expected override behaviour.  openclaw.json is
        # written before BaseInstalledAgent.run() merges _extra_env into the
        # container environment, so we must resolve base URLs here with the
        # same priority order that the container will see at runtime.
        _env: dict[str, str] = {**os.environ, **self._extra_env}

        match provider:
            case "anthropic":
                # openclaw uses "anthropic-messages" api type for Anthropic.
                # baseUrl must be a plain string (no env-ref support in openclaw).
                api_type: str | None = "anthropic-messages"
                base_url = _env.get(
                    "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
                )
                api_key_env = "ANTHROPIC_API_KEY"

            case "openai":
                api_type = "openai-completions"
                base_url = _env.get(
                    "OPENAI_BASE_URL", "https://api.openai.com/v1"
                )
                api_key_env = "OPENAI_API_KEY"

            case "openrouter":
                api_type = "openai-completions"
                base_url = _env.get(
                    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
                )
                api_key_env = "OPENROUTER_API_KEY"

            case _:
                # Generic OpenAI-compatible provider (e.g. deepseek, together).
                # openclaw requires an explicit "api" field from the enum:
                #   openai-completions | openai-responses | anthropic-messages
                #   | google-generative-ai | github-copilot
                #   | bedrock-converse-stream | ollama
                api_type = "openai-completions"
                base_url = _env.get(
                    f"{provider.upper()}_BASE_URL",
                    _env.get("OPENAI_BASE_URL", ""),
                )
                if not base_url:
                    raise ValueError(
                        f"Cannot resolve base URL for provider '{provider}'. "
                        f"Set {provider.upper()}_BASE_URL or OPENAI_BASE_URL."
                    )
                api_key_env = f"{provider.upper()}_API_KEY"

        return {
            "models": {
                "providers": {
                    provider: {
                        "baseUrl": base_url,
                        "apiKey": {
                            "source": "env",
                            "provider": "default",
                            "id": api_key_env,
                        },
                        "models": [
                            {
                                "id": model,
                                "name": model,
                                "reasoning": False,
                                "input": ["text"],
                                "cost": {
                                    "input": 0,
                                    "output": 0,
                                    "cacheRead": 0,
                                    "cacheWrite": 0,
                                },
                                "contextWindow": 200000,
                                "maxTokens": 8192,
                            }
                        ],
                        # Only include "api" when explicitly set; omitting it lets
                        # openclaw infer the correct type for each provider.
                        **({"api": api_type} if api_type else {}),
                    }
                }
            },
            "agents": {
                "list": [
                    {
                        "id": _AGENT_ID,
                        "default": True,
                        # AgentModelSchema accepts a plain "provider/model" string
                        # (or {primary, fallbacks} object).
                        # The object {provider, model} is NOT valid per the Zod schema.
                        "model": f"{provider}/{model}",
                        # Point openclaw at /app so file operations land in
                        # the task working directory where the verifier checks.
                        "workspace": _WORKSPACE_DIR,
                    }
                ]
            },
        }

    def _resolve_api_key_env(self) -> tuple[str, str]:
        """Return ``(env_var_name, env_var_value)`` for the current provider.

        Returns an empty-string pair when the required variable is not set so
        that the caller can decide whether to raise or silently proceed.
        """
        if not self.model_name or "/" not in self.model_name:
            return "", ""

        provider = self.model_name.split("/", 1)[0]
        match provider:
            case "anthropic":
                key = "ANTHROPIC_API_KEY"
            case "openai":
                key = "OPENAI_API_KEY"
            case "openrouter":
                key = "OPENROUTER_API_KEY"
            case _:
                key = f"{provider.upper()}_API_KEY"

        return key, os.environ.get(key, "")

    # ------------------------------------------------------------------
    # BaseInstalledAgent interface
    # ------------------------------------------------------------------

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        """Return the sequence of shell commands that run the openclaw task.

        Step 1 writes the ``openclaw.json`` config via a heredoc (avoids all
        shell-quoting edge-cases with large JSON blobs).

        Step 2 invokes ``openclaw agent --local --json`` and tees stdout to
        ``/logs/agent/openclaw.txt`` for post-run parsing.
        """
        if not self.model_name or "/" not in self.model_name:
            raise ValueError(
                "model_name must be in 'provider/model' format, "
                f"got: {self.model_name!r}"
            )

        # ------------------------------------------------------------------
        # Build the environment dict
        # ------------------------------------------------------------------
        env: dict[str, str] = {
            "OPENCLAW_STATE_DIR": _STATE_DIR,
        }

        # Inject the API key for the chosen provider
        key_name, key_value = self._resolve_api_key_env()
        if key_value:
            env[key_name] = key_value

        # NOTE: BaseInstalledAgent.run() automatically merges self._extra_env into
        # every ExecInput.env dict, so we must NOT do that manually here – it would
        # be applied twice and could clobber values the caller set intentionally.
        #
        # Base URLs do NOT need to be passed as container env vars: openclaw reads
        # them from the "baseUrl" string field in openclaw.json, which was already
        # expanded from {**os.environ, **self._extra_env} when
        # _build_openclaw_config() ran on the host.  extra_env values therefore
        # take priority over process-level env vars for base URL resolution.

        # ------------------------------------------------------------------
        # Serialize openclaw.json
        # ------------------------------------------------------------------
        config = self._build_openclaw_config()
        config_json = json.dumps(config, indent=2, ensure_ascii=False)

        escaped_instruction = shlex.quote(instruction)

        commands: list[ExecInput] = [
            # Step 1: write openclaw.json via heredoc (avoids all shell-quoting
            # edge-cases: single quotes inside JSON are impossible, so the
            # 'HARBOR_EOF' heredoc delimiter is always safe).
            ExecInput(
                command=(
                    f"mkdir -p {_STATE_DIR} && "
                    f"cat > {_STATE_DIR}/openclaw.json << 'HARBOR_EOF'\n"
                    f"{config_json}\n"
                    "HARBOR_EOF"
                ),
                env=env,
                timeout_sec=30,
            ),
        ]

        # Register MCP servers and skills when provided (Phase 2 extensions).
        mcp_cmd = self._build_register_mcp_servers_command()
        if mcp_cmd:
            commands.append(ExecInput(command=mcp_cmd, env=env, timeout_sec=30))

        skills_cmd = self._build_register_skills_command()
        if skills_cmd:
            commands.append(ExecInput(command=skills_cmd, env=env, timeout_sec=30))

        # Step 2: run openclaw.
        # ``set -o pipefail`` ensures that openclaw's non-zero exit code is not
        # masked by ``tee`` (which always exits 0), so Harbor records the actual
        # failure in command-N/return-code.txt for diagnostic purposes.
        commands.append(
            ExecInput(
                command=(
                    "set -o pipefail; "
                    ". ~/.nvm/nvm.sh 2>/dev/null || true; "
                    "openclaw agent --local --json "
                    f"--agent harbor-task --message {escaped_instruction} "
                    f"2>/logs/agent/openclaw-stderr.txt "
                    f"| tee /logs/agent/openclaw.txt; "
                    # openclaw runs as root inside the container; make all files
                    # under /logs/agent/ world-readable so populate_context_post_run
                    # can parse them from the host before docker stop() chowns.
                    "chmod -R a+rX /logs/agent/ 2>/dev/null || true"
                ),
                env=env,
            )
        )

        return commands

    def populate_context_post_run(self, context: AgentContext) -> None:
        """Parse the JSON output written by openclaw and populate AgentContext.

        openclaw writes a single JSON object to stdout when invoked with
        ``--json``.  We tee that to ``/logs/agent/openclaw.txt`` and read it
        back here.

        Then we parse the JSONL session transcript(s) to produce an ATIF
        ``trajectory.json`` in the task output directory.

        Populated fields:
            - ``context.n_input_tokens``   ← ``meta.agentMeta.usage.input``
            - ``context.n_output_tokens``  ← ``meta.agentMeta.usage.output``
            - ``context.n_cache_tokens``   ← ``meta.agentMeta.usage.cacheRead``

        Not populated:
            - ``context.cost_usd`` — openclaw does not report pricing in its
              ``--json`` output.
        """
        output_path = self.logs_dir / self._OUTPUT_FILENAME
        session_id: str | None = None
        model_name: str = self.model_name or "unknown"

        if not output_path.exists():
            print(f"openclaw: output file not found at {output_path}")
        else:
            raw = output_path.read_text(encoding="utf-8").strip()
            if not raw:
                print("openclaw: output file is empty")
            else:
                # openclaw may emit non-JSON log lines (e.g. [secrets] warnings)
                # before or after the actual JSON object.  Try the whole string
                # first; if that fails, extract the outermost { ... } block.
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    json_start = raw.find("{")
                    json_end = raw.rfind("}")
                    if json_start != -1 and json_end > json_start:
                        try:
                            data = json.loads(raw[json_start : json_end + 1])
                        except json.JSONDecodeError as exc:
                            print(f"openclaw: failed to parse JSON output: {exc}")
                            data = {}
                    else:
                        print("openclaw: no JSON object found in output")
                        data = {}

                meta = data.get("meta", {})
                agent_meta = meta.get("agentMeta", {})
                usage = agent_meta.get("usage", {})

                context.n_input_tokens = usage.get("input", 0)
                context.n_output_tokens = usage.get("output", 0)
                context.n_cache_tokens = usage.get("cacheRead", 0)
                # cost_usd is intentionally left unset: openclaw --json does not
                # include pricing information.

                print(
                    f"openclaw: tokens in={context.n_input_tokens} "
                    f"out={context.n_output_tokens} "
                    f"cache_read={context.n_cache_tokens}"
                )

                # Capture session-id for ATIF lookup (stored in the --json output)
                session_id = (
                    data.get("session", {}).get("id")
                    or agent_meta.get("sessionId")
                    or None
                )
                # Also capture model from the JSON output if available
                model_name = (
                    agent_meta.get("model")
                    or data.get("session", {}).get("model")
                    or model_name
                )

        # ------------------------------------------------------------------
        # ATIF trajectory.json
        # ------------------------------------------------------------------
        if self.SUPPORTS_ATIF:
            # If we didn't get session_id from the JSON output, fall back to
            # looking at any .jsonl file present in the sessions directory.
            try:
                trajectory = self._parse_transcript_to_trajectory(
                    session_id=session_id or "",
                    default_model_name=model_name,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"openclaw: ATIF trajectory parsing failed: {exc}")
                trajectory = None

            if trajectory is not None:
                trajectory_path = self.logs_dir / "trajectory.json"
                trajectory_path.write_text(
                    format_trajectory_json(trajectory.to_json_dict()),
                    encoding="utf-8",
                )
                print(f"openclaw: trajectory.json written ({len(trajectory.steps)} steps)")

    # ------------------------------------------------------------------
    # Optional hooks (Phase 2 / forward-compatibility)
    # ------------------------------------------------------------------

    def _build_register_mcp_servers_command(self) -> str | None:
        """Write a mcporter config for MCP server integration.

        .. warning::

            **EXPERIMENTAL / UNVERIFIED** — openclaw's ACP translator currently
            ignores MCP servers (``mcpCapabilities: {http: false, sse: false}``).
            This hook is kept as a forward-compatibility placeholder; the config
            file may have no runtime effect until openclaw adds native MCP
            tool-server support.
        """
        if not self.mcp_servers:
            return None

        servers: dict[str, dict[str, Any]] = {}
        for server in self.mcp_servers:
            if server.transport == "stdio":
                entry: dict[str, Any] = {
                    "command": server.command,
                    "args": server.args,
                }
            elif server.transport == "streamable-http":
                entry = {"baseUrl": server.url}
            else:  # sse
                entry = {"url": server.url}
            servers[server.name] = entry

        config = json.dumps({"mcpServers": servers}, indent=2)
        escaped = shlex.quote(config)
        return (
            f"mkdir -p /root/.mcporter && "
            f"echo {escaped} > {_MCPORTER_CONFIG}"
        )

    def _build_register_skills_command(self) -> str | None:
        """Copy Harbor skills into openclaw's workspace skills directory.

        openclaw loads ``SKILL.md`` files from ``<workspace>/skills/**/SKILL.md``
        where ``workspace`` is set to ``{_STATE_DIR}/workspace`` in the agent
        config.  We copy the Harbor-provided skills directory there so openclaw
        picks them up automatically on the next run.
        """
        if not self.skills_dir:
            return None
        return (
            f"mkdir -p {_SKILLS_DIR} && "
            f"cp -r {shlex.quote(self.skills_dir)}/* "
            f"{_SKILLS_DIR}/ 2>/dev/null || true"
        )

    # ------------------------------------------------------------------
    # ATIF trajectory parsing
    # ------------------------------------------------------------------

    def _parse_transcript_to_trajectory(
        self, session_id: str, default_model_name: str
    ) -> Trajectory | None:
        """Parse the JSONL session transcript into an ATIF Trajectory.

        openclaw writes one JSON object per line to::

            $STATE_DIR/agents/harbor-task/sessions/<sessionId>.jsonl

        Each line is a ``SessionEvent`` with:
          - ``message.role``    : ``"user"`` or ``"assistant"``
          - ``message.content`` : text string or list of content blocks
          - ``message.usage``   : ``{input, output, cacheRead, cacheWrite}``
          - ``provider``        : provider id string
          - ``model``           : model id string
          - ``timestamp``       : ISO-8601 string

        Content blocks follow Anthropic's format:
          - text    : ``{type: "text",    text: "..."}``
          - tool_use: ``{type: "tool_use", id, name, input: {...}}``
          - tool_result: ``{type: "tool_result", tool_use_id, content}``
        """
        sessions_dir = self.logs_dir / "openclaw-state" / "agents" / _AGENT_ID / "sessions"

        # When session_id is non-empty, try the exact path first.
        transcript_path: Path | None = None
        if session_id:
            candidate = sessions_dir / f"{session_id}.jsonl"
            if candidate.exists():
                transcript_path = candidate

        # Fallback: glob for any .jsonl file in the sessions directory.
        if transcript_path is None:
            candidates = list(sessions_dir.glob("*.jsonl")) if sessions_dir.exists() else []
            if not candidates:
                print(f"openclaw: no transcript found in {sessions_dir}")
                return None
            transcript_path = candidates[0]
            print(f"openclaw: using transcript {transcript_path.name}")

        raw_lines: list[dict[str, Any]] = []
        for line in transcript_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    raw_lines.append(obj)
            except json.JSONDecodeError:
                pass

        if not raw_lines:
            print("openclaw: transcript is empty")
            return None

        # ------------------------------------------------------------------
        # Pass 1: Parse each JSONL event into a "proto-turn" dict.
        # ------------------------------------------------------------------
        proto_turns: list[dict[str, Any]] = []
        total_input = total_output = total_cache_read = 0

        for event in raw_lines:
            message = event.get("message")
            if not isinstance(message, dict):
                continue

            role = message.get("role")
            if role not in ("user", "assistant"):
                continue

            timestamp = event.get("timestamp")
            model_from_event = (
                event.get("model") or message.get("model") or default_model_name
            )
            content = message.get("content", "")

            # Normalise content to a list of blocks
            if isinstance(content, str):
                blocks: list[dict[str, Any]] = [{"type": "text", "text": content}]
            elif isinstance(content, list):
                blocks = [b for b in content if isinstance(b, dict)]
            else:
                blocks = []

            # -- Build metrics for assistant turns --
            metrics: Metrics | None = None
            if role == "assistant":
                usage = message.get("usage") or event.get("usage") or {}
                if isinstance(usage, dict):
                    inp = usage.get("input", 0) or 0
                    out = usage.get("output", 0) or 0
                    cache_read = usage.get("cacheRead", 0) or 0
                    total_input += inp
                    total_output += out
                    total_cache_read += cache_read
                    if inp or out or cache_read:
                        metrics = Metrics(
                            prompt_tokens=inp,
                            completion_tokens=out,
                            cached_tokens=cache_read,
                        )

            # -- Classify content blocks --
            text_parts: list[str] = []
            turn_tool_calls: list[ToolCall] = []
            turn_tool_results: list[ObservationResult] = []

            for block in blocks:
                btype = (block.get("type") or "").lower()

                if btype == "text":
                    text = (block.get("text") or "").strip()
                    if text:
                        text_parts.append(text)

                elif btype in ("tool_use", "toolcall", "tool_call"):
                    call_id = block.get("id") or ""
                    tool_name = block.get("name") or ""
                    arguments = block.get("input") or {}
                    if not isinstance(arguments, dict):
                        arguments = {"input": arguments}
                    turn_tool_calls.append(
                        ToolCall(
                            tool_call_id=call_id,
                            function_name=tool_name,
                            arguments=arguments,
                        )
                    )

                elif btype in ("tool_result", "tool_result_error"):
                    call_id = block.get("tool_use_id") or ""
                    result_content = block.get("content") or ""
                    if isinstance(result_content, list):
                        parts = [
                            (p.get("text") or "")
                            if isinstance(p, dict)
                            else str(p)
                            for p in result_content
                        ]
                        result_text = (
                            "\n".join(p for p in parts if p).strip() or None
                        )
                    else:
                        result_text = str(result_content).strip() or None
                    turn_tool_results.append(
                        ObservationResult(
                            source_call_id=call_id or None,
                            content=result_text,
                        )
                    )

            proto_turns.append(
                {
                    "role": role,
                    "timestamp": timestamp,
                    "model": model_from_event,
                    "text_parts": text_parts,
                    "tool_calls": turn_tool_calls,
                    "tool_results": turn_tool_results,
                    "merged_results": [],
                    "metrics": metrics,
                }
            )

        # ------------------------------------------------------------------
        # Pass 2: Merge tool_result blocks into the preceding assistant turn
        #         that issued the matching tool_use.  This is necessary
        #         because Trajectory.validate_tool_call_references requires
        #         every ObservationResult.source_call_id to reference a
        #         ToolCall.tool_call_id within the SAME Step.
        # ------------------------------------------------------------------
        for i, turn in enumerate(proto_turns):
            if not turn["tool_results"]:
                continue
            # Walk backwards to find the most recent assistant turn with
            # tool_calls that match the source_call_ids.
            for j in range(i - 1, -1, -1):
                prev = proto_turns[j]
                if prev["role"] == "assistant" and prev["tool_calls"]:
                    prev["merged_results"].extend(turn["tool_results"])
                    turn["tool_results"] = []  # consumed
                    break

        # ------------------------------------------------------------------
        # Pass 3: Build ATIF Steps from the (now merged) proto-turns.
        #         Pure tool_result turns that were fully merged into their
        #         parent assistant turn are skipped.
        # ------------------------------------------------------------------
        steps: list[Step] = []
        step_id = 1

        for turn in proto_turns:
            text = "\n\n".join(turn["text_parts"])
            tc = turn["tool_calls"] or None
            all_results = turn["merged_results"] + turn["tool_results"]
            obs = Observation(results=all_results) if all_results else None

            # Skip turns that are now empty (pure tool_result, fully merged)
            if not text and tc is None and obs is None and turn["metrics"] is None:
                continue

            source: str = "user" if turn["role"] == "user" else "agent"

            steps.append(
                Step(
                    step_id=step_id,
                    timestamp=turn["timestamp"],
                    source=source,  # type: ignore[arg-type]
                    model_name=turn["model"] if source == "agent" else None,
                    message=text or "",
                    tool_calls=tc,
                    observation=obs,
                    metrics=turn["metrics"],
                )
            )
            step_id += 1

        if not steps:
            print("openclaw: no valid ATIF steps produced")
            return None

        final_metrics = FinalMetrics(
            total_prompt_tokens=total_input or None,
            total_completion_tokens=total_output or None,
            total_cached_tokens=total_cache_read or None,
            total_cost_usd=None,
            total_steps=len(steps),
        )

        return Trajectory(
            schema_version="ATIF-v1.2",
            session_id=session_id,
            agent=Agent(
                name=AgentName.OPENCLAW.value,
                version=self.version() or "unknown",
                model_name=default_model_name,
            ),
            steps=steps,
            final_metrics=final_metrics,
        )
