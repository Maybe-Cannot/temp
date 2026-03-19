# openclaw 自建仓库



26/03/16 从openclaw官方仓库迁移过来
当前官方仓库，在使用源码安装时，存在一个bug

[Bug: A2UI bundle missing from Docker image — canvas/a2ui broken](https://github.com/openclaw/openclaw/issues/12878)

简单来说：这是一个官方曾经存在过的打包 Bug。在旧版本中，官方为了减小 Git 仓库体积，不再追踪那个生成的 js 文件，但由于 .dockerignore 设置太严，导致 Docker 构建时既找不到源代码也找不到预编译文件，最后生成了一个“残疾”的镜像。
从 v2026.1.29 开始，官方规定 a2ui.bundle.js 不再随代码上传（Stop tracking），而是在构建时动态生成。
官方在 #13114 提交中通过以下三步彻底解决了这个问题：
解除封锁：修改 .dockerignore，允许 apps/shared/... 等源码进入构建环境。
取消逃生舱：删除了 OPENCLAW_A2UI_SKIP_MISSING=1。以前设置这个是为了让构建“带病运行”，现在强制要求必须能生成 A2UI。
增强校验：修改脚本。如果没源码且没预编译包，构建会直接报错退出，而不是生成一个坏掉的镜像。

目前可按照以下方式处理
```bash
git submodule update --init --recursive
git log --grep="#13114"
```

3.19更新： 问题的本质并不是真的出现了什么bug,而是我们删除了原有.git仓库后，相关hook失效了。

## pnpm处理
在处理好之后，使用以下方式即可构建
```bash
pnpm install
pnpm build
npm link
```
通常，你应该打包
```bash
pnpm install
pnpm build
pnpm pack
npm install -g ./openclaw-2026.3.14.tgz
```

当然，不建议你在仓库里直接运行，因为这样会使得仓库内容太大
```bash
pnpm install
pnpm build
```
我提供了包
需要通过一下命令拉取

1.稀疏检出

```bash
mkdir test
cd test
git init
git remote add -f origin https://github.com/Maybe-Cannot/temp.git
git config core.sparseCheckout true
echo "openclaw-2026.3.14.tgz" >> .git/info/sparse-checkout
git pull origin openclaw
```
2.release方式

```bash
mkdir test 
cd test
curl -L -O https://github.com/Maybe-Cannot/temp/releases/download/v1.0.0/openclaw-2026.3.14.tgz
npm install -g ./openclaw-2026.3.14.tgz
```
