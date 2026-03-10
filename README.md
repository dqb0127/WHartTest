# WHartTest - AI驱动的智能测试用例生成平台

## 项目简介

WHartTest 是一个基于 Django REST Framework 构建的AI驱动测试自动化平台，核心功能是通过AI智能生成测试用例。平台集成了 LangChain、MCP（Model Context Protocol）工具调用、项目管理、需求评审、测试用例管理以及先进的知识库管理和文档理解功能。利用大语言模型和多种嵌入服务（OpenAI、Azure OpenAI、Ollama等）的能力，自动化生成高质量的测试用例，并结合知识库提供更精准的测试辅助，为测试团队提供一个完整的智能测试管理解决方案。

## 平台功能
1. AI智能测试用例生成  
基于大语言模型（LLM）技术，从需求文档或对话中自动生成结构化测试用例  
包含测试步骤、前置条件、输入数据、期望结果、优先级等完整信息  
支持多种嵌入服务（OpenAI、Azure OpenAI、Ollama等）增强理解能力
2. 知识库管理与文档理解  
集成知识库系统，支持文档上传、解析和嵌入搜索  
从API文档、需求文档中提取上下文信息  
提供精准的知识检索和语义理解能力
3. MCP（Model Context Protocol）工具调用  
支持多种AI工具的无缝集成和调用  
提供Playwright浏览器自动化、UI自动化、APP自动化等工具  
支持自定义工具扩展和第三方服务接入
4. 需求评审与风险分析  
AI驱动的需求文档评审功能  
自动识别需求中的潜在问题和风险点  
提供改进建议和测试策略指导
5. 测试用例管理与执行  
测试用例的创建、编辑、分类和组织  
支持测试套件和测试计划的制定  
批量执行测试用例并生成执行报告
6. 自动化脚本生成  
基于测试用例自动生成UI自动化脚本  
支持一键执行和调试功能  
降低自动化测试的技术门槛
7. 执行结果与报告分析  
自动截屏和测试结果记录  
详细的执行报告和统计分析  
支持结果导出和历史回溯
8. Skill系统（智能技能管理）  
Skill上传与管理：支持通过zip文件或Git仓库导入skill  
## 文档
详细文档请访问：https://mgdaaslab.github.io/WHartTest/

## 快速开始

### Docker 部署（推荐 - 开箱即用）

```bash
# 1. 克隆仓库
git clone https://github.com/MGdaasLab/WHartTest.git
cd WHartTest

# 2. 准备配置（使用默认配置，包含自动生成的API Key）
cp .env.example .env

# 3. 一键启动（直接运行脚本，按提示选择 1 或 2）
./run_compose.sh

# 4. 访问系统
# http://localhost:8913 (admin/admin123456)
```

**就这么简单！** 系统会自动创建默认API Key，MCP服务开箱即用。

### 统一部署脚本

如果你使用仓库自带脚本部署，现在启动后会先让你在“远程拉镜像”和“本地构建镜像”之间二选一：

```bash
./run_compose.sh
```

这个脚本现在会：

- 先选择部署方式：`remote` 远程镜像下载，或 `local` 本地构建镜像
- `remote` 模式会自动在内置远程镜像仓库候选里测速择优，用户只需选择 `1` 即可
- `remote` 会按仓库类型分别选择：Docker Hub 使用官方 / `docker.1panel.live` / `docker.1ms.run` / `docker.xuanyuan.me` / `docker.m.daocloud.io`，GHCR 使用官方 / `ghcr.1ms.run` / `ghcr.nju.edu.cn` / `ghcr.m.daocloud.io`，MCR 使用官方 / `mcr.azure.cn` / `mcr.m.daocloud.io`
- `local` 模式会自动探测当前网络下更快的 `APT / PyPI / npm / Hugging Face` 下载地址
- Python 依赖安装现在支持自动回退：首选测速最快的 PyPI 源，某个包下载超时会顺序切到其余候选继续安装
- `local` 内置候选包含官方源、清华、中科大、阿里云、腾讯云、华为云、北外、上海交大、`npmmirror`、`hf-mirror` 等
- 支持通过环境变量继续追加你自己的候选镜像源
- 本地构建默认使用 Docker 缓存，不再每次都 `--no-cache`

常用示例：

```bash
# 交互选择部署方式
./run_compose.sh

# 直接使用远程预构建镜像
./run_compose.sh remote

# 直接使用本地构建，并自动选择更快下载源
./run_compose.sh local

# 本地构建时强制使用原生官方源
DOCKER_SOURCE_PROFILE=native ./run_compose.sh local

# 本地构建时强制只在镜像源里择优
DOCKER_SOURCE_PROFILE=mirror ./run_compose.sh local

# 给 PyPI 追加自定义候选源（注意用引号包起来）
DOCKER_PIP_CANDIDATES_EXTRA="corp|https://pypi.example.com/simple|https://pypi.example.com/simple/pip/" ./run_compose.sh local

# 只有在本地全量重建时才禁用缓存
DOCKER_BUILD_NO_CACHE=1 ./run_compose.sh local
```

> ⚠️ **生产环境提示**：请登录后台删除默认API Key并创建新的安全密钥。详见 [快速启动指南](./docs/QUICK_START.md)

详细的部署说明请参考：
- [快速启动指南](./docs/QUICK_START.md) - **推荐新用户阅读**
- [GitHub 自动构建部署指南](./docs/github-docker-deployment.md)
- [完整部署文档](https://mgdaaslab.github.io/WHartTest/)

## 页面展示

| | |
  |---|---|
  | ![alt text](docs\public\img\image-a1.png) | ![alt text](docs\public\img\image-a2.png) |
  | ![alt text](docs\public\img\image-a3.png)| ![alt text](docs\public\img\image-a4.png) |
  | ![alt text](docs\public\img\image-a5.png) | ![alt text](docs\public\img\image-a17.png) |
  | ![alt text](docs\public\img\image-a7.png) | ![alt text](docs\public\img\image-a8.png) |
  | ![alt text](docs\public\img\image-a9.png) | ![alt text](docs\public\img\image-a10.png) |
  | ![alt text](docs\public\img\image-a11.png) | ![alt text](docs\public\img\image-a12.png) |
  | ![alt text](docs\public\img\image-a13.png) | ![alt text](docs\public\img\image-a14.png) |
  | ![alt text](docs\public\img\image-a15.png) | ![alt text](docs\public\img\image-a16.png) |
## 贡献指南

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 创建 Pull Request


## 联系方式

如有问题或建议，请通过以下方式联系：
- 提交 Issue
- 项目讨论区
- 添加微信时请备注github，拉你进微信群聊。

<img width="400" alt="image" src="docs\public\img\wx.jpg" />

qq群：
1. 8xxxxxxxx0（已满）
2. 1017708746
---
## 【重要安全警示】关于 v1.4.0 以及后续版本 Skills 权限及部署安全的声明
鉴于 Skills 模块具备较高的系统执行权限，为了保障您的数据与环境安全，我们做出以下严正提示：

部署建议：强烈建议仅在内网环境或受信任的私有网络中部署使用。 访问控制：切勿将服务直接暴露于公网（Public Internet），或授予任何未经身份验证及不可信人员访问权限。 免责声明：本项目（WHartTest）仅供学习与研究使用。用户需自行承担因违规部署（如开放公网、未做鉴权等）所导致的一切安全风险与后果。对于因不当配置引发的数据泄露、服务器被入侵等安全事故，WHartTest 团队不承担任何法律及连带责任。
**WHartTest** - AI驱动测试用例生成，让测试更智能，让开发更高效！
