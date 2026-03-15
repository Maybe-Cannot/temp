# log

## openclaw 的适配工作
 修改:
 - src\harbor\agents\installed\install-openclaw.sh.j2
 - src\harbor\agents\installed\openclaw.py
 - src\harbor\agents\factory.py:13

  15-1
  对openclaw的安装方式进行调整

```shell
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash
nvm install 22
#!/bin/bash
set -euo pipefail

# 本脚本用于在 Linux 环境下自动安装 openclaw 及其依赖，包括 nvm、Node.js、openclaw（可选指定版本）和 mcporter。

apt-get update
apt-get install -y curl git

# 安装 nvm（Node 版本管理器）
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash

export NVM_DIR="$HOME/.nvm"
# 加载 nvm，使用 || true 以兼容 nvm.sh 内部的非零返回值
\. "$NVM_DIR/nvm.sh" || true
# 验证 nvm 是否加载成功
command -v nvm &>/dev/null || { echo "错误：NVM 加载失败" >&2; exit 1; }

# 安装 Node.js 22 版本
nvm install 22
# 显示 npm 版本
npm -v

# 安装 openclaw（如指定 version 则安装对应版本，否则安装最新版）
{% if version %}
npm i -g openclaw@{{ version }}
{% else %}
npm i -g openclaw@latest
{% endif %}

# 安装 mcporter（openclaw 的 memory/QMD 子系统依赖）
# 注意：mcporter 并不提供通用的 MCP 工具服务器集成，openclaw 的 ACP 转换器当前会忽略外部 MCP 服务器。
npm i -g mcporter

# 显示 openclaw 版本，验证安装
openclaw --version
```

目前的安装方式是通过npm安装，现在我们需要将其改为从源码安装

官方提供的文档是这样的

```shell
git clone -b https://github.com/Maybe-Cannot/temp.git
cd temp

pnpm install
pnpm ui:build # 首次运行会自动安装 UI 依赖
pnpm build

pnpm openclaw onboard --install-daemon

# 开发循环（TS 变更自动重载）
pnpm gateway:watch
```

我们要改成

```shell
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash
nvm install 22
#!/bin/bash
set -euo pipefail

# 本脚本用于在 Linux 环境下自动安装 openclaw 及其依赖，包括 nvm、Node.js、openclaw（可选指定版本）和 mcporter。

apt-get update
apt-get install -y curl git

# 安装 nvm（Node 版本管理器）
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | bash

export NVM_DIR="$HOME/.nvm"
# 加载 nvm，使用 || true 以兼容 nvm.sh 内部的非零返回值
\. "$NVM_DIR/nvm.sh" || true
# 验证 nvm 是否加载成功
command -v nvm &>/dev/null || { echo "错误：NVM 加载失败" >&2; exit 1; }

# 安装 Node.js 22 版本
nvm install 22
# 显示 npm 版本
npm -v

npm install -g pnpm

# 安装 openclaw（如指定 version 则安装对应版本，否则安装最新版）
git clone -b openclaw https://github.com/Maybe-Cannot/temp.git
cd temp

pnpm install
pnpm ui:build # 首次运行会自动安装 UI 依赖
pnpm build
pnpm link --global
# 安装 mcporter（openclaw 的 memory/QMD 子系统依赖）
# 注意：mcporter 并不提供通用的 MCP 工具服务器集成，openclaw 的 ACP 转换器当前会忽略外部 MCP 服务器。
npm i -g mcporter

# 显示 openclaw 版本，验证安装
openclaw --version

```

