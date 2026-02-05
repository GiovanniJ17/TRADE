"""Configuration management"""
import yaml
import os
from pathlib import Path
from typing import Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Centralized configuration manager"""
    
    def __init__(self, config_path: str = "config/config.yaml"):
        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = {}
        self.load_config()
    
    def load_config(self):
        """Load YAML configuration file"""
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config = {}
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation (e.g., 'data_provider.provider')"""
        keys = key.split('.')
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value if value is not None else default
    
    def get_env(self, key: str, default: Any = None) -> str:
        """Get environment variable"""
        return os.getenv(key, default)
    
    def reload(self):
        """Reload configuration from file"""
        self.load_config()
    
    def set(self, key: str, value: Any):
        """Set configuration value in memory (does not persist to file)"""
        keys = key.split('.')
        config_dict = self.config
        for k in keys[:-1]:
            if k not in config_dict:
                config_dict[k] = {}
            config_dict = config_dict[k]
        config_dict[keys[-1]] = value


# Global config instance
config = Config()
