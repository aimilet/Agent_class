# 助教 Agent 桌面应用

当前前端已经切换为课程化多 Agent 工作台，主入口仍是 Rust 原生桌面应用。

桌面端使用 `eframe/egui`，直接连接本地 FastAPI 后端，并且可以在“设置”页托管本地后端进程。

## 启动

先准备后端环境：

```bash
cd backend
uv sync
```

再启动桌面端：

```bash
cd frontend
cargo run
```

默认连接地址：

```text
http://127.0.0.1:18080
```

如果后端尚未启动，可以在桌面端“设置”页点击“启动后端”。

## 当前页面

- `总览`：查看课程、名单、作业导入、命名、评审初始化、正式评审的整体进度。
- `课程与名单`：创建课程，上传名单材料，运行初始化 Agent，确认候选并写入课程名单。
- `作业与提交`：创建单次作业，选择作业文件夹，运行导入 Agent，确认提交匹配并应用导入。
- `命名与审批`：创建命名策略，生成命名计划，查看命令预览，审批后执行改名或回滚。
- `评审初始化`：上传题目/答案/评分规范材料，运行评审初始化 Agent，检查并修正单题基线。
- `正式评审`：创建评审运行，启动多 Agent 评分，查看结果，人工复核并提交发布审批。
- `日志审计`：查看 Agent 调用、工具调用、课程审计事件和错误留痕。
- `设置`：管理后端地址、本地后端目录、后端进程和后端日志。

## 设计约束

- 功能页与设置页分离，避免所有配置堆叠在一个界面。
- 高风险副作用必须先生成计划和审批任务，再由用户显式批准与执行。
- Agent 结果以结构化表格、状态标签、JSON 引用和命令预览展示。
- 视觉风格采用浅色、低边框、圆角卡片和侧边栏布局，接近 macOS 原生应用的平面化表达。
- 最小窗口尺寸已降低到 `560 x 380`，便于在小屏或分屏环境下使用。

## 构建

开发检查：

```bash
cd frontend
cargo check
```

本机 Linux 发布构建：

```bash
cd frontend
cargo build --release
```

### Windows 客户端构建

在 WSL/Linux 下给 Windows 生成可双击运行的客户端时，必须构建 MSVC 目标：

```bash
cd frontend
bash build-windows-msvc.sh
```

生成位置：

```text
frontend/target/x86_64-pc-windows-msvc/release/frontend-gui.exe
```

如果 Windows 正在占用旧的 `frontend-gui.exe`，脚本会自动改为生成
`frontend-gui-YYYYMMDD-HHMMSS.exe`，这仍然是同一条 MSVC 构建链路的产物。

诊断版控制台程序：

```bash
cd frontend
FRONTEND_CONSOLE=1 bash build-windows-msvc.sh
```

生成位置：

```text
frontend/target/x86_64-pc-windows-msvc/release/frontend-console.exe
```

这条链路依赖：

- Rust 目标：`x86_64-pc-windows-msvc`
- `zig`：默认路径为 `$HOME/.local/bin/zig`
- `cargo-xwin` 已准备的 Windows MSVC sysroot：默认目录为 `/tmp/xwin-cache`
- 项目内 shim：`frontend/toolchain/msvc-shims` 与 `tools`

不要用下面这个目标给 Windows 用户发客户端：

```bash
cargo build --release --target x86_64-pc-windows-gnu
```

历史测试中 GNU 目标生成的 `frontend.exe` 在 Windows 双击运行不稳定；当前可复用的成功方式是 `x86_64-pc-windows-msvc`。

Windows/Linux 均可使用同一套 Rust 桌面前端源码构建；如果要完整运行 Agent 流程，仍需要同机或可访问地址上的后端与 LLM 配置。
