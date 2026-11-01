# Any2PDF

[English](README.en.md) · [下载便携版](https://github.com/LiamxZhang/any2pdf/releases) · [构建状态](https://github.com/LiamxZhang/any2pdf/actions)

本地 PDF 转换工具，支持 Windows、Linux 和 macOS。选择文件或拖入窗口，添加到队列后转换；历史记录保留结果、失败原因与诊断详情。**默认中文，可随时切换 English。文件不上传服务器。**

![Any2PDF 中文界面](docs/screenshots/zh.png)

## 使用

1. 在 Releases 下载对应系统的完整便携包并解压，**保留整个文件夹**。
2. Windows 双击 `Any2PDF.exe`；Linux 运行 `Any2PDF/Any2PDF`；macOS 打开 `Any2PDF.app`。不需要安装 Python、LibreOffice 或浏览器。
3. 在「上传文件」选择或拖入文件，在「转换队列」选择输出目录，点击「开始转换」。
4. 在「历史记录」打开 PDF、查看失败原因、查看诊断或重试。清空历史不会删除原文件和 PDF。

各平台便携包由原生 CI 构建，并在所有平台的真实转换与界面启动检查通过后自动发布。若 Releases 暂无版本，请查看 Actions 中尚未完成或失败的构建；源码不等同于可直接启动的发行包。

| 平台 | 首版目标 |
| --- | --- |
| Windows | x86-64，Windows 10/11 |
| Linux | x86-64，glibc ≥ 2.35，Ubuntu 22.04 或更新桌面环境 |
| macOS | Apple Silicon / arm64，macOS 12 或更新；首版不包含 Intel 包 |

Linux 需要正常的桌面图形、字体和音频系统库，具体见 [第三方与运行环境说明](THIRD_PARTY.md)。这是便携桌面包，不是适用于所有发行版的静态二进制。未签名的 Windows/macOS 下载应用可能触发系统的首次运行提示。

## 格式与限制

| 文件 | 支持情况 |
| --- | --- |
| PDF | 校验并复制到输出目录，保留原件 |
| JPG / JPEG / PNG / BMP / TIFF / WebP / GIF | 转为 PDF，多帧图像逐页转换 |
| TXT / CSV / JSON / Markdown / 日志 / 常见代码 | 文本分页，支持 UTF-8、带 BOM 的 UTF-16、GB18030；Markdown 和 CSV 按纯文本排版 |
| DOC / DOCX / XLS / XLSX / PPT / PPTX / ODT / ODS / ODP / RTF | 随包 LibreOffice 转换，复杂排版可能与 Microsoft Office 有差异 |
| HTML / HTM | 随包 Chromium 打印，优先使用随包字体，字体外观可能与原页面不同；加载同目录内的本地资源，禁用 JavaScript 和外部网络 |

每个文件上限 **10 GiB（10,737,418,240 字节）**，大于十进制 10 GB。程序保留本地文件路径，分块读取文本/PDF、逐页写出文本与图像。页索引、单页图像、字体、Office 和 Chromium 仍然需要内存；输入上限不代表任何 10 GiB 文件都一定能完成。请预留足够内存与输出磁盘空间，单任务最长 2 小时。

不支持的格式、损坏文件、密码保护、缺失引擎、权限不足、空间不足、超时及进程异常会明确显示失败原因，不会将扩展名改成 `.pdf` 冒充成功。不保证转换任意私有格式。程序不会覆盖已有 PDF；同名输出自动添加序号。

## 隐私与历史

“上传”只添加本地路径，不上传任何内容。历史、语言设置和错误日志存储在当前用户目录：Windows `%LOCALAPPDATA%/Any2PDF`；Linux `$XDG_DATA_HOME/Any2PDF`（默认 `~/.local/share/Any2PDF`）；macOS `~/Library/Application Support/Any2PDF`。日志含本地路径和引擎诊断；清空历史会清除对应诊断日志，输出文件保留。软件使用本地转换器，并不构成处理恶意文档的安全沙箱。

## 开发与构建

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e ".[dev]"
python main.py
python -m pytest tests -q
```

源码模式下，内置文本/图像/PDF 转换可立即使用；Office/HTML 需下载引擎。完整便携包构建：

```bash
python -m scripts.build --archive
# Windows
python -m scripts.smoke dist/Any2PDF/Any2PDF.exe --gui-smoke
# Linux（CI 使用 xvfb-run -a）
python -m scripts.smoke dist/Any2PDF/Any2PDF --gui-smoke
# macOS
python -m scripts.smoke dist/Any2PDF.app/Contents/MacOS/Any2PDF --gui-smoke
```

必须在目标系统构建，不支持从 Windows 交叉编译 macOS/Linux。脚本从官方归档下载带校验的 LibreOffice，保留原始许可，下载 Chromium 和中文字体并打包到 `vendor`。开发时可用 `ANY2PDF_LIBREOFFICE` 指向 `soffice`，或 `ANY2PDF_VENDOR` 指向完整引擎目录。发行包默认仅使用随包引擎。

推送 `v*` 标签触发三平台构建、引擎转换与真实 Qt 界面启动检查；全部成功才创建 GitHub Release。普通分支构建只生成 Actions artifacts。测试证据见 [验证记录](docs/verification.md)。

## 许可证

项目代码采用 [MIT](LICENSE)。Qt、LibreOffice、Chromium、字体及其他依赖保留各自许可证，见 [THIRD_PARTY.md](THIRD_PARTY.md)。
