<!-- ascii-profile-lab: tutorial -->
# ASCII Profile Lab

**把 GitHub 头像变成清晰的字符画，再做成会自动更新的粉白终端主页。**

A practical Python + SVG tutorial and reusable GitHub Profile template. 中文教程 / offline demo / public GitHub stats / GitHub Actions.

[![Checks](https://github.com/ThreshoLdnnis/ascii-profile-lab/actions/workflows/profile.yml/badge.svg)](https://github.com/ThreshoLdnnis/ascii-profile-lab/actions/workflows/profile.yml)
[完整中文教程](docs/TUTORIAL.zh-CN.md) · [Use this template](https://github.com/ThreshoLdnnis/ascii-profile-lab/generate) · [作者实际主页](https://github.com/ThreshoLdnnis)

![实战效果：头像字符画与粉白终端信息卡](https://raw.githubusercontent.com/ThreshoLdnnis/ThreshoLdnnis/main/assets/profile-dark.svg)

上图是这次制作的实际效果。仓库内另附**原创几何机器人**示例，数字明确标为演示数据，可以完全离线试跑。

## 你会得到什么

- 112 × 70 个字符的头像：保留轮廓、发丝和五官细节。
- 粉色中间调与白色高光，配深色背景；电脑横版、手机竖版各两种主题。
- 无外部字体、脚本或图片依赖的 SVG 卡片。
- 真实的公开仓库数、收到的 Stars / Forks、关注数据和账号注册时长。
- 每天自动更新的 GitHub Actions，不需要个人访问令牌或第三方图片服务。

## 三步用在自己的主页

### 1. 从模板创建同名公开仓库

点击 **[Use this template → Create a new repository](https://github.com/ThreshoLdnnis/ascii-profile-lab/generate)**。

Owner 选自己，Repository name **填自己的 GitHub 用户名**，可见性选 **Public**。例如账号是 `alice`，主页仓库就是 `alice/alice`，不是 `alice/ascii-profile-lab`。

已有同名仓库时，按[完整教程](docs/TUTORIAL.zh-CN.md)中的已有仓库方案复制文件，保留自己的 README 内容。

### 2. 修改 `profile.json`

把占位符换成真实账号。最小配置：

```json
{
  "username": "alice",
  "name": "Alice"
}
```

也可以填写 `role`、`focus`、`stack`、`now`、`tagline`、`introduction` 和 `projects`。它们都是可选字段；不用把作者的个人介绍照搬过去。

### 3. 运行工作流

打开仓库 **Actions → ASCII Profile Lab → Run workflow**。第一次使用时，如果 GitHub 提示尚未启用工作流，按页面提示启用。

工作流会获取你的公开头像和数据、生成四张 SVG，再更新根目录 `README.md`。打开 `https://github.com/你的用户名` 查看效果。之后每天计划在北京时间 **08:17** 更新，修改配置也会触发更新。

**教程仓库只运行检查和离线演示；只有 `用户名/用户名` 仓库会自动更新主页 README。** 账号配置与仓库 Owner 不一致时会直接报错，避免误用别人的头像和数据。

## 先在本地试跑

需要 Python 3.12 或更新版本：

```sh
python -m pip install -r requirements.txt
python scripts/generate_profile.py --demo
```

无需账号、Token 或联网请求。打开 `examples/profile-dark.svg`，或查看 [demo 的 README](examples/PROFILE_README.md)。

使用自己的账号时，先编辑 `profile.json`，再运行：

```sh
python scripts/fetch_stats.py
python scripts/generate_profile.py
```

用本地照片替代 GitHub 头像：

```sh
python scripts/generate_profile.py --portrait "path/to/portrait.jpg"
```

更多命令：

```sh
# 已有同来源缓存时，离线重绘
python scripts/generate_profile.py --offline

# 把离线示例输出到另一个目录
python scripts/generate_profile.py --demo --output-dir output

# 仅在自己的同名主页仓库里，明确指定生成根 README
python scripts/generate_profile.py --readme README.md

python -m unittest discover -s tests -v
```

## 文件怎么分工

| 文件 | 用途 |
| :--- | :--- |
| `README.md` | 这里的教程入口；普通本地生成不会覆盖它 |
| `docs/TUTORIAL.zh-CN.md` | 从建仓库到图像算法、配色、排版和排障的完整说明 |
| `profile.json` | 你的账号和可选简介 |
| `scripts/generate_profile.py` | 图像处理、ASCII 网格与 SVG 渲染 |
| `scripts/profile_cli.py` | 命令行、来源缓存、通用 README 生成 |
| `scripts/fetch_stats.py` | 通过 GitHub REST API 获取公开数据 |
| `assets/` | 使用真实账号生成的卡片与缓存 |
| `PROFILE_README.md` | 默认的个人主页生成结果，可先预览再使用 |
| `examples/` | 原创机器人、明确标注的示例数据及离线效果 |
| `.github/workflows/profile.yml` | 检查、离线演示与同名主页的自动更新 |

## 为什么这版头像更清楚

最初的低密度网格会丢失眼睛和发丝；暗底上若把亮部映成空格，白发还会“消失”。这版提高字符密度，结合亮度、轻度锐化和边缘信息，保留粉色层次与白色高光。相邻同色字符合并成 SVG `tspan`，同时控制文件体积。

缓存也有两个明确处理：头像缓存记录来源，换账号后不能沿用旧头像；README 使用直接的 `raw.githubusercontent.com` 图片地址和内容摘要，减少新图已生成但主页仍显示旧图的问题。

算法公式、字符宽高比、`<picture>` 和自定义配色见[完整中文教程](docs/TUTORIAL.zh-CN.md)。

## 数据说明

真实模式只统计本人拥有的**公开仓库**；Stars / Forks 是这些仓库收到的总数，语言是非 Fork 公开仓库的主要语言计数。`Uptime` 是 **GitHub 账号年龄**，不是个人年龄。不会估算提交数或代码行数。离线演示的数字是样例，卡片和 README 都会注明。

计划任务可能延迟；长期无仓库活动时，GitHub 可能暂停定时工作流。参见 [Profile README 条件](https://docs.github.com/en/account-and-profile/how-tos/profile-customization/managing-your-profile-readme)、[从模板创建仓库](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)和[定时工作流说明](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

## 许可与灵感

代码、文档与程序生成的机器人示例采用 [MIT](LICENSE)。作者主页图片以远程链接展示。

视觉灵感来自 [Andrew Grant 的终端风 Profile](https://github.com/Andrew6rant/Andrew6rant)；本仓库提供独立的 Python / SVG 实现与制作过程。
