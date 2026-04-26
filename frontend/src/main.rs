#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

mod api;
mod app;
mod models;

use eframe::egui;

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1280.0, 820.0])
            .with_min_inner_size([560.0, 380.0])
            .with_title("助教 Agent 桌面端"),
        ..Default::default()
    };

    eframe::run_native(
        "助教 Agent 桌面端",
        options,
        Box::new(|cc| Ok(Box::new(app::AssistantApp::new(cc)))),
    )
}
