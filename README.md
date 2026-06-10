# Harbor 项目更改

Harbor 是由 [Terminal-Bench](https://www.tbench.ai/) 的开发团队推出的一个用于评估和优化智能体（Agent）与大语言模型（LLM）的框架。

项目链接：

项目官方文档：

****

## 01 安装

建议使用 `conda + python3.12`（harbor 要求 Python >= 3.12）

使用以下指令完成包的安装：

```bash
pip install git+https://github.com/Maybe-Cannot/temp.git@harbor
```

> **注**：安装需要 `pyproject.toml` 与 `src/` 同时存在于仓库根目录，仅上传 `src/` 无法构建。

## 02 配置 API 密钥

在任意位置创建 `.env` 文件，填入需要的 provider，其余保持注释：

```
# Anthropic
# ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_BASE_URL=https://api.anthropic.com

# OpenAI
# OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=https://api.openai.com/v1

# DeepSeek
# DEEPSEEK_API_KEY=sk-...
# DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# Qwen（阿里云百炼 / DashScope）
# DASHSCOPE_API_KEY=sk-...
# DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# Kimi（月之暗面）
# MOONSHOT_API_KEY=sk-...
# MOONSHOT_BASE_URL=https://api.moonshot.cn/v1

# GLM（智谱 AI）
# ZAI_API_KEY=...
# ZAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4/
```

运行时通过 `--env-file` 传入：

```bash
harbor run ... --env-file /path/to/.env
```

多个 provider 可同时写入，切换模型时**只改 `--model`**，`.env` 不动。

可使用的模型及格式请参考 [LiteLLM 定价文档](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)。

> **注**：DeepSeek / Qwen / Kimi / GLM 暂无 LiteLLM 计价条目，不影响实验结果。

## 03 支持的模型格式

`--model` 参数统一使用 `provider/model` 格式：

| provider 前缀 | 示例                                                   |
| ------------- | ------------------------------------------------------ |
| `anthropic/`  | `anthropic/claude-opus-4-8`                            |
| `openai/`     | `openai/gpt-4o`                                        |
| `deepseek/`   | `deepseek/deepseek-chat`                               |
| `dashscope/`  | `dashscope/qwen-plus`、`dashscope/qwen-max`            |
| `moonshot/`   | `moonshot/moonshot-v1-8k`、`moonshot/moonshot-v1-128k` |
| `zai/`        | `zai/glm-4-flash`、`zai/glm-4-air`                     |
| `nvidia/`     | `nvidia/llama-3.1-nemotron-70b-instruct`               |

## 04 启动一个任务

```bash
harbor run --help
```

### 4.1 数据集下载

```bash
harbor datasets list
harbor datasets download *name*
```

### 4.2 运行验证

```bash
harbor run -d terminal-bench-sample -a oracle
```

### 4.3 运行标准任务

```bash
harbor run -d hello-world -m deepseek/deepseek-v4-pro -a terminus-2
```

### 4.4 从本地数据集启动任务

```bash
harbor run -p <path> -m deepseek/deepseek-chat -a terminus-2 --env-file /path/to/.env
```

路径下每个子目录代表一个测试任务，根目录需包含 `task.toml`。

### 4.5 使用 openclaw

openclaw v2026.5.5 已接入并注册，支持上述所有 provider：

```bash
harbor run -p <path> -m deepseek/deepseek-chat -a openclaw --env-file /path/to/.env
harbor run -p <path> -m dashscope/qwen-plus -a openclaw --env-file /path/to/.env
harbor run -p <path> -m anthropic/claude-opus-4-8 -a openclaw --env-file /path/to/.env
```

## 05 SkillSafetyBench 实验

数据集已展平至 `ssb-dataset/`（155 个 case，每个子目录含 `task.toml`）。

```bash
# 运行全部数据集
harbor run \
  -p D:/code/skill/skill-safety-bench/ssb-dataset \
  -m deepseek/deepseek-chat \
  -a openclaw \
  --env-file D:/code/skill/skill-safety-bench/.env

# 运行单个 task（调试）
harbor run \
  -p D:/code/skill/skill-safety-bench/ssb-dataset/ssb_rd1_c1_01 \
  -m deepseek/deepseek-chat \
  -a openclaw \
  --env-file D:/code/skill/skill-safety-bench/.env
```

结果在 `jobs/` 目录下，关注 `attack_results.json` 中的 `attack_success_count`（越少越好）。

## 示例：运行 Terminal-Bench-2.0

```bash
export ANTHROPIC_API_KEY=<你的密钥>
harbor run --dataset terminal-bench@2.0 \
   --agent claude-code \
   --model anthropic/claude-opus-4-8 \
   --n-concurrent 4
```

云端运行（Daytona）：

```bash
export ANTHROPIC_API_KEY=<你的密钥>
export DAYTONA_API_KEY=<你的密钥>
harbor run --dataset terminal-bench@2.0 \
   --agent claude-code \
   --model anthropic/claude-opus-4-8 \
   --n-concurrent 100 \
   --env daytona
```

