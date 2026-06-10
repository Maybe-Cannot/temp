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

所有密钥通过环境变量注入，多个 provider 可同时配置，互不冲突。切换模型时**只需修改 `--model` 参数**，无需重置变量。

```bash
export ANTHROPIC_API_KEY="sk-ant-..."

export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.openai.com/v1"

export DEEPSEEK_API_KEY="sk-..."
export DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"

export DASHSCOPE_API_KEY="sk-..."        # Qwen
export DASHSCOPE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"

export MOONSHOT_API_KEY="sk-..."         # Kimi
export MOONSHOT_BASE_URL="https://api.moonshot.cn/v1"

export ZAI_API_KEY="..."                 # GLM
export ZAI_BASE_URL="https://open.bigmodel.cn/api/paas/v4/"
```

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
harbor run -d hello-world -m deepseek/deepseek-chat -a terminus-2
```

### 4.4 从本地数据集启动任务

```bash
harbor run -p <path> -m deepseek/deepseek-chat -a terminus-2
```

路径下每个子目录代表一个测试任务，根目录需包含 `task.toml`。

### 4.5 使用 openclaw

openclaw v2026.5.5 已接入并注册，支持上述所有 provider：

```bash
harbor run -d hello-world -m deepseek/deepseek-chat -a openclaw
harbor run -d hello-world -m dashscope/qwen-plus -a openclaw
harbor run -d hello-world -m anthropic/claude-opus-4-8 -a openclaw
```

> 使用非 Anthropic 模型时建议加 `--skip-api-preflight`。

## 05 SkillSafetyBench 实验

```bash
cd skill-safety-bench

# 运行单个 risk domain
bash scripts/start_agent_batch.sh \
  --rd 1 --agent openclaw \
  --model deepseek/deepseek-chat \
  --skip-api-preflight

# 调试单个 case
bash scripts/start_agent_batch.sh \
  --rd 1 \
  --case offer_letter_routing_cue_precleared_merge_sheet \
  --agent openclaw --model dashscope/qwen-plus \
  --skip-api-preflight

# 干跑
bash scripts/start_agent_batch.sh --rd 1 --agent openclaw --dry-run
```

结果在 `jobs/.../attack_results.json`，关注 `attack_success_count`（越少越好）。

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



