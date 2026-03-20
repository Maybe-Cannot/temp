"""OpenClaw 适配器（Harbor 集成版）。

整体作用
--------
将 Harbor 的 Agent 执行接口转换为 OpenClaw CLI 的调用流程，并在运行后把
OpenClaw 输出还原为 Harbor 可消费的上下文统计与 ATIF 轨迹文件。

代码结构（按功能模块划分）
------------------------
1) 常量与后端规格定义
    - 输入：环境变量、固定路径常量
    - 输出：运行时参数对象 `CliBackendSpec`
    - 作用：约束 CLI 参数、输出模式、会话参数与额外环境变量。

2) 运行时配置生成模块
    - 输入：`model_name`、环境变量、Agent 基础属性
    - 输出：OpenClaw 配置字典（写入 `openclaw.json`）
    - 作用：生成 provider/model 配置、agent 配置、可选插件配置。

3) 执行命令构建模块
    - 输入：任务指令文本、运行模式（legacy/cli-backend）、后端规格
    - 输出：`list[ExecInput]` 命令序列
    - 作用：构建安装前置命令、主执行命令、统一日志和 transcript 拷贝后处理。

4) 结果解析与上下文回填模块
    - 输入：`openclaw.txt`、stderr、session 轨迹文件
    - 输出：`AgentContext` 令牌统计、`trajectory.json`、兼容产物目录
    - 作用：解析 json/jsonl/text 输出，提取 usage/session/model，并回填 Harbor 上下文。

5) transcript 发现与 ATIF 转换模块
    - 输入：session id、session 目录下 jsonl 事件流
    - 输出：`Trajectory | None`
    - 作用：定位最新 transcript，解析 tool_use/tool_result，生成结构化 ATIF 步骤。

6) 兼容产物与日志模块
    - 输入：解析后的结果与轨迹
    - 输出：episode 目录、结构化 job/trial 日志、清理后的输出目录
    - 作用：提供与 Harbor 现有观测链路兼容的调试与结果文件。
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
_PLUGIN_INSPECT_FILENAME = "openclaw-plugins.json"

_OPENAI_COMPAT_BASE_URLS: dict[str, str] = {
    "deepseek": "https://api.deepseek.com/v1",
    "together": "https://api.together.xyz/v1",
    "groq": "https://api.groq.com/openai/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "perplexity": "https://api.perplexity.ai",
}


@dataclass
class CliBackendSpec:
    """CLI 后端规格。

    输入：环境变量解析结果。
    输出：规范化后的命令参数/模式/环境配置。
    作用：避免在命令拼接阶段直接散落读取环境变量，集中约束默认值与容错行为。
    """

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
        """从环境变量构建 CLI 后端规格。

        输入：`env`（通常为 `os.environ` 与外部注入变量的合并结果）。
        输出：`CliBackendSpec` 实例。
        作用：完成字符串/JSON/CSV 类型参数归一化，并提供合法值兜底。
        """

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
    """OpenClaw 适配器实现（同时支持 legacy 与 cli-backend 两种运行模式）。"""

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
        # 模块：运行模式解析
        # 输入：OPENCLAW_BACKEND_MODE（来自运行时环境）
        # 输出：legacy / cli-backend
        # 作用：在未识别值时回退 legacy，保证兼容默认链路。
        mode = (self._extra_env.get("OPENCLAW_BACKEND_MODE") or os.environ.get("OPENCLAW_BACKEND_MODE") or "legacy").strip().lower()
        if mode not in {"legacy", "cli-backend"}:
            return "legacy"
        return mode

    def _runtime_env(self) -> dict[str, str]:
        return {**os.environ, **self._extra_env}

    def _build_openclaw_config(self) -> dict[str, Any]:
        """构建 OpenClaw 配置对象。

        输入：`self.model_name` 与运行时环境变量。
        输出：可序列化的 OpenClaw 配置字典。
        作用：统一 provider/model 解析、API 鉴权来源、agent 默认配置及插件开关。
        """

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

        # 仅在显式要求时才输出 plugins 配置。
        # 某些 OpenClaw 版本会在检测到 plugins 配置后主动触发插件发现/校验，
        # 在受限运行镜像中可能在 agent 启动前失败，因此默认不写入该段。
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
        """构建 Harbor 执行阶段所需命令序列。

        输入：`instruction`（用户任务指令）。
        输出：按顺序执行的 `ExecInput` 列表。
        作用：根据运行模式拼装主命令，并注入统一的日志采集和 transcript 拷贝后处理。
        """

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

            plugin_inspect_cmd = self._build_capture_plugin_inventory_command()
            if plugin_inspect_cmd:
                commands.append(ExecInput(command=plugin_inspect_cmd, env=env, timeout_sec=30))

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

        plugin_inspect_cmd = self._build_capture_plugin_inventory_command()
        if plugin_inspect_cmd:
            commands.append(ExecInput(command=plugin_inspect_cmd, env=env, timeout_sec=30))

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
        """统一包装执行命令。

        输入：`base_command`（不带日志重定向与收尾处理的 OpenClaw 主命令）。
        输出：可直接交给 shell 执行的完整命令字符串。
        作用：
        1) 保留管道前主进程退出码；
        2) 统一落盘 stdout/stderr；
        3) 复制最新 transcript，供后续 ATIF 转换使用。
        """

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
        """构建 cli-backend 模式下的基础命令。

        输入：`instruction` 与 `backend` 规格。
        输出：`(command, extra_env)`。
        作用：处理会话恢复参数、stdin/argv 输入模式，以及环境变量清理前缀。
        """

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

    def _build_capture_plugin_inventory_command(self) -> str | None:
        """构建插件清单采集命令。

        输入：运行时环境变量（可通过 OPENCLAW_CAPTURE_PLUGIN_INSPECT 控制开关）。
        输出：shell 命令字符串（关闭时返回 None）。
        作用：将插件 inspect 结果写入日志目录，供后处理阶段做“工具名→插件”映射。
        """

        enabled_raw = (self._runtime_env().get("OPENCLAW_CAPTURE_PLUGIN_INSPECT") or "1").strip().lower()
        if enabled_raw in {"0", "false", "no", "off"}:
            return None

        return (
            ". ~/.nvm/nvm.sh 2>/dev/null || true; "
            "openclaw plugins inspect --all --json "
            f"> /logs/agent/{_PLUGIN_INSPECT_FILENAME} "
            "2>/logs/agent/openclaw-plugins-stderr.txt || true"
        )

    def _state_session_file(self) -> Path:
        return self.logs_dir / "openclaw-last-session-id.txt"

    def populate_context_post_run(self, context: AgentContext) -> None:
        """运行后回填 Harbor 上下文并生成兼容产物。

        输入：`AgentContext`（待填充对象）与运行日志目录中的输出文件。
        输出：更新后的 `context`、可选 `trajectory.json`、episode/debug 产物与结构化日志。
        作用：聚合输出解析、令牌统计、轨迹转换、日志写入与临时产物清理。
        """

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

        # 尽力输出与官方框架形态对齐的兼容产物。
        self._emit_official_like_artifacts(parsed=parsed, trajectory=trajectory)
        self._append_structured_logs(
            parsed=parsed,
            trajectory=trajectory,
            context=context,
            output_mode=output_mode,
        )
        self._cleanup_agent_artifacts()

    def _parse_backend_output(self, raw: str, output_mode: str) -> dict[str, Any]:
        # 模块：后端输出分发解析
        # 输入：原始输出文本 + 输出模式
        # 输出：统一结构字典（text/usage/sessionId/model 等）
        # 作用：屏蔽 json/jsonl/text 差异，保证后续处理分支稳定。
        if not raw:
            return {"text": "", "usage": {}, "sessionId": None}

        if output_mode == "jsonl":
            return self._parse_jsonl_output(raw)
        if output_mode == "text":
            return {"text": raw, "usage": {}, "sessionId": None}
        return self._parse_json_output(raw)

    def _parse_json_output(self, raw: str) -> dict[str, Any]:
        # 模块：JSON 输出解析
        # 输入：可能掺杂日志前后缀的原始文本
        # 输出：统一字段字典；解析失败时退化为纯文本结果
        # 作用：尽量从非严格输出中恢复有效 JSON，减少运行波动对主流程影响。
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
        # 当未返回完整 system prompt 文本时，保留紧凑 report 便于排查。
        return json.dumps(report, ensure_ascii=False)

    def _parse_jsonl_output(self, raw: str) -> dict[str, Any]:
        # 模块：JSONL 输出解析
        # 输入：逐行 JSON 事件文本
        # 输出：聚合后的 text/usage/sessionId/model
        # 作用：面向流式输出场景，逐行容错并累加 usage。
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
        # 模块：会话 ID 提取
        # 输入：单条解析后的响应对象
        # 输出：session id（若不存在则返回 None）
        # 作用：兼容多种字段命名与嵌套结构，降低后端协议差异影响。
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
        # 模块：模型名提取
        # 输入：单条解析后的响应对象
        # 输出：模型名字符串或 None
        # 作用：按优先级在顶层/session/meta 中提取模型名。
        value = parsed.get("model")
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

    def _load_plugin_tool_index(self) -> dict[str, list[dict[str, str]]]:
        """加载工具名到插件信息的映射索引。

        输入：`openclaw-plugins.json`（由 `openclaw plugins inspect --all --json` 生成）。
        输出：`{tool_name_lower: [plugin_info, ...]}`。
        作用：将插件加载/注册信息并入工具调用记录，提升实验可解释性。
        """

        plugin_path = self.logs_dir / _PLUGIN_INSPECT_FILENAME
        if not plugin_path.exists() or not plugin_path.is_file():
            return {}

        try:
            raw = plugin_path.read_text(encoding="utf-8")
        except OSError:
            return {}

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}

        entries: list[dict[str, Any]] = []
        if isinstance(parsed, list):
            entries = [entry for entry in parsed if isinstance(entry, dict)]
        elif isinstance(parsed, dict):
            plugins = parsed.get("plugins")
            if isinstance(plugins, list):
                entries = [entry for entry in plugins if isinstance(entry, dict)]

        index: dict[str, list[dict[str, str]]] = {}

        def register_tool(tool_name: str, plugin_info: dict[str, str]) -> None:
            normalized = tool_name.strip().lower()
            if not normalized:
                return
            bucket = index.setdefault(normalized, [])
            plugin_id = plugin_info.get("plugin_id", "")
            if plugin_id and any(existing.get("plugin_id") == plugin_id for existing in bucket):
                return
            bucket.append(plugin_info)

        for entry in entries:
            plugin = entry.get("plugin") if isinstance(entry.get("plugin"), dict) else entry
            plugin_id = str(plugin.get("id") or "").strip() if isinstance(plugin, dict) else ""
            if not plugin_id:
                continue

            plugin_info = {
                "plugin_id": plugin_id,
                "plugin_name": str(plugin.get("name") or plugin_id).strip(),
                "origin": str(plugin.get("origin") or "").strip(),
                "source": str(plugin.get("source") or "").strip(),
            }

            inspect_tools = entry.get("tools")
            if isinstance(inspect_tools, list):
                for tool in inspect_tools:
                    if not isinstance(tool, dict):
                        continue
                    names = tool.get("names")
                    if not isinstance(names, list):
                        continue
                    for name in names:
                        if isinstance(name, str):
                            register_tool(name, plugin_info)

            tool_names = entry.get("toolNames")
            if isinstance(tool_names, list):
                for name in tool_names:
                    if isinstance(name, str):
                        register_tool(name, plugin_info)

        return index

    def _lookup_plugin_candidates(
        self,
        tool_name: str,
        plugin_tool_index: dict[str, list[dict[str, str]]],
    ) -> list[dict[str, str]]:
        normalized = (tool_name or "").strip().lower()
        if not normalized:
            return []

        direct = plugin_tool_index.get(normalized)
        if direct:
            return [dict(item) for item in direct]

        # 兼容带命名空间的工具名（如 plugin/tool）。
        suffix = normalized.split("/", 1)[-1]
        if suffix and suffix != normalized:
            matched = plugin_tool_index.get(suffix)
            if matched:
                return [dict(item) for item in matched]

        namespace_matches: list[dict[str, str]] = []
        for candidate_name, items in plugin_tool_index.items():
            if candidate_name.endswith(f"/{normalized}"):
                namespace_matches.extend(dict(item) for item in items)

        dedup: dict[str, dict[str, str]] = {}
        for item in namespace_matches:
            key = item.get("plugin_id") or json.dumps(item, ensure_ascii=False)
            dedup[key] = item
        return list(dedup.values())

    def _build_tool_call_records(
        self,
        tool_calls: list[ToolCall] | None,
        plugin_tool_index: dict[str, list[dict[str, str]]],
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for call in tool_calls or []:
            name = call.function_name or ""
            records.append(
                {
                    "id": call.tool_call_id,
                    "name": name,
                    "arguments": call.arguments,
                    "plugin_candidates": self._lookup_plugin_candidates(name, plugin_tool_index),
                }
            )
        return records

    def _build_tool_result_records(
        self,
        observation: Observation | None,
        tool_call_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        call_name_by_id: dict[str, str] = {}
        for record in tool_call_records:
            call_id = record.get("id")
            call_name = record.get("name")
            if isinstance(call_id, str) and call_id and isinstance(call_name, str):
                call_name_by_id[call_id] = call_name

        out: list[dict[str, Any]] = []
        for result in (observation.results if observation and observation.results else []):
            source_call_id = result.source_call_id if isinstance(result.source_call_id, str) else None
            out.append(
                {
                    "source_call_id": source_call_id,
                    "tool_name": call_name_by_id.get(source_call_id or "") if source_call_id else None,
                    "content": result.content,
                }
            )
        return out

    def _render_tool_details_text(
        self,
        tool_call_records: list[dict[str, Any]],
        tool_result_records: list[dict[str, Any]],
    ) -> str:
        lines: list[str] = []

        if tool_call_records:
            lines.append("【工具调用详情】")
            for idx, call in enumerate(tool_call_records, start=1):
                name = str(call.get("name") or "") or "(unknown)"
                call_id = str(call.get("id") or "") or "-"
                lines.append(f"{idx}. name={name} call_id={call_id}")
                lines.append(
                    f"   arguments={json.dumps(call.get('arguments', {}), ensure_ascii=False)}"
                )

                candidates = call.get("plugin_candidates")
                if isinstance(candidates, list) and candidates:
                    rendered = []
                    for item in candidates:
                        if not isinstance(item, dict):
                            continue
                        plugin_id = str(item.get("plugin_id") or "").strip()
                        plugin_name = str(item.get("plugin_name") or plugin_id).strip()
                        origin = str(item.get("origin") or "").strip()
                        source = str(item.get("source") or "").strip()
                        base = plugin_name if plugin_name else plugin_id
                        extras = [part for part in [plugin_id, origin, source] if part]
                        rendered.append(f"{base} ({', '.join(extras)})" if extras else base)
                    if rendered:
                        lines.append(f"   plugin_candidates={'; '.join(rendered)}")

        if tool_result_records:
            if lines:
                lines.append("")
            lines.append("【工具调用结果】")
            for idx, result in enumerate(tool_result_records, start=1):
                call_id = str(result.get("source_call_id") or "") or "-"
                tool_name = str(result.get("tool_name") or "") or "(unknown)"
                content = result.get("content")
                content_text = "" if content is None else str(content)
                lines.append(f"{idx}. tool={tool_name} source_call_id={call_id}")
                lines.append(f"   content={content_text}")

        return "\n".join(lines).strip()

    def _emit_official_like_artifacts(
        self,
        parsed: dict[str, Any],
        trajectory: Trajectory | None,
    ) -> None:
        # 模块：官方风格产物输出
        # 输入：解析结果与轨迹对象
        # 输出：episode-*/prompt.txt、response.txt、debug.json
        # 作用：提供与 Harbor 既有可视化/分析链路对齐的结果目录结构。
        try:
            plugin_tool_index = self._load_plugin_tool_index()
            episodes = self._build_episode_pairs(
                parsed=parsed,
                trajectory=trajectory,
                plugin_tool_index=plugin_tool_index,
            )
            for idx, episode in enumerate(episodes):
                ep_dir = self.logs_dir / f"episode-{idx}"
                ep_dir.mkdir(parents=True, exist_ok=True)
                (ep_dir / "prompt.txt").write_text(episode.get("prompt", ""), encoding="utf-8")
                (ep_dir / "response.txt").write_text(episode.get("response", ""), encoding="utf-8")
                (ep_dir / "raw.json").write_text(
                    json.dumps(episode.get("raw", {}), ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
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
        plugin_tool_index: dict[str, list[dict[str, str]]] | None = None,
    ) -> list[dict[str, Any]]:
        episodes: list[dict[str, Any]] = []
        tool_index = plugin_tool_index or {}

        if trajectory is not None:
            # 让 episode 数量与轨迹 step 数量对齐，便于对照调试。
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
                            "raw": {
                                "prompt_raw": prompt,
                                "response_raw": "",
                                "source": step.source,
                                "step_id": step.step_id,
                                "timestamp": step.timestamp,
                            },
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
                    tool_call_records = self._build_tool_call_records(step.tool_calls, tool_index)
                    tool_result_records = self._build_tool_result_records(step.observation, tool_call_records)
                    tool_details_text = self._render_tool_details_text(
                        tool_call_records,
                        tool_result_records,
                    )
                    response_text = step.message or ""
                    if tool_details_text:
                        response_text = (
                            f"{response_text}\n\n{tool_details_text}"
                            if response_text
                            else tool_details_text
                        )

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
                    if tool_call_records:
                        debug_obj["tool_calls"] = tool_call_records
                    if tool_result_records:
                        debug_obj["tool_results"] = tool_result_records

                    episodes.append(
                        {
                            "prompt": prompt,
                            "response": response_text,
                            "raw": {
                                "prompt_raw": prompt,
                                "response_raw": step.message or "",
                                "response_with_tool_details": response_text,
                                "model": step.model_name,
                                "step_id": step.step_id,
                                "timestamp": step.timestamp,
                                "tool_calls": tool_call_records,
                                "tool_results": tool_result_records,
                                "token_usage": {
                                    "prompt_tokens": step.metrics.prompt_tokens if step.metrics else None,
                                    "completion_tokens": step.metrics.completion_tokens if step.metrics else None,
                                    "cached_tokens": step.metrics.cached_tokens if step.metrics else None,
                                    "cost_usd": step.metrics.cost_usd if step.metrics else None,
                                },
                            },
                            "debug": debug_obj,
                        }
                    )
                    episode_index += 1
                    continue

                episodes.append(
                    {
                        "prompt": last_prompt or system_prompt or "",
                        "response": step.message or "",
                        "raw": {
                            "prompt_raw": last_prompt or system_prompt or "",
                            "response_raw": step.message or "",
                            "source": step.source,
                            "step_id": step.step_id,
                            "timestamp": step.timestamp,
                        },
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
                            "raw": {
                                "prompt_raw": "",
                                "response_raw": text,
                                "source": "payloads",
                                "index": idx,
                            },
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
                    "raw": {
                        "prompt_raw": "",
                        "response_raw": parsed.get("text", "") if isinstance(parsed.get("text"), str) else "",
                        "source": "fallback",
                    },
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
        # 模块：结构化日志汇总
        # 输入：解析结果、轨迹、上下文计数与输出模式
        # 输出：job.log/trial.log 的摘要与逐轮日志
        # 作用：把关键诊断信息收敛到统一日志，便于问题回放与对比。
        usage = parsed.get("usage") if isinstance(parsed.get("usage"), dict) else {}
        payloads = parsed.get("payloads") if isinstance(parsed.get("payloads"), list) else []
        text = parsed.get("text") if isinstance(parsed.get("text"), str) else ""
        session_id = parsed.get("sessionId") if isinstance(parsed.get("sessionId"), str) else ""
        model = parsed.get("model") if isinstance(parsed.get("model"), str) else (self.model_name or "")
        step_count = len(trajectory.steps) if trajectory is not None else 0
        plugin_tool_index = self._load_plugin_tool_index()

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
        self._append_job_log(f"openclaw: plugin_tool_index_size={len(plugin_tool_index)}")
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
                    tool_call_records = self._build_tool_call_records(step.tool_calls, plugin_tool_index)
                    self._append_job_log(
                        "openclaw: turn[{}] tool_calls={}".format(
                            turn,
                            json.dumps(tool_call_records, ensure_ascii=False),
                        )
                    )
                if step.observation and step.observation.results:
                    tool_call_records = self._build_tool_call_records(step.tool_calls, plugin_tool_index)
                    tool_result_records = self._build_tool_result_records(
                        step.observation,
                        tool_call_records,
                    )
                    self._append_job_log(
                        "openclaw: turn[{}] tool_results={}".format(
                            turn,
                            json.dumps(tool_result_records, ensure_ascii=False),
                        )
                    )

        if stderr_lines:
            self._append_job_log(f"openclaw: stderr_lines={len(stderr_lines)}")
            for idx, line in enumerate(stderr_lines[:10], start=1):
                self._append_job_log(f"openclaw: stderr[{idx}] {line}")
        self._append_job_log("openclaw: run summary end")

    def _cleanup_agent_artifacts(self) -> None:
        # 模块：运行后清理
        # 输入：logs 目录中的临时执行产物
        # 输出：删除不需要暴露给上层的中间文件/目录
        # 作用：保持输出目录稳定、简洁，并与官方结果布局保持一致。
        # 为保持与官方布局一致，清理不对上层暴露的低层执行中间产物。
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

        # 不保留 terminus 专用产物，避免污染 openclaw 适配器输出。
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
        # 模块：MCP 服务注册命令构建
        # 输入：`mode` 与 `self.mcp_servers`
        # 输出：shell 命令字符串（无 MCP 时返回 None）
        # 作用：生成 OpenClaw/兼容后端可读取的 MCP 配置文件。
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

        # 在 cli-backend 模式仍写入 mcporter 配置保持兼容，
        # 同时额外写一份后端可直接读取的 MCP 配置。
        backend_mcp_config = shlex.quote(json.dumps({"mcpServers": servers}, indent=2))
        return (
            f"mkdir -p /root/.mcporter {_STATE_DIR} && "
            f"echo {escaped_mcporter} > {_MCPORTER_CONFIG} && "
            f"echo {backend_mcp_config} > {_STATE_DIR}/backend-mcp.json"
        )

    def _build_register_skills_command(self) -> str | None:
        # 模块：Skills 同步命令构建
        # 输入：`self.skills_dir`
        # 输出：复制 skills 的 shell 命令（无目录时返回 None）
        # 作用：将 Harbor 提供的技能目录同步到容器内固定位置。
        if not self.skills_dir:
            return None
        return (
            f"mkdir -p {_SKILLS_DIR} && "
            f"cp -r {shlex.quote(self.skills_dir)}/* "
            f"{_SKILLS_DIR}/ 2>/dev/null || true"
        )

    def _resolve_session_dirs(self) -> list[Path]:
        # 模块：Session 目录发现
        # 输入：`logs_dir/openclaw-state/agents`
        # 输出：可用 sessions 目录列表
        # 作用：为 transcript 定位提供候选路径集合。
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
        """定位 transcript 文件路径。

        输入：`session_id`（可为空，空时退化为“取最新 transcript”策略）。
        输出：可读 transcript 文件路径或 `None`。
        作用：
        1) 优先使用已复制到 logs 目录的 transcript；
        2) 其次在 sessions 目录按 session/topic/reset 命名匹配；
        3) 在多个匹配文件中选择最新修改时间的文件。
        """

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
            # 优先取最新文件；OpenClaw 可能在同目录并存 reset/topic 变体。
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
            # OpenClaw 可能将 transcript 按 topic 存为
            # <sessionId>-topic-<encodedTopic>.jsonl，重置归档则是 *.jsonl.reset.*。
            # 这里同时兼容两类命名。
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

    def _extract_tool_result_text(self, content: Any) -> str | None:
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text.strip())
                        continue
                    parts.append(json.dumps(item, ensure_ascii=False))
                    continue
                if item is None:
                    continue
                item_text = str(item).strip()
                if item_text:
                    parts.append(item_text)
            merged = "\n".join(part for part in parts if part).strip()
            return merged or None

        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            rendered = json.dumps(content, ensure_ascii=False).strip()
            return rendered or None

        if isinstance(content, str):
            normalized = content.strip()
            return normalized or None

        if content is None:
            return None

        normalized = str(content).strip()
        return normalized or None

    def _parse_transcript_to_trajectory(
        self, session_id: str, default_model_name: str
    ) -> Trajectory | None:
        """将 OpenClaw transcript 转换为 Harbor ATIF 轨迹。

        输入：`session_id` 与默认模型名。
        输出：`Trajectory` 或 `None`。
        作用：
        1) 解析 user/assistant/system 事件；
        2) 提取 tool_use/tool_result 并做关联合并；
        3) 汇总 token metrics，生成标准 ATIF 结构。
        """

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

            role_raw = message.get("role")
            role = str(role_raw).strip().lower() if role_raw is not None else ""
            if role not in ("user", "assistant", "system", "toolresult"):
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

            if role == "toolresult":
                call_id_raw = (
                    message.get("toolCallId")
                    or message.get("toolUseId")
                    or message.get("tool_call_id")
                    or message.get("tool_use_id")
                    or event.get("toolCallId")
                    or event.get("toolUseId")
                    or event.get("tool_call_id")
                    or event.get("tool_use_id")
                )
                call_id = str(call_id_raw or "").strip()

                tool_name = str(message.get("toolName") or message.get("tool_name") or "").strip()
                result_text = self._extract_tool_result_text(content)
                if tool_name and result_text:
                    result_text = f"[tool={tool_name}]\n{result_text}"

                if call_id or result_text:
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
                continue

            for block in blocks:
                btype = str(block.get("type") or "").lower()

                if btype == "text":
                    text = str(block.get("text") or "").strip()
                    if text:
                        text_parts.append(text)
                elif btype in ("tool_use", "toolcall", "tool_call"):
                    call_id = str(block.get("id") or "")
                    tool_name = str(block.get("name") or "")
                    arguments = block.get("input")
                    if arguments is None:
                        arguments = block.get("arguments")
                    if arguments is None:
                        arguments = {}
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
                    call_id = str(
                        block.get("tool_use_id")
                        or block.get("toolUseId")
                        or block.get("tool_call_id")
                        or block.get("toolCallId")
                        or ""
                    )
                    result_text = self._extract_tool_result_text(block.get("content"))
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

            source = "agent" if turn["role"] not in ("user", "system") else turn["role"]
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
