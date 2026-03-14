
# Harbor 项目更改

Harbor 是由 [Terminal-Bench](https://www.tbench.ai/) 的开发团队推出的一个用于评估和优化智能体（Agent）与大语言模型（LLM）的框架。

项目链接：

项目官方文档：

****

## 01 安装

建议使用`conda + python3.13`

使用以下指令来完成包的安装

```bash
pip install git+https://github.com/Maybe-Cannot/temp.git@harbor
```

## 02 临时配置

需要引入密钥环境变量，目前仅测试过qwen和deepseek

可使用的模型及格式请参考[Litellm定价文档](https://github.com/BerriAI/litellm/blob/main/model_prices_and_context_window.json)

导入格式：

```bash
export DASHSCOPE_API_KEY="****"
export DEEPSEEK_API_KEY="****"
export ANTHROPIC_API_KEY="****"
```

## 03 启动一个任务

要查看所有支持的智能体及其它选项，请运行：

```bash
harbor run --help
```

### 3.1 数据集下载

探索所有支持的第三方基准（如 SWE-Bench、Aider Polyglot），可以通过以下命令查看harbor内已注册数据集

```bash
harbor datasets list
```

随后可以通过download方法对指定数据集下载

```bash
harbor datasets download *name*
```

### 3.2 运行验证

再下载完数据集后可以使用该指令检测任务是否能够运行

```bash
harbor run -d terminal-bench-sample  -a oracle
```

-d 使用已注册数据集

-a 使用何种agent架构，oracle是数据集提供的解决方案

要在这些数据集上评测某个智能体和模型，可以使用如下命令：

```
harbor run -d "<dataset@version>" -m "<model>" -a "<agent>"
```

### 3.3 启动实际任务

配置

使用数据集hello-world

agent架构terminus-2

model选择deepseek/deepseek-chat

```bash
harbor run -d hello-world -m deepseek/deepseek-chat -a terminus-2
```

-m 设定所使用的模型

### 3.4 从自构建数据集中启动任务

```bash
harbor run -p *path* -m deepseek/deepseek-chat -a terminus-2
```

-p 代表本地数据集的路径，内部结构应符合harbor给出的标准：内部多个子目录，每个目录代指一个测试

可以使用相对路径，但建议填入绝对路径

### 3.5 使用openclaw

openclaw已被注册，可以直接使用，目前还没有对其全部功能进行测试

```bash
harbor run -d hello-world -m deepseek/deepseek-chat -a openclaw
```



## 示例：运行 Terminal-Bench-2.0

Harbor 是 [Terminal-Bench-2.0](https://github.com/laude-institute/terminal-bench-2) 的官方运行工具：

```
export ANTHROPIC_API_KEY=<你的密钥>
harbor run --dataset terminal-bench@2.0 \
   --agent claude-code \
   --model anthropic/claude-opus-4-1 \
   --n-concurrent 4
```

这将在本地通过 Docker 启动基准测试。若要在云服务商（如 Daytona）上运行，只需加上 `--env` 参数：

```
export ANTHROPIC_API_KEY=<你的密钥>
export DAYTONA_API_KEY=<你的密钥>
harbor run --dataset terminal-bench@2.0 \
   --agent claude-code \
   --model anthropic/claude-opus-4-1 \
   --n-concurrent 100 \
   --env daytona
```


