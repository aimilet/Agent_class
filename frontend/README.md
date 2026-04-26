# 助教 Agent 桌面应用

当前主入口是 Rust 桌面应用，不是网页界面。

桌面端使用 `eframe/egui`，直接连接本地后端 API，并且可以在应用内托管后端进程。

## 启动

先准备后端环境：

```bash
cd backend
uv sync
```

再启动桌面端：

```bash
cd frontend
source "$HOME/.cargo/env"
cargo run
```

默认连接地址：

```text
http://127.0.0.1:18080
```

如果后端尚未启动，可以直接在桌面端左侧“0. 本地后端管理”中点击“启动后端”。

## 当前能力

- 桌面端内启动 / 停止 / 重启后端
- 查看后端进程日志
- 刷新后端状态、学生、规则、审阅任务
- 通过桌面文件选择器导入学生名单
- 切换名单解析模式：`auto / local_only / agent_layout`
- 创建改名规则
- 通过桌面文件夹选择器预览 / 执行批量改名
- 通过桌面文件 / 文件夹选择器创建审阅任务
- 切换审阅模式：`auto / local_ocr / agent_vision`
- 按关键词、执行状态、复核状态筛选任务提交
- 只查看未匹配学生的作业
- 对单份作业执行人工复核并回写数据库
- 查看单份作业的处理日志
- 导出当前任务报告为 `Markdown / JSON`
- 查看学生归属、匹配方式、分数和任务详情

## 已构建二进制

本地构建完成后，可执行文件在：

```text
frontend/target/debug/frontend
frontend/target/release/frontend
frontend/target/x86_64-pc-windows-msvc/release/frontend.exe
dist/windows/zhujiao-agent.exe
```

## Windows 产物

当前已经生成 Windows 版桌面应用：

```text
dist/windows/zhujiao-agent.exe
```

注意：

- 这是桌面端 GUI，本身可以打开
- 如果要实际执行名单导入、改名、自动审阅，仍然需要同机准备后端目录与 Python/uv 环境
