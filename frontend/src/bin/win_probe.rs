use std::fs::OpenOptions;
use std::io::{self, Write};
use std::time::SystemTime;

fn main() {
    println!("win_probe 已进入 main。");
    if let Ok(exe) = std::env::current_exe() {
        println!("当前 exe：{}", exe.display());
        if let Some(parent) = exe.parent() {
            let log_path = parent.join("win-probe.log");
            if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(&log_path) {
                let _ = writeln!(file, "[{:?}] win_probe 已进入 main。", SystemTime::now());
                println!("日志已写入：{}", log_path.display());
            } else {
                println!("日志写入失败：{}", log_path.display());
            }
        }
    }
    println!("按 Enter 关闭。");
    let mut input = String::new();
    let _ = io::stdin().read_line(&mut input);
}
