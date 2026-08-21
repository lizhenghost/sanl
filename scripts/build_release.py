#!/usr/bin/env python3
"""
NodePool 发布构建脚本
打包项目为可分发的 tar.gz/zip 包
"""
import os
import sys
import tarfile
import zipfile
import json
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(PROJECT_ROOT, "dist")
VERSION = os.environ.get("RELEASE_VERSION", datetime.now().strftime("%Y%m%d-%H%M%S"))


def get_files_to_package():
    """获取需要打包的文件列表"""
    include_patterns = [
        "main.py",
        "requirements.txt",
        "README.md",
        "LICENSE",
        "CHANGELOG.md",
        "config/",
        "src/",
        "static/",
        "frontend/",
        "scripts/",
        "presets/",
        ".gitignore",
    ]

    files = []
    for pattern in include_patterns:
        path = os.path.join(PROJECT_ROOT, pattern)
        if os.path.isfile(path):
            files.append(path)
        elif os.path.isdir(path):
            for root, dirs, filenames in os.walk(path):
                # 排除 __pycache__ 和 .pyc
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in filenames:
                    if f.endswith(".pyc"):
                        continue
                    files.append(os.path.join(root, f))
    return files


def create_tar_gz(files, output_path):
    """创建 tar.gz 包"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with tarfile.open(output_path, "w:gz") as tar:
        for f in files:
            arcname = os.path.relpath(f, PROJECT_ROOT)
            tar.add(f, arcname=os.path.join(f"nodepool-{VERSION}", arcname))
    print(f"Created: {output_path}")


def create_zip(files, output_path):
    """创建 zip 包"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            arcname = os.path.relpath(f, PROJECT_ROOT)
            zf.write(f, arcname=os.path.join(f"nodepool-{VERSION}", arcname))
    print(f"Created: {output_path}")


def create_changelog():
    """生成 CHANGELOG.md"""
    changelog_path = os.path.join(PROJECT_ROOT, "CHANGELOG.md")
    if not os.path.exists(changelog_path):
        with open(changelog_path, "w") as f:
            f.write(f"""# NodePool Changelog

## v{VERSION} - {datetime.now().strftime("%Y-%m-%d")}

### 🚀 新功能
- 节点池聚合平台
- 多源订阅抓取与合并
- subs-check 测速引擎桥接
- 多格式订阅输出（Clash/V2Ray/Sing-box/Base64）
- 节点质量评分与排名
- Token 鉴权系统
- 多用户系统
- 世界地图可视化
- 数据源管理面板
- 定时自动抓取与测速

### 🔧 优化
- 自动去重合并
- 节点健康度监控
- 源自动禁用机制

### 🐛 修复
- 测速结果状态保存
- 定时任务调度稳定性
""")
    return changelog_path


def main():
    os.makedirs(DIST_DIR, exist_ok=True)

    # 确保 CHANGELOG 存在
    create_changelog()

    files = get_files_to_package()
    print(f"Packaging {len(files)} files...")

    # 创建 tar.gz
    tar_path = os.path.join(DIST_DIR, f"nodepool-{VERSION}.tar.gz")
    create_tar_gz(files, tar_path)

    # 创建 zip
    zip_path = os.path.join(DIST_DIR, f"nodepool-{VERSION}.zip")
    create_zip(files, zip_path)

    print(f"\n✅ Release {VERSION} built successfully!")
    print(f"  - {tar_path}")
    print(f"  - {zip_path}")


if __name__ == "__main__":
    main()