"""Openclaw adapter v2 (reference implementation).

This file is a drop-in style redesign proposal based on conflict analysis.
It keeps Harbor-facing entrypoints while adding compatibility with both:
- legacy fixed command mode (`openclaw agent --local --json`)
- configurable CLI backend mode (json/jsonl/text, session modes, stdin/arg)
"""

from __future__ import annotations

import json
import os
import shlex
from datetime import datetime, timezone
from dataclasses import dataclass
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

_STATE_DIR = "/tmp/openclaw-state"
_DEFAULT_AGENT_ID = "harbor-task"
_WORKSPACE_DIR = "/app"
_SKILLS_DIR = f"{_WORKSPACE_DIR}/skills"
_MCPORTER_CONFIG = "/root/.mcporter/mcporter.json"
_COPIED_TRANSCRIPT_FILENAME = "openclaw-session.jsonl"

_OPENAI_COMPAT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "perplexity": "https://api.perplexity.ai",
}


@dataclass
class CliBackendSpec:
    command: str
    args: list[str]
    resume_args: list[str]
    output_mode: str
    input_mode: str
    max_prompt_arg_chars: int
    session_mode: str
    session_arg: str
    session_args: list[str]
    extra_env: dict[str, str]
    clear_env: list[str]

    @classmethod
    def from_env(cls, env: dict[str, str]) -> "CliBackendSpec":
        def _json_list(name: str, default: list[str]) -> list[str]:
            raw = (env.get(name) or "").strip()
            if not raw:
                return default
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(x) for x in parsed]
            except json.JSONDecodeError:
                pass
            return default

        def _csv(name: str, default: list[str]) -> list[str]:
            raw = (env.get(name) or "").strip()
            if not raw:
                return default
            return [part.strip() for part in raw.split(",") if part.strip()]

        def _json_obj(name: str) -> dict[str, str]:
            raw = (env.get(name) or "").strip()
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return {str(k): str(v) for k, v in parsed.items()}
            except json.JSONDecodeError:
                pass
            return {}

        output_mode = (env.get("OPENCLAW_OUTPUT_MODE") or "json").strip().lower()
        if output_mode not in {"json", "jsonl", "text"}:
            output_mode = "json"

        input_mode = (env.get("OPENCLAW_INPUT_MODE") or "arg").strip().lower()
        if input_mode not in {"arg", "stdin"}:
            input_mode = "arg"

        session_mode = (env.get("OPENCLAW_SESSION_MODE") or "always").strip().lower()
        if session_mode not in {"always", "existing", "none"}:
            session_mode = "always"

        max_prompt = 6000
        try:
            max_prompt = int((env.get("OPENCLAW_MAX_PROMPT_ARG_CHARS") or "6000").strip())
        except ValueError:
            max_prompt = 6000

        return cls(
            command=(env.get("OPENCLAW_CLI_COMMAND") or "openclaw").strip(),
            args=_json_list("OPENCLAW_CLI_ARGS_JSON", ["agent", "--json"]),
            resume_args=_json_list("OPENCLAW_CLI_RESUME_ARGS_JSON", []),
            output_mode=output_mode,
            input_mode=input_mode,
            max_prompt_arg_chars=max(100, max_prompt),
            session_mode=session_mode,
            session_arg=(env.get("OPENCLAW_SESSION_ARG") or "--session-id").strip(),
            session_args=_json_list("OPENCLAW_SESSION_ARGS_JSON", []),
            extra_env=_json_obj("OPENCLAW_BACKEND_ENV_JSON"),
            clear_env=_csv("OPENCLAW_BACKEND_CLEAR_ENV", []),
        )


class Openclaw(BaseInstalledAgent):
    """Openclaw Harbor adapter with dual runtime mode support."""

    SUPPORTS_ATIF: bool = True
    _OUTPUT_FILENAME = "openclaw.txt"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
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

    def _runtime_mode(self) -> str:
        mode = (self._extra_env.get("OPENCLAW_BACKEND_MODE") or os.environ.get("OPENCLAW_BACKEND_MODE") or "legacy").strip().lower()
        if mode not in {"legacy", "cli-backend"}:
            return "legacy"
        return mode

    def _runtime_env(self) -> dict[str, str]:
        return {**os.environ, **self._extra_env}

    def _build_openclaw_config(self) -> dict[str, Any]:
        if not self.model_name or "/" not in self.model_name:
            raise ValueError(
                "model_name must be in 'provider/model' format, "
                f"got: {self.model_name!r}"
            )

        provider, model = self.model_name.split("/", 1)
        env = self._runtime_env()
        memory_slot = (env.get("OPENCLAW_MEMORY_PLUGIN_SLOT") or "none").strip() or "none"
        plugins_enabled_raw = (env.get("OPENCLAW_PLUGINS_ENABLED") or "").strip().lower()
        plugins_enabled = plugins_enabled_raw in {"1", "true", "yes", "on"}

        match provider:
            case "anthropic":
                api_type: str | None = "anthropic-messages"
                base_url = env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
                api_key_env = "ANTHROPIC_API_KEY"
            case "openai":
                api_type = "openai-completions"
                base_url = env.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
                api_key_env = "OPENAI_API_KEY"
            case "openrouter":
                api_type = "openai-completions"
                base_url = env.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
                api_key_env = "OPENROUTER_API_KEY"
            case _:
                api_type = "openai-completions"
                base_url = env.get(
                    f"{provider.upper()}_BASE_URL",
                    env.get(
                        "OPENAI_BASE_URL",
                        _OPENAI_COMPAT_BASE_URLS.get(provider.lower(), ""),
                    ),
                )
                if not base_url:
                    raise ValueError(
                        f"Cannot resolve base URL for provider '{provider}'. "
                        f"Set {provider.upper()}_BASE_URL or OPENAI_BASE_URL."
                    )
                api_key_env = f"{provider.upper()}_API_KEY"

        config: dict[str, Any] = {
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
                        **({"api": api_type} if api_type else {}),
                    }
                }
            },
            "agents": {
                "list": [
                    {
                        "id": self._resolve_agent_id(),
                        "default": True,
                        "model": f"{provider}/{model}",
                        "workspace": _WORKSPACE_DIR,
                    }
                ]
            },
        }

        # Do not emit a plugins block unless explicitly requested.
        # In current OpenClaw versions, an explicit plugins section triggers
        # plugin-registry discovery/validation, which can fail in constrained
        # runtime images before `agent` starts.
        explicit_plugins_enabled = "OPENCLAW_PLUGINS_ENABLED" in env
        explicit_memory_slot = "OPENCLAW_MEMORY_PLUGIN_SLOT" in env
        if explicit_plugins_enabled or explicit_memory_slot:
            plugins_config: dict[str, Any] = {
                "enabled": plugins_enabled,
            }
            if memory_slot != "none":
                plugins_config["slots"] = {"memory": memory_slot}
            config["plugins"] = plugins_config

        return config

    def _resolve_agent_id(self) -> str:
        env = self._runtime_env()
        agent_id = (env.get("OPENCLAW_AGENT_ID") or _DEFAULT_AGENT_ID).strip()
        return agent_id or _DEFAULT_AGENT_ID

    def _resolve_api_key_env(self) -> tuple[str, str]:
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

        env = self._runtime_env()
        return key, env.get(key, "")

    def create_run_agent_commands(self, instruction: str) -> list[ExecInput]:
        if not self.model_name or "/" not in self.model_name:
            raise ValueError(
                "model_name must be in 'provider/model' format, "
                f"got: {self.model_name!r}"
            )

        mode = self._runtime_mode()
        env = {"OPENCLAW_STATE_DIR": _STATE_DIR}

        key_name, key_value = self._resolve_api_key_env()
        if key_value:
            env[key_name] = key_value

        commands: list[ExecInput] = []

        if mode == "legacy":
            config = self._build_openclaw_config()
            config_json = json.dumps(config, indent=2, ensure_ascii=False)
            commands.append(
                ExecInput(
                    command=(
                        f"mkdir -p {_STATE_DIR} && "
                        f"cat > {_STATE_DIR}/openclaw.json << 'HARBOR_EOF'\n"
                        f"{config_json}\n"
                        "HARBOR_EOF"
                    ),
                    env=env,
                    timeout_sec=30,
                )
            )

            mcp_cmd = self._build_register_mcp_servers_command(mode=mode)
            if mcp_cmd:
                commands.append(ExecInput(command=mcp_cmd, env=env, timeout_sec=30))

            skills_cmd = self._build_register_skills_command()
            if skills_cmd:
                commands.append(ExecInput(command=skills_cmd, env=env, timeout_sec=30))

            escaped_instruction = shlex.quote(instruction)
            base_command = (
                ". ~/.nvm/nvm.sh 2>/dev/null || true; "
                "openclaw agent --local --json "
                f"--agent {shlex.quote(self._resolve_agent_id())} "
                f"--message {escaped_instruction}"
            )
            commands.append(
                ExecInput(
                    command=self._wrap_agent_exec_command(base_command),
                    env=env,
                )
            )
            return commands

        backend = CliBackendSpec.from_env(self._runtime_env())

        mcp_cmd = self._build_register_mcp_servers_command(mode=mode)
        if mcp_cmd:
            commands.append(ExecInput(command=mcp_cmd, env=env, timeout_sec=30))

        skills_cmd = self._build_register_skills_command()
        if skills_cmd:
            commands.append(ExecInput(command=skills_cmd, env=env, timeout_sec=30))

        cmd, cmd_env = self._build_cli_backend_command(instruction, backend)
        merged_env = {**env, **cmd_env}
        commands.append(
            ExecInput(
                command=self._wrap_agent_exec_command(cmd),
                env=merged_env,
            )
        )
        return commands

    def _wrap_agent_exec_command(self, base_command: str) -> str:
        # Shared wrapper for both legacy and cli-backend execution paths:
        # - preserve agent exit code through pipeline
        # - persist stderr and normalized logs
        # - copy latest session transcript for ATIF parsing
        return (
            "set -o pipefail; "
            f"{base_command} "
            "2>/tmp/openclaw-stderr.raw "
            "| tee /logs/agent/openclaw.txt; "
            "rc=${PIPESTATUS[0]}; "
            "grep -Evi 'plugin id mismatch|Unable to resolve plugin runtime module' "
            "/tmp/openclaw-stderr.raw > /logs/agent/openclaw-stderr.txt || true; "
            "mkdir -p /logs/agent/openclaw-state 2>/dev/null || true; "
            f"cp -a {_STATE_DIR}/agents /logs/agent/openclaw-state/ 2>/dev/null || true; "
            f"latest_session=\"$(ls -1t {_STATE_DIR}/agents/*/sessions/*.jsonl {_STATE_DIR}/agents/*/sessions/*.jsonl.reset.* 2>/dev/null | head -n1 || true)\"; "
            f"[ -n \"$latest_session\" ] && cp \"$latest_session\" /logs/agent/{_COPIED_TRANSCRIPT_FILENAME} || true; "
            "chmod -R a+rX /logs/agent/ 2>/dev/null || true"
            "; exit $rc"
        )

    def _build_cli_backend_command(
        self, instruction: str, backend: CliBackendSpec
    ) -> tuple[str, dict[str, str]]:
        state = self._state_session_file()
        previous_session = ""
        if state.exists():
            try:
                previous_session = state.read_text(encoding="utf-8").strip()
            except OSError:
                previous_session = ""

        session_id = ""
        use_resume = False
        if backend.session_mode == "none":
            session_id = ""
        elif backend.session_mode == "existing":
            session_id = previous_session
        else:
            session_id = previous_session or ""

        if session_id and backend.resume_args:
            use_resume = True

        args = list(backend.resume_args if use_resume else backend.args)
        if session_id:
            if backend.session_args:
                args.extend(part.replace("{sessionId}", session_id) for part in backend.session_args)
            elif backend.session_arg:
                args.extend([backend.session_arg, session_id])

        quoted_command = shlex.quote(backend.command)
        quoted_args = " ".join(shlex.quote(part) for part in args)

        instruction_arg = ""
        stdin_prefix = ""
        if backend.input_mode == "stdin" or len(instruction) > backend.max_prompt_arg_chars:
            stdin_prefix = f"printf %s {shlex.quote(instruction)} | "
        else:
            instruction_arg = f" {shlex.quote(instruction)}"

        clear_env_prefix = ""
        if backend.clear_env:
            clear_env_prefix = " ".join(f"unset {shlex.quote(name)};" for name in backend.clear_env) + " "

        full_command = (
            f"{clear_env_prefix}{stdin_prefix}{quoted_command} {quoted_args}{instruction_arg}"
        ).strip()

        return full_command, backend.extra_env

    def _state_session_file(self) -> Path:
        return self.logs_dir / "openclaw-last-session-id.txt"

    def populate_context_post_run(self, context: AgentContext) -> None:
        output_path = self.logs_dir / self._OUTPUT_FILENAME
        mode = self._runtime_mode()
        raw_mode = (self._runtime_env().get("OPENCLAW_OUTPUT_MODE") or "json").strip().lower()
        output_mode = raw_mode if mode == "cli-backend" else "json"

        session_id: str | None = None
        model_name = self.model_name or "unknown"
        parsed: dict[str, Any] = {}
        trajectory: Trajectory | None = None

        if output_path.exists():
            raw = output_path.read_text(encoding="utf-8").strip()
            parsed = self._parse_backend_output(raw, output_mode)
            usage = parsed.get("usage", {}) if isinstance(parsed.get("usage"), dict) else {}

            context.n_input_tokens = int(usage.get("input") or 0)
            context.n_output_tokens = int(usage.get("output") or 0)
            context.n_cache_tokens = int(usage.get("cacheRead") or 0)

            session_id = parsed.get("sessionId") if isinstance(parsed.get("sessionId"), str) else None
            if session_id:
                try:
                    self._state_session_file().parent.mkdir(parents=True, exist_ok=True)
                    self._state_session_file().write_text(session_id, encoding="utf-8")
                except OSError:
                    pass

            model_candidate = parsed.get("model")
            if isinstance(model_candidate, str) and model_candidate.strip():
                model_name = model_candidate
        else:
            context.n_input_tokens = 0
            context.n_output_tokens = 0
            context.n_cache_tokens = 0

        if self.SUPPORTS_ATIF:
            try:
                trajectory = self._parse_transcript_to_trajectory(
                    session_id=session_id or "",
                    default_model_name=model_name,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"openclaw-v2: ATIF trajectory parsing failed: {exc}")
                trajectory = None

            if trajectory is not None:
                trajectory_path = self.logs_dir / "trajectory.json"
                trajectory_path.write_text(
                    format_trajectory_json(trajectory.to_json_dict()),
                    encoding="utf-8",
                )

        # Best-effort parity artifacts to align with official framework output.
        self._emit_official_like_artifacts(parsed=parsed, trajectory=trajectory)
        self._append_structured_logs(
            parsed=parsed,
            trajectory=trajectory,
            context=context,
            output_mode=output_mode,
        )
        self._cleanup_agent_artifacts()

    def _parse_backend_output(self, raw: str, output_mode: str) -> dict[str, Any]:
        if not raw:
            return {"text": "", "usage": {}, "sessionId": None}

        if output_mode == "jsonl":
            return self._parse_jsonl_output(raw)
        if output_mode == "text":
            return {"text": raw, "usage": {}, "sessionId": None}
        return self._parse_json_output(raw)

    def _parse_json_output(self, raw: str) -> dict[str, Any]:
        trimmed = raw.strip()
        parsed: dict[str, Any] | None = None

        try:
            obj = json.loads(trimmed)
            if isinstance(obj, dict):
                parsed = obj
        except json.JSONDecodeError:
            json_start = trimmed.find("{")
            json_end = trimmed.rfind("}")
            if json_start != -1 and json_end > json_start:
                try:
                    obj = json.loads(trimmed[json_start : json_end + 1])
                    if isinstance(obj, dict):
                        parsed = obj
                except json.JSONDecodeError:
                    parsed = None

        if parsed is None:
            return {"text": trimmed, "usage": {}, "sessionId": None}

        usage_raw = self._extract_usage_candidate(parsed)
        usage = self._extract_usage_map(usage_raw)
        session_id = self._extract_session_id(parsed)
        model = self._extract_model_name(parsed)
        text = self._extract_text(parsed)
        payload_texts = self._extract_payload_texts(parsed)
        system_prompt = self._extract_system_prompt_text(parsed)
        return {
            "text": text,
            "usage": usage,
            "sessionId": session_id,
            "model": model,
            "payloads": payload_texts,
            "systemPrompt": system_prompt,
        }

    def _extract_system_prompt_text(self, parsed: dict[str, Any]) -> str:
        meta = parsed.get("meta") if isinstance(parsed.get("meta"), dict) else {}
        report = (
            meta.get("systemPromptReport")
            if isinstance(meta.get("systemPromptReport"), dict)
            else None
        )
        if report is None:
            return ""
        text = report.get("systemPrompt")
        if isinstance(text, str) and text.strip():
            return text.strip()
        # Keep a compact report string when the full prompt text is not emitted.
        return json.dumps(report, ensure_ascii=False)

    def _parse_jsonl_output(self, raw: str) -> dict[str, Any]:
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        text_parts: list[str] = []
        usage: dict[str, int] = {}
        session_id: str | None = None
        model: str | None = None

        for line in lines:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue

            if not session_id:
                session_id = self._extract_session_id(obj)
            if not model:
                model = self._extract_model_name(obj)

            candidate_usage = self._extract_usage_map(self._extract_usage_candidate(obj))
            usage = self._merge_usage(usage, candidate_usage)

            text = self._extract_text(obj)
            if text:
                text_parts.append(text)

        return {
            "text": "\n".join(part for part in text_parts if part).strip(),
            "usage": usage,
            "sessionId": session_id,
            "model": model,
        }

    def _extract_usage_candidate(self, parsed: dict[str, Any]) -> dict[str, Any]:
        meta = parsed.get("meta") if isinstance(parsed.get("meta"), dict) else {}
        agent_meta = meta.get("agentMeta") if isinstance(meta.get("agentMeta"), dict) else {}
        usage = agent_meta.get("usage") if isinstance(agent_meta.get("usage"), dict) else None
        if usage is None and isinstance(parsed.get("usage"), dict):
            usage = parsed.get("usage")
        return usage if isinstance(usage, dict) else {}

    def _extract_usage_map(self, usage: dict[str, Any]) -> dict[str, int]:
        def pick(keys: list[str]) -> int:
            for key in keys:
                value = usage.get(key)
                if isinstance(value, (int, float)):
                    return int(value)
            return 0

        return {
            "input": pick(["input", "input_tokens", "inputTokens"]),
            "output": pick(["output", "output_tokens", "outputTokens"]),
            "cacheRead": pick(["cacheRead", "cache_read_input_tokens", "cached_input_tokens"]),
            "cacheWrite": pick(["cacheWrite", "cache_write_input_tokens"]),
            "total": pick(["total", "total_tokens", "totalTokens"]),
        }

    def _merge_usage(self, base: dict[str, int], add: dict[str, int]) -> dict[str, int]:
        merged = dict(base)
        for key, value in add.items():
            merged[key] = merged.get(key, 0) + int(value)
        return merged

    def _extract_session_id(self, parsed: dict[str, Any]) -> str | None:
        fields_raw = (
            self._runtime_env().get("OPENCLAW_SESSION_ID_FIELDS")
            or "session_id,sessionId,conversation_id,conversationId,thread_id"
        )
        fields = [part.strip() for part in fields_raw.split(",") if part.strip()]

        for field in fields:
            value = parsed.get(field)
            if isinstance(value, str) and value.strip():
                return value.strip()

        session = parsed.get("session")
        if isinstance(session, dict):
            sid = session.get("id")
            if isinstance(sid, str) and sid.strip():
                return sid.strip()

        meta = parsed.get("meta")
        if isinstance(meta, dict):
            agent_meta = meta.get("agentMeta")
            if isinstance(agent_meta, dict):
                sid = agent_meta.get("sessionId")
                if isinstance(sid, str) and sid.strip():
                    return sid.strip()

        return None

    def _extract_model_name(self, parsed: dict[str, Any]) -> str | None:
        for key in ("model",):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        session = parsed.get("session")
        if isinstance(session, dict):
            value = session.get("model")
            if isinstance(value, str) and value.strip():
                return value.strip()

        meta = parsed.get("meta")
        if isinstance(meta, dict):
            agent_meta = meta.get("agentMeta")
            if isinstance(agent_meta, dict):
                value = agent_meta.get("model")
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return None

    def _extract_text(self, parsed: dict[str, Any]) -> str:
        def collect(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return "".join(collect(item) for item in value)
            if isinstance(value, dict):
                if isinstance(value.get("text"), str):
                    return value["text"]
                if isinstance(value.get("content"), str):
                    return value["content"]
                if isinstance(value.get("content"), list):
                    return "".join(collect(item) for item in value["content"])
                if isinstance(value.get("message"), dict):
                    return collect(value["message"])
            return ""

        return (
            collect(parsed.get("message"))
            or collect(parsed.get("content"))
            or collect(parsed.get("result"))
            or ""
        ).strip()

    def _extract_payload_texts(self, parsed: dict[str, Any]) -> list[str]:
        payloads = parsed.get("payloads")
        if not isinstance(payloads, list):
            return []
        out: list[str] = []
        for item in payloads:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                out.append(text.strip())
        return out

    def _emit_official_like_artifacts(
        self,
        parsed: dict[str, Any],
        trajectory: Trajectory | None,
    ) -> None:
        try:
            episodes = self._build_episode_pairs(parsed=parsed, trajectory=trajectory)
            for idx, episode in enumerate(episodes):
                ep_dir = self.logs_dir / f"episode-{idx}"
                ep_dir.mkdir(parents=True, exist_ok=True)
                (ep_dir / "prompt.txt").write_text(episode.get("prompt", ""), encoding="utf-8")
                (ep_dir / "response.txt").write_text(episode.get("response", ""), encoding="utf-8")
                (ep_dir / "debug.json").write_text(
                    json.dumps(episode.get("debug", {}), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
        except Exception as exc:  # noqa: BLE001
            self._append_job_log(f"openclaw: emit_official_like_artifacts failed: {exc}")

    def _build_episode_pairs(
        self,
        parsed: dict[str, Any],
        trajectory: Trajectory | None,
    ) -> list[dict[str, Any]]:
        episodes: list[dict[str, Any]] = []

        if trajectory is not None:
            # Keep episode count aligned with trajectory step count.
            last_prompt = ""
            system_prompt = (
                parsed.get("systemPrompt") if isinstance(parsed.get("systemPrompt"), str) else ""
            )
            episode_index = 0
            for step in trajectory.steps:
                if step.source in ("user", "system"):
                    prompt = step.message or system_prompt or ""
                    if prompt:
                        last_prompt = prompt
                    episodes.append(
                        {
                            "prompt": prompt,
                            "response": "",
                            "debug": {
                                "episode": episode_index,
                                "source": f"trajectory-{step.source}-step",
                                "step_id": step.step_id,
                                "timestamp": step.timestamp,
                                "message_chars": len(step.message or ""),
                            },
                        }
                    )
                    episode_index += 1
                    continue

                if step.source == "agent":
                    prompt = last_prompt or system_prompt or ""
                    debug_obj = {
                        "episode": episode_index,
                        "source": "trajectory-agent-step",
                        "step_id": step.step_id,
                        "model": step.model_name,
                        "timestamp": step.timestamp,
                        "message_chars": len(step.message or ""),
                        "tool_call_count": len(step.tool_calls or []),
                    }
                    if step.metrics is not None:
                        debug_obj["metrics"] = {
                            "prompt_tokens": step.metrics.prompt_tokens,
                            "completion_tokens": step.metrics.completion_tokens,
                            "cached_tokens": step.metrics.cached_tokens,
                            "cost_usd": step.metrics.cost_usd,
                        }
                    if step.tool_calls:
                        debug_obj["tool_calls"] = [
                            {
                                "id": tc.tool_call_id,
                                "name": tc.function_name,
                                "arguments": tc.arguments,
                            }
                            for tc in step.tool_calls
                        ]
                    if step.observation and step.observation.results:
                        debug_obj["tool_results"] = [
                            {
                                "source_call_id": result.source_call_id,
                                "content": result.content,
                            }
                            for result in step.observation.results
                        ]

                    episodes.append(
                        {
                            "prompt": prompt,
                            "response": step.message or "",
                            "debug": debug_obj,
                        }
                    )
                    episode_index += 1
                    continue

                episodes.append(
                    {
                        "prompt": last_prompt or system_prompt or "",
                        "response": step.message or "",
                        "debug": {
                            "episode": episode_index,
                            "source": f"trajectory-{step.source}-step",
                            "step_id": step.step_id,
                            "timestamp": step.timestamp,
                            "message_chars": len(step.message or ""),
                        },
                    }
                )
                episode_index += 1

        if not episodes:
            payloads = parsed.get("payloads")
            if isinstance(payloads, list) and payloads:
                for idx, text in enumerate(payloads):
                    if not isinstance(text, str):
                        continue
                    episodes.append(
                        {
                            "prompt": "",
                            "response": text,
                            "debug": {
                                "source": "payloads",
                                "index": idx,
                            },
                        }
                    )

        if not episodes:
            episodes.append(
                {
                    "prompt": "",
                    "response": parsed.get("text", "") if isinstance(parsed.get("text"), str) else "",
                    "debug": {"source": "fallback"},
                }
            )

        return episodes

    def _append_job_log(self, message: str) -> None:
        try:
            trial_dir = self.logs_dir.parent
            trial_log = trial_dir / "trial.log"
            job_log = trial_dir.parent / "job.log"
            line = f"{datetime.now(timezone.utc).isoformat()} {message}\n"
            trial_log.parent.mkdir(parents=True, exist_ok=True)
            with trial_log.open("a", encoding="utf-8") as f:
                f.write(line)
            with job_log.open("a", encoding="utf-8") as f:
                f.write(line)
        except OSError:
            pass

    def _append_structured_logs(
        self,
        parsed: dict[str, Any],
        trajectory: Trajectory | None,
        context: AgentContext,
        output_mode: str,
    ) -> None:
        usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
        payloads = parsed.get("payloads") if isinstance(parsed.get("payloads"), list) else []
        text = parsed.get("text") if isinstance(parsed.get("text"), str) else ""
        session_id = parsed.get("sessionId") if isinstance(parsed.get("sessionId"), str) else ""
        model = parsed.get("model") if isinstance(parsed.get("model"), str) else (self.model_name or "")
        step_count = len(trajectory.steps) if trajectory is not None else 0

        stderr_path = self.logs_dir / "openclaw-stderr.txt"
        stderr_lines: list[str] = []
        if stderr_path.exists():
            try:
                stderr_lines = [ln.strip() for ln in stderr_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            except OSError:
                stderr_lines = []

        self._append_job_log("openclaw: run summary begin")
        self._append_job_log(f"openclaw: output_mode={output_mode} session_id={session_id or '-'} model={model or '-'}")
        self._append_job_log(
            "openclaw: tokens "
            f"input={context.n_input_tokens} output={context.n_output_tokens} cache={context.n_cache_tokens} "
            f"usage_total={usage.get('total', 0) if isinstance(usage, dict) else 0}"
        )
        self._append_job_log(
            f"openclaw: payloads={len(payloads)} text_chars={len(text)} trajectory_steps={step_count}"
        )
        system_prompt = parsed.get("systemPrompt") if isinstance(parsed.get("systemPrompt"), str) else ""
        if system_prompt:
            self._append_job_log(f"openclaw: system_prompt={json.dumps(system_prompt, ensure_ascii=False)}")

        if trajectory is not None:
            last_prompt = system_prompt
            turn = 0
            for step in trajectory.steps:
                if step.source in ("user", "system"):
                    if step.message:
                        last_prompt = step.message
                    if step.source == "system" and step.message:
                        self._append_job_log(
                            f"openclaw: system_step[{step.step_id}]={json.dumps(step.message, ensure_ascii=False)}"
                        )
                    continue

                if step.source != "agent":
                    continue

                turn += 1
                self._append_job_log(
                    f"openclaw: turn[{turn}] prompt={json.dumps(last_prompt or '', ensure_ascii=False)}"
                )
                self._append_job_log(
                    f"openclaw: turn[{turn}] response={json.dumps(step.message or '', ensure_ascii=False)}"
                )
                if step.tool_calls:
                    self._append_job_log(
                        "openclaw: turn[{}] tool_calls={}".format(
                            turn,
                            json.dumps(
                                [
                                    {
                                        "id": call.tool_call_id,
                                        "name": call.function_name,
                                        "arguments": call.arguments,
                                    }
                                    for call in step.tool_calls
                                ],
                                ensure_ascii=False,
                            ),
                        )
                    )
                if step.observation and step.observation.results:
                    self._append_job_log(
                        "openclaw: turn[{}] tool_results={}".format(
                            turn,
                            json.dumps(
                                [
                                    {
                                        "source_call_id": result.source_call_id,
                                        "content": result.content,
                                    }
                                    for result in step.observation.results
                                ],
                                ensure_ascii=False,
                            ),
                        )
                    )

        if stderr_lines:
            self._append_job_log(f"openclaw: stderr_lines={len(stderr_lines)}")
            for idx, line in enumerate(stderr_lines[:10], start=1):
                self._append_job_log(f"openclaw: stderr[{idx}] {line}")
        self._append_job_log("openclaw: run summary end")

    def _cleanup_agent_artifacts(self) -> None:
        # Keep parity with official layout by removing low-level execution
        # artifacts that are not present in terminus-style outputs.
        for path in sorted(self.logs_dir.glob("command-*")):
            try:
                if path.is_dir():
                    for child in sorted(path.rglob("*"), reverse=True):
                        if child.is_file() or child.is_symlink():
                            child.unlink(missing_ok=True)
                        elif child.is_dir():
                            child.rmdir()
                    path.rmdir()
            except OSError:
                pass

        # Do not keep terminus-only artifacts in openclaw adapter output.
        for name in ("recording.cast", "terminus_2.pane"):
            artifact = self.logs_dir / name
            if artifact.exists() and artifact.is_file():
                try:
                    artifact.unlink()
                except OSError:
                    pass

        state_dir = self.logs_dir / "openclaw-state"
        if state_dir.exists() and state_dir.is_dir():
            try:
                for child in sorted(state_dir.rglob("*"), reverse=True):
                    if child.is_file() or child.is_symlink():
                        child.unlink(missing_ok=True)
                    elif child.is_dir():
                        child.rmdir()
                state_dir.rmdir()
            except OSError:
                pass

    def _build_register_mcp_servers_command(self, mode: str) -> str | None:
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
            else:
                entry = {"url": server.url}
            servers[server.name] = entry

        mcporter = json.dumps({"mcpServers": servers}, indent=2)
        escaped_mcporter = shlex.quote(mcporter)

        if mode == "legacy":
            return (
                f"mkdir -p /root/.mcporter && "
                f"echo {escaped_mcporter} > {_MCPORTER_CONFIG}"
            )

        # In cli-backend mode we still write mcporter for backward compatibility,
        # and also emit a backend-readable MCP config file.
        backend_mcp_config = shlex.quote(json.dumps({"mcpServers": servers}, indent=2))
        return (
            f"mkdir -p /root/.mcporter {_STATE_DIR} && "
            f"echo {escaped_mcporter} > {_MCPORTER_CONFIG} && "
            f"echo {backend_mcp_config} > {_STATE_DIR}/backend-mcp.json"
        )

    def _build_register_skills_command(self) -> str | None:
        if not self.skills_dir:
            return None
        return (
            f"mkdir -p {_SKILLS_DIR} && "
            f"cp -r {shlex.quote(self.skills_dir)}/* "
            f"{_SKILLS_DIR}/ 2>/dev/null || true"
        )

    def _resolve_session_dirs(self) -> list[Path]:
        agents_dir = self.logs_dir / "openclaw-state" / "agents"
        if not agents_dir.exists() or not agents_dir.is_dir():
            return []

        dirs: list[Path] = []
        for entry in agents_dir.iterdir():
            if entry.is_dir():
                sessions = entry / "sessions"
                if sessions.exists() and sessions.is_dir():
                    dirs.append(sessions)
        return sorted(dirs)

    def _find_transcript_path(self, session_id: str) -> Path | None:
        copied = self.logs_dir / _COPIED_TRANSCRIPT_FILENAME
        if copied.exists() and copied.is_file():
            try:
                if copied.stat().st_size > 0:
                    return copied
            except OSError:
                pass

        session_dirs = self._resolve_session_dirs()
        if not session_dirs:
            return None

        def newest_matching(patterns: tuple[str, ...]) -> Path | None:
            # Prefer the freshest file because OpenClaw may keep reset/topic
            # variants side-by-side in the same session directory.
            latest_path: Path | None = None
            latest_mtime = -1.0
            for sessions in session_dirs:
                for pattern in patterns:
                    for candidate in sessions.glob(pattern):
                        if not candidate.is_file():
                            continue
                        try:
                            stat = candidate.stat()
                        except OSError:
                            continue
                        if stat.st_mtime > latest_mtime:
                            latest_mtime = stat.st_mtime
                            latest_path = candidate
            return latest_path

        if session_id:
            # OpenClaw may persist topic-scoped transcripts as
            # <sessionId>-topic-<encodedTopic>.jsonl, and reset archives as
            # *.jsonl.reset.*. Support both naming styles.
            matched = newest_matching(
                (
                    f"{session_id}.jsonl",
                    f"{session_id}-topic-*.jsonl",
                    f"{session_id}.jsonl.reset.*",
                    f"{session_id}-topic-*.jsonl.reset.*",
                )
            )
            if matched is not None:
                return matched

        return newest_matching(("*.jsonl", "*.jsonl.reset.*"))

    def _parse_transcript_to_trajectory(
        self, session_id: str, default_model_name: str
    ) -> Trajectory | None:
        transcript_path = self._find_transcript_path(session_id)
        if transcript_path is None:
            self._append_job_log("openclaw: transcript not found; skip ATIF trajectory parse")
            return None

        raw_lines: list[dict[str, Any]] = []
        try:
            transcript_lines = transcript_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            self._append_job_log(f"openclaw: failed to read transcript: {exc}")
            return None

        for line in transcript_lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
                if isinstance(obj, dict):
                    raw_lines.append(obj)
            except json.JSONDecodeError:
                continue

        if not raw_lines:
            return None

        proto_turns: list[dict[str, Any]] = []
        total_input = total_output = total_cache_read = 0

        for event in raw_lines:
            message = event.get("message")
            if not isinstance(message, dict):
                continue

            role = message.get("role")
            if role not in ("user", "assistant", "system"):
                continue

            timestamp = event.get("timestamp")
            model_from_event = event.get("model") or message.get("model") or default_model_name
            content = message.get("content", "")

            if isinstance(content, str):
                blocks: list[dict[str, Any]] = [{"type": "text", "text": content}]
            elif isinstance(content, list):
                blocks = [b for b in content if isinstance(b, dict)]
            else:
                blocks = []

            metrics: Metrics | None = None
            if role == "assistant":
                usage = message.get("usage") or event.get("usage") or {}
                usage_map = self._extract_usage_map(usage if isinstance(usage, dict) else {})
                inp = usage_map.get("input", 0)
                out = usage_map.get("output", 0)
                cache_read = usage_map.get("cacheRead", 0)
                total_input += inp
                total_output += out
                total_cache_read += cache_read
                if inp or out or cache_read:
                    metrics = Metrics(
                        prompt_tokens=inp,
                        completion_tokens=out,
                        cached_tokens=cache_read,
                    )

            text_parts: list[str] = []
            turn_tool_calls: list[ToolCall] = []
            turn_tool_results: list[ObservationResult] = []

            for block in blocks:
                btype = str(block.get("type") or "").lower()

                if btype == "text":
                    text = str(block.get("text") or "").strip()
                    if text:
                        text_parts.append(text)
                elif btype in ("tool_use", "toolcall", "tool_call"):
                    call_id = str(block.get("id") or "")
                    tool_name = str(block.get("name") or "")
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
                    call_id = str(block.get("tool_use_id") or "")
                    result_content = block.get("content") or ""
                    if isinstance(result_content, list):
                        parts = [
                            (str(p.get("text") or "") if isinstance(p, dict) else str(p))
                            for p in result_content
                        ]
                        result_text = "\n".join(part for part in parts if part).strip() or None
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

        for i, turn in enumerate(proto_turns):
            if not turn["tool_results"]:
                continue
            for j in range(i - 1, -1, -1):
                prev = proto_turns[j]
                if prev["role"] == "assistant" and prev["tool_calls"]:
                    prev["merged_results"].extend(turn["tool_results"])
                    turn["tool_results"] = []
                    break

        steps: list[Step] = []
        step_id = 1

        for turn in proto_turns:
            text = "\n\n".join(turn["text_parts"])
            tool_calls = turn["tool_calls"] or None
            all_results = turn["merged_results"] + turn["tool_results"]
            observation = Observation(results=all_results) if all_results else None

            if not text and tool_calls is None and observation is None and turn["metrics"] is None:
                continue

            source = "agent" if turn["role"] == "assistant" else turn["role"]
            steps.append(
                Step(
                    step_id=step_id,
                    timestamp=turn["timestamp"],
                    source=source,  # type: ignore[arg-type]
                    model_name=turn["model"] if source == "agent" else None,
                    message=text or "",
                    tool_calls=tool_calls,
                    observation=observation,
                    metrics=turn["metrics"],
                )
            )
            step_id += 1

        if not steps:
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
