"""
ChanAnalyzer Web 服务启动脚本

使用方法:
    python web/start_server.py        # 启动服务（自动打开浏览器）
    python web/start_server.py --no-browser  # 启动服务（不打开浏览器）
"""
import os
import sys

# 修复 tushare 权限问题：强制使用 /tmp 目录存储 token
os.environ['TUSHARE_PATH'] = '/tmp'
import subprocess
import webbrowser
import argparse
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def check_dependencies():
    """检查依赖是否安装"""
    missing = []

    try:
        import fastapi
    except ImportError:
        missing.append("fastapi")

    try:
        import uvicorn
    except ImportError:
        missing.append("uvicorn")

    if missing:
        print("❌ 缺少依赖，请先安装:")
        print(f"   pip install {' '.join(missing)}")
        return False

    return True


def start_server(host=None, port=None, open_browser=True):
    """启动 FastAPI 服务器"""
    if not check_dependencies():
        return

    # 检测是否在云平台环境（Render、Railway 等）
    is_cloud = os.environ.get("RENDER", "") or os.environ.get("RAILWAY", "") or os.environ.get("PORT", "")

    # 云平台默认配置
    if host is None:
        host = "0.0.0.0" if is_cloud else "127.0.0.1"
    if port is None:
        port = int(os.environ.get("PORT", "8000"))

    # 云环境不打开浏览器
    if is_cloud:
        open_browser = False

    # 导入 app
    from web.api import app

    # 服务器地址
    server_url = f"http://{host}:{port}"

    print("=" * 50)
    print("🚀 ChanAnalyzer Web 服务")
    print("=" * 50)
    print(f"📍 服务地址: {server_url}")
    print(f"📄 API 文档: {server_url}/docs")
    print(f"🌐 前端页面: {server_url}/static/index.html")
    print("=" * 50)
    print("按 Ctrl+C 停止服务")
    print()

    # 打开浏览器
    if open_browser:
        # 延迟1秒打开浏览器，等待服务器启动
        import threading
        def open_browser_later():
            import time
            time.sleep(1.5)
            webbrowser.open(f"{server_url}/static/login.html")
        threading.Thread(target=open_browser_later, daemon=True).start()

    # 启动服务器
    import uvicorn
    # 使用导入字符串以支持 reload
    uvicorn.run(
        "web.api:app",
        host=host,
        port=port,
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChanAnalyzer Web 服务")
    parser.add_argument("--host", default=None, help="监听地址（默认云平台0.0.0.0，本地127.0.0.1）")
    parser.add_argument("--port", type=int, default=None, help="监听端口（默认从环境变量PORT读取或8000）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    args = parser.parse_args()

    try:
        start_server(
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser
        )
    except KeyboardInterrupt:
        print("\n👋 服务已停止")
