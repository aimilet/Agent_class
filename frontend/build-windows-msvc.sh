#!/usr/bin/env bash
set -euo pipefail

# 在 WSL/Linux 下交叉编译可双击运行的 Windows MSVC 版前端。
# 注意：不要用 x86_64-pc-windows-gnu 目标替代，历史测试中该产物在 Windows
# 双击运行不稳定；当前可用链路是 x86_64-pc-windows-msvc + xwin sysroot。

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
xwin_cache_dir="${XWIN_CACHE_DIR:-/tmp/xwin-cache}"
sysroot="$xwin_cache_dir/windows-msvc-sysroot/windows-msvc-sysroot"
target="x86_64-pc-windows-msvc"
out_dir="$script_dir/target/$target/release"
out_name="frontend-gui.exe"

if [ "${FRONTEND_CONSOLE:-0}" = "1" ]; then
    out_name="frontend-console.exe"
fi

if [ ! -d "$sysroot" ]; then
    echo "错误：未找到 Windows MSVC sysroot：$sysroot" >&2
    echo "请先准备 cargo-xwin 缓存，或设置 XWIN_CACHE_DIR 指向已有缓存目录。" >&2
    exit 1
fi

if [ ! -x "$HOME/.local/bin/zig" ]; then
    echo "错误：未找到 zig：$HOME/.local/bin/zig" >&2
    exit 1
fi

if ! rustup target list --installed | grep -qx "$target"; then
    echo "错误：未安装 Rust 目标：$target" >&2
    echo "请先执行：rustup target add $target" >&2
    exit 1
fi

export PATH="$repo_root/tools:$script_dir/toolchain/msvc-shims:$HOME/.cargo/bin:$HOME/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:$xwin_cache_dir"
export ZIG_GLOBAL_CACHE_DIR="${ZIG_GLOBAL_CACHE_DIR:-/tmp/zig-cache}"
export ZIG_LOCAL_CACHE_DIR="${ZIG_LOCAL_CACHE_DIR:-/tmp/zig-cache-local}"

export AR_x86_64_pc_windows_msvc="llvm-lib"
export CC_x86_64_pc_windows_msvc="clang"
export CXX_x86_64_pc_windows_msvc="clang"
export TARGET_AR="llvm-lib"
export TARGET_CC="clang"
export TARGET_CXX="clang"

export CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER="lld-link"
export CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS="-C linker-flavor=lld-link -C link-arg=-defaultlib:oldnames -Lnative=$sysroot/lib/x86_64-unknown-windows-msvc"

common_flags="--target=x86_64-windows-msvc -fuse-ld=lld-link -I$sysroot/include -I$sysroot/include/c++/stl -I$sysroot/include/__msvc_vcruntime_intrinsics -L$sysroot/lib/x86_64-unknown-windows-msvc"
export CFLAGS_x86_64_pc_windows_msvc="$common_flags"
export CXXFLAGS_x86_64_pc_windows_msvc="$common_flags"
export RCFLAGS="-I$sysroot/include -I$sysroot/include/c++/stl -I$sysroot/include/__msvc_vcruntime_intrinsics"

cd "$script_dir"

if [ "${FRONTEND_CONSOLE:-0}" = "1" ]; then
    cargo build --release --target "$target" --features console
else
    cargo build --release --target "$target"
fi

target_file="$out_dir/$out_name"
if ! cp -f "$out_dir/frontend.exe" "$target_file"; then
    timestamp="$(date +%Y%m%d-%H%M%S)"
    fallback_file="$out_dir/${out_name%.exe}-$timestamp.exe"
    echo "警告：无法覆盖 $target_file，可能是 Windows 正在占用该文件。" >&2
    echo "改为生成备用文件：$fallback_file" >&2
    cp "$out_dir/frontend.exe" "$fallback_file"
    target_file="$fallback_file"
fi

echo "已生成 Windows MSVC 前端：$target_file"
if command -v file >/dev/null 2>&1; then
    file "$target_file"
fi
