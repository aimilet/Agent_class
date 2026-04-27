#![cfg_attr(
    all(target_os = "windows", not(feature = "console")),
    windows_subsystem = "windows"
)]

mod api;
mod app;
mod models;

use eframe::egui;
use std::fs::OpenOptions;
#[cfg(feature = "console")]
use std::io;
use std::io::Write;
use std::panic;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::SystemTime;

static PANIC_DIALOG_SHOWN: AtomicBool = AtomicBool::new(false);

fn main() -> eframe::Result<()> {
    install_panic_hook();
    console_log("诊断版已进入 main。");
    write_startup_log("开始启动助教 Agent 桌面端。");

    let result = run_app();
    match &result {
        Ok(()) => {
            write_startup_log("桌面端正常退出。");
            console_log("eframe 已返回 Ok，程序即将退出。");
        }
        Err(err) => {
            let message = format!("桌面端启动失败：{err}");
            write_startup_log(&message);
            show_startup_error(&message);
        }
    }
    pause_console();
    result
}

fn run_app() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1280.0, 820.0])
            .with_min_inner_size([360.0, 280.0])
            .with_title("助教 Agent 桌面端"),
        centered: true,
        // 更保守的 shader 可以避开部分旧显卡/虚拟机环境启动即崩的问题。
        shader_version: Some(eframe::egui_glow::ShaderVersion::Gl120),
        ..Default::default()
    };

    write_startup_log("NativeOptions 已创建，准备进入 eframe。");
    console_log("准备调用 eframe::run_native。");
    eframe::run_native(
        "助教 Agent 桌面端",
        options,
        Box::new(|cc| {
            console_log("eframe 已回调 app creator。");
            write_startup_log("eframe 已创建窗口上下文，开始初始化应用。");
            Ok(Box::new(app::AssistantApp::new(cc)))
        }),
    )
}

fn install_panic_hook() {
    let default_hook = panic::take_hook();
    panic::set_hook(Box::new(move |info| {
        let location = info
            .location()
            .map(|loc| format!("{}:{}:{}", loc.file(), loc.line(), loc.column()))
            .unwrap_or_else(|| "未知位置".to_owned());
        let payload = info
            .payload()
            .downcast_ref::<&str>()
            .map(|value| (*value).to_owned())
            .or_else(|| info.payload().downcast_ref::<String>().cloned())
            .unwrap_or_else(|| "未知 panic".to_owned());
        let message = format!("程序崩溃：{payload}\n位置：{location}");
        write_startup_log(&message);
        if !PANIC_DIALOG_SHOWN.swap(true, Ordering::SeqCst) {
            show_startup_error(&message);
        }
        default_hook(info);
    }));
}

fn show_startup_error(message: &str) {
    let log_paths = startup_log_paths()
        .into_iter()
        .map(|path| path.display().to_string())
        .collect::<Vec<_>>()
        .join("\n");
    let description = format!("{message}\n\n请查看启动日志：\n{log_paths}");
    let _ = rfd::MessageDialog::new()
        .set_level(rfd::MessageLevel::Error)
        .set_title("助教 Agent 启动失败")
        .set_description(description)
        .set_buttons(rfd::MessageButtons::Ok)
        .show();
}

fn write_startup_log(message: &str) -> Option<PathBuf> {
    console_log(message);
    for path in startup_log_paths() {
        if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&path) {
            let _ = writeln!(file, "[{:?}] {message}", SystemTime::now());
            return Some(path);
        }
    }
    None
}

fn startup_log_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(parent) = exe_path.parent() {
            paths.push(parent.join("frontend-startup.log"));
        }
    }
    paths.push(std::env::temp_dir().join("frontend-startup.log"));
    paths
}

fn console_log(message: &str) {
    #[cfg(feature = "console")]
    {
        println!("{message}");
    }
    #[cfg(not(feature = "console"))]
    {
        let _ = message;
    }
}

fn pause_console() {
    #[cfg(feature = "console")]
    {
        println!();
        println!("诊断版已停止在这里，按 Enter 关闭窗口。");
        let mut input = String::new();
        let _ = io::stdin().read_line(&mut input);
    }
}
