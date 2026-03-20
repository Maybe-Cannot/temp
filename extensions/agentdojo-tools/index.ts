import fs from "node:fs";
import path from "node:path";
import {
  definePluginEntry,
  type AnyAgentTool,
  type OpenClawPluginApi,
  type OpenClawPluginConfigSchema,
} from "openclaw/plugin-sdk/core";
import { runCommandWithTimeout } from "openclaw/plugin-sdk/process-runtime";

type AgentDojoToolsPluginConfig = {
  catalogPath?: string;
  runnerPath?: string;
  pythonBin?: string;
  configPath?: string;
  statePath?: string;
  callLogPath?: string;
  toolNamePrefix?: string;
  registerOptionalTools?: boolean;
  timeoutMs?: number;
};

type ResolvedPluginConfig = {
  catalogPath: string;
  runnerPath?: string;
  pythonBin: string;
  configPath?: string;
  statePath?: string;
  callLogPath?: string;
  toolNamePrefix: string;
  registerOptionalTools: boolean;
  timeoutMs: number;
};

type CatalogRunner = {
  path?: string;
  python?: string;
  env?: Record<string, unknown>;
};

type CatalogTool = {
  name?: string;
  runner_name?: string;
  description?: string;
  parameters?: Record<string, unknown>;
};

type AgentDojoToolCatalog = {
  suite_name?: string;
  benchmark_version?: string;
  tool_name_prefix?: string;
  runner?: CatalogRunner;
  tools?: CatalogTool[];
};

const DEFAULT_CATALOG_PATH = "./openclaw_tool_catalog.json";
const DEFAULT_CATALOG_FALLBACK_PATH = "/testbed/openclaw_tool_catalog.json";
const DEFAULT_PYTHON_BIN = "python";
const DEFAULT_TOOL_PREFIX = "agentdojo_";
const DEFAULT_REGISTER_OPTIONAL_TOOLS = false;
const DEFAULT_TIMEOUT_MS = 120_000;
const DEFAULT_STATE_PATH = "/testbed/environment_state.json";
const DEFAULT_PRE_STATE_PATH = "/testbed/pre_environment_state.json";

const pluginConfigJsonSchema = {
  type: "object",
  additionalProperties: false,
  properties: {
    catalogPath: { type: "string", default: DEFAULT_CATALOG_PATH },
    runnerPath: { type: "string" },
    pythonBin: { type: "string", default: DEFAULT_PYTHON_BIN },
    configPath: { type: "string" },
    statePath: { type: "string" },
    callLogPath: { type: "string" },
    toolNamePrefix: { type: "string", default: DEFAULT_TOOL_PREFIX },
    registerOptionalTools: { type: "boolean", default: DEFAULT_REGISTER_OPTIONAL_TOOLS },
    timeoutMs: { type: "number", minimum: 1000, default: DEFAULT_TIMEOUT_MS },
  },
} as const;

const agentdojoToolsPluginConfigSchema: OpenClawPluginConfigSchema = {
  safeParse(value: unknown) {
    try {
      return { success: true, data: resolvePluginConfig(value) };
    } catch (error) {
      return {
        success: false,
        error: {
          issues: [
            {
              path: [],
              message: error instanceof Error ? error.message : String(error),
            },
          ],
        },
      };
    }
  },
  jsonSchema: pluginConfigJsonSchema,
};

function normalizeString(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : undefined;
}

function normalizeNumber(value: unknown): number | undefined {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return undefined;
  }
  return value;
}

function normalizeBoolean(value: unknown): boolean | undefined {
  if (typeof value !== "boolean") {
    return undefined;
  }
  return value;
}

function resolvePluginConfig(value: unknown): ResolvedPluginConfig {
  const cfg = (value ?? {}) as AgentDojoToolsPluginConfig;
  return {
    catalogPath: normalizeString(cfg.catalogPath) ?? DEFAULT_CATALOG_PATH,
    runnerPath: normalizeString(cfg.runnerPath),
    pythonBin: normalizeString(cfg.pythonBin) ?? DEFAULT_PYTHON_BIN,
    configPath: normalizeString(cfg.configPath),
    statePath: normalizeString(cfg.statePath),
    callLogPath: normalizeString(cfg.callLogPath),
    toolNamePrefix: normalizeString(cfg.toolNamePrefix) ?? DEFAULT_TOOL_PREFIX,
    registerOptionalTools:
      normalizeBoolean(cfg.registerOptionalTools) ?? DEFAULT_REGISTER_OPTIONAL_TOOLS,
    timeoutMs: Math.max(1000, Math.floor(normalizeNumber(cfg.timeoutMs) ?? DEFAULT_TIMEOUT_MS)),
  };
}

function loadCatalog(catalogPath: string): AgentDojoToolCatalog {
  const raw = fs.readFileSync(catalogPath, "utf-8");
  const parsed = JSON.parse(raw) as AgentDojoToolCatalog;
  if (!Array.isArray(parsed.tools)) {
    throw new Error("agentdojo-tools: catalog.tools must be an array");
  }
  return parsed;
}

function resolveCatalogPath(
  api: OpenClawPluginApi,
  configuredCatalogPath: string,
): {
  catalogPath: string;
  source: "configured" | "fallback";
} {
  const resolvedConfigured = api.resolvePath(configuredCatalogPath);
  if (fs.existsSync(resolvedConfigured)) {
    return { catalogPath: resolvedConfigured, source: "configured" };
  }

  if (fs.existsSync(DEFAULT_CATALOG_FALLBACK_PATH)) {
    return { catalogPath: DEFAULT_CATALOG_FALLBACK_PATH, source: "fallback" };
  }

  throw new Error(
    `agentdojo-tools: catalog file not found: ${resolvedConfigured} ` +
      `or fallback ${DEFAULT_CATALOG_FALLBACK_PATH}`,
  );
}

function resolveRelativeTo(baseDir: string, value?: string): string | undefined {
  if (!value) {
    return undefined;
  }
  return path.isAbsolute(value) ? value : path.resolve(baseDir, value);
}

function normalizeRunnerEnv(
  catalogRunnerEnv: Record<string, unknown> | undefined,
): Record<string, string> {
  if (!catalogRunnerEnv) {
    return {};
  }
  const normalized: Record<string, string> = {};
  for (const [key, val] of Object.entries(catalogRunnerEnv)) {
    if (typeof val === "string") {
      normalized[key] = val;
    }
  }
  return normalized;
}

function resolveRunnerToolName(tool: CatalogTool, prefix: string): string | undefined {
  const runnerName = normalizeString(tool.runner_name);
  if (runnerName) {
    return runnerName;
  }
  const fallbackName = normalizeString(tool.name);
  if (!fallbackName) {
    return undefined;
  }
  if (prefix && fallbackName.startsWith(prefix)) {
    const stripped = fallbackName.slice(prefix.length).trim();
    return stripped || undefined;
  }
  return fallbackName;
}

function resolveRegisteredToolName(tool: CatalogTool, runnerName: string, prefix: string): string {
  const explicit = normalizeString(tool.name);
  if (explicit) {
    return explicit;
  }
  return `${prefix}${runnerName}`;
}

function normalizeParametersSchema(parameters: unknown): Record<string, unknown> {
  if (!parameters || typeof parameters !== "object" || Array.isArray(parameters)) {
    return { type: "object", properties: {} };
  }
  return parameters as Record<string, unknown>;
}

function resolveRunnerPath(params: {
  pluginCfg: ResolvedPluginConfig;
  catalog: AgentDojoToolCatalog;
  catalogDir: string;
}): { runnerPath: string; source: "plugin-config" | "catalog" | "default" } {
  const configRunnerPath = normalizeString(params.pluginCfg.runnerPath);
  const catalogRunnerPath = normalizeString(params.catalog.runner?.path);

  let source: "plugin-config" | "catalog" | "default" = "default";
  let rawPath = "./tool_runner.py";

  if (configRunnerPath) {
    source = "plugin-config";
    rawPath = configRunnerPath;
  } else if (catalogRunnerPath) {
    source = "catalog";
    rawPath = catalogRunnerPath;
  }

  const resolved = resolveRelativeTo(params.catalogDir, rawPath) ?? rawPath;
  if (!fs.existsSync(resolved)) {
    throw new Error(
      `agentdojo-tools: runner not found (${source}): ${resolved}. ` +
        "Ensure dataset workspace contains tool_runner.py or set plugins.entries.agentdojo-tools.config.runnerPath.",
    );
  }

  return { runnerPath: resolved, source };
}

function resolveStatePaths(runnerEnv: Record<string, string>): {
  statePath: string;
  preStatePath: string;
} {
  const statePath = normalizeString(runnerEnv.AGENTDOJO_STATE_PATH) ?? DEFAULT_STATE_PATH;
  const preStatePath =
    normalizeString(runnerEnv.AGENTDOJO_PRE_STATE_PATH) ?? DEFAULT_PRE_STATE_PATH;
  return { statePath, preStatePath };
}

function resolveInitTaskPath(runnerPath: string): string {
  return path.resolve(path.dirname(runnerPath), "init_task.py");
}

type PluginCommandRunResult = {
  code: number;
  stdout: string;
  stderr: string;
};

async function runPluginCommandWithTimeout(options: {
  argv: string[];
  timeoutMs: number;
  cwd?: string;
  env?: Record<string, string>;
}): Promise<PluginCommandRunResult> {
  const [command] = options.argv;
  if (!command) {
    return { code: 1, stdout: "", stderr: "command is required" };
  }

  try {
    const result = await runCommandWithTimeout(options.argv, {
      timeoutMs: options.timeoutMs,
      cwd: options.cwd,
      env: options.env,
    });
    const timedOut = result.termination === "timeout" || result.termination === "no-output-timeout";
    return {
      code: result.code ?? 1,
      stdout: result.stdout,
      stderr: timedOut
        ? result.stderr || `command timed out after ${options.timeoutMs}ms`
        : result.stderr,
    };
  } catch (error) {
    return {
      code: 1,
      stdout: "",
      stderr: error instanceof Error ? error.message : String(error),
    };
  }
}

const agentdojoToolsPlugin = definePluginEntry({
  id: "agentdojo-tools",
  name: "AgentDojo Tools",
  description: "Register AgentDojo tools from catalog and execute through Python runner",
  configSchema: agentdojoToolsPluginConfigSchema,
  register(api: OpenClawPluginApi) {
    if (api.registrationMode !== "full") {
      return;
    }

    const pluginCfg = resolvePluginConfig(api.pluginConfig);
    const catalogResolution = resolveCatalogPath(api, pluginCfg.catalogPath);
    const resolvedCatalogPath = catalogResolution.catalogPath;
    const catalogDir = path.dirname(resolvedCatalogPath);
    const catalog = loadCatalog(resolvedCatalogPath);

    if (catalogResolution.source === "fallback") {
      api.logger.warn(
        `agentdojo-tools: catalogPath ${pluginCfg.catalogPath} not found, fallback to ${resolvedCatalogPath}`,
      );
    }

    const defaultPrefix =
      normalizeString(pluginCfg.toolNamePrefix) ??
      normalizeString(catalog.tool_name_prefix) ??
      DEFAULT_TOOL_PREFIX;
    const runnerResolution = resolveRunnerPath({
      pluginCfg,
      catalog,
      catalogDir,
    });
    const resolvedRunnerPath = runnerResolution.runnerPath;

    const resolvedPythonBin =
      pluginCfg.pythonBin ?? normalizeString(catalog.runner?.python) ?? DEFAULT_PYTHON_BIN;

    const runnerEnv = normalizeRunnerEnv(catalog.runner?.env);
    runnerEnv.AGENTDOJO_TOOL_NAME_PREFIX = defaultPrefix;
    const resolvedConfigPath = resolveRelativeTo(catalogDir, pluginCfg.configPath);
    const resolvedStatePath = resolveRelativeTo(catalogDir, pluginCfg.statePath);
    const resolvedCallLogPath = resolveRelativeTo(catalogDir, pluginCfg.callLogPath);

    if (resolvedConfigPath) {
      runnerEnv.AGENTDOJO_CONFIG_PATH = resolvedConfigPath;
    }
    if (resolvedStatePath) {
      runnerEnv.AGENTDOJO_STATE_PATH = resolvedStatePath;
    }
    if (resolvedCallLogPath) {
      runnerEnv.AGENTDOJO_CALL_LOG_PATH = resolvedCallLogPath;
    }

    api.logger.info(
      `agentdojo-tools: using runner (${runnerResolution.source}) ${resolvedRunnerPath}`,
    );

    const statePaths = resolveStatePaths(runnerEnv);
    const resolvedInitTaskPath = resolveInitTaskPath(resolvedRunnerPath);

    let stateInitializationPromise: Promise<void> | null = null;
    const ensureStateInitialized = async (): Promise<void> => {
      if (fs.existsSync(statePaths.statePath) && fs.existsSync(statePaths.preStatePath)) {
        return;
      }

      if (!fs.existsSync(resolvedInitTaskPath)) {
        throw new Error(
          `agentdojo-tools: state files missing (${statePaths.statePath}, ${statePaths.preStatePath}) and init script not found: ${resolvedInitTaskPath}`,
        );
      }

      api.logger.warn(
        `agentdojo-tools: state files missing, running initializer ${resolvedInitTaskPath}`,
      );

      const initResult = await runPluginCommandWithTimeout({
        argv: [resolvedPythonBin, resolvedInitTaskPath],
        timeoutMs: pluginCfg.timeoutMs,
        cwd: catalogDir,
        env: runnerEnv,
      });

      if (initResult.code !== 0) {
        const stderr = initResult.stderr.trim();
        const stdout = initResult.stdout.trim();
        const details =
          stderr || stdout || `agentdojo-tools: init failed with exit code ${initResult.code}`;
        throw new Error(details);
      }

      if (!fs.existsSync(statePaths.statePath) || !fs.existsSync(statePaths.preStatePath)) {
        throw new Error(
          `agentdojo-tools: initializer finished but state files are still missing (${statePaths.statePath}, ${statePaths.preStatePath})`,
        );
      }
    };

    const ensureStateReady = async (): Promise<void> => {
      if (!stateInitializationPromise) {
        stateInitializationPromise = ensureStateInitialized().catch((error) => {
          stateInitializationPromise = null;
          throw error;
        });
      }
      await stateInitializationPromise;
    };

    void ensureStateReady().catch((error) => {
      const text = error instanceof Error ? error.message : String(error);
      api.logger.warn(`agentdojo-tools: eager state initialization failed: ${text}`);
    });

    let registeredCount = 0;
    for (const tool of catalog.tools ?? []) {
      const runnerName = resolveRunnerToolName(tool, defaultPrefix);
      if (!runnerName) {
        api.logger.warn("agentdojo-tools: skip tool with empty runner_name/name");
        continue;
      }

      const registeredName = resolveRegisteredToolName(tool, runnerName, defaultPrefix);
      const description =
        normalizeString(tool.description) ?? `AgentDojo tool bridge for ${runnerName}`;
      const parameters = normalizeParametersSchema(tool.parameters);

      const toolDefinition: AnyAgentTool = {
        name: registeredName,
        description,
        parameters,
        async execute(_toolCallId: string, params: unknown) {
          try {
            await ensureStateReady();
          } catch (error) {
            const text = error instanceof Error ? error.message : String(error);
            return {
              content: [{ type: "text", text }],
              isError: true,
              details: {
                code: 1,
                tool: runnerName,
                runnerPath: resolvedRunnerPath,
                stage: "init",
              },
            };
          }

          const result = await runPluginCommandWithTimeout({
            argv: [
              resolvedPythonBin,
              resolvedRunnerPath,
              runnerName,
              JSON.stringify((params as Record<string, unknown> | undefined) ?? {}),
            ],
            timeoutMs: pluginCfg.timeoutMs,
            cwd: catalogDir,
            env: runnerEnv,
          });

          const stdout = result.stdout.trim();
          const stderr = result.stderr.trim();
          if (result.code !== 0) {
            const text =
              stderr || stdout || `agentdojo-tools: runner failed with exit code ${result.code}`;
            return {
              content: [{ type: "text", text }],
              isError: true,
              details: {
                code: result.code,
                tool: runnerName,
                runnerPath: resolvedRunnerPath,
              },
            };
          }

          return {
            content: [{ type: "text", text: stdout || "(ok)" }],
            details: {
              code: result.code,
              tool: runnerName,
              runnerPath: resolvedRunnerPath,
            },
          };
        },
      };

      if (pluginCfg.registerOptionalTools) {
        api.registerTool(toolDefinition, { optional: true });
      } else {
        api.registerTool(toolDefinition);
      }

      registeredCount += 1;
    }

    api.logger.info(
      `agentdojo-tools: registered ${registeredCount} tools from ${resolvedCatalogPath}`,
    );
  },
});

export default agentdojoToolsPlugin;
