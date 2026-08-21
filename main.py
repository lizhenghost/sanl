#!/usr/bin/env python3
"""
NodePool 主入口
"""
import sys
import os
import logging

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.api.api import create_app
from src.config import get_app_config
import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    config = get_app_config()
    host = config.get("host", "0.0.0.0")
    port = config.get("port", 8899)
    
    logger.info(f"Starting NodePool on {host}:{port}")
    
    app = create_app()
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )


if __name__ == "__main__":
    main()
