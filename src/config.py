"""
数据源管理模块
"""
import yaml
import os

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "app.yaml")
_config = None


def load_config(path=None):
    global _config
    if _config is not None:
        return _config
    config_path = path or _CONFIG_PATH
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f)
    else:
        _config = {
            "app": {"name": "Sanl", "version": "1.0.0", "debug": True, "host": "0.0.0.0", "port": 8899, "api_key": "changeme"},
            "database": {"path": "./data/nodes.db"},
            "subs_check": {"binary_path": "./subs-check", "config_path": "./config/subs-check.yaml", "output_dir": "./output"},
            "sources": {"github": {"enabled": True, "refresh_interval": 3600}, "telegram": {"enabled": True, "refresh_interval": 7200}},
            "scheduler": {"fetch_cron": "0 */6 * * *", "check_cron": "30 * * * *", "auto_clean_days": 7, "check_backend": "subs-check"}
        }
    return _config


def get_config():
    return load_config()


def get_app_config():
    return load_config().get("app", {})


def get_subs_check_config():
    return load_config().get("subs_check", {})


def get_scheduler_config():
    return load_config().get("scheduler", {})