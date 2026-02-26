"""
Centralized configuration management for the trading ecosystem.
Uses environment variables with Firebase as the source of truth for dynamic updates.
"""
import os
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import firebase_admin
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

# Initialize structured logging
logger = logging.getLogger(__name__)


class ExchangeType(Enum):
    """Supported exchange types with validation"""
    BINANCE = "binance"
    COINBASE = "coinbase"
    KRAKEN = "kraken"
    BYBIT = "bybit"


@dataclass
class NodeConfig:
    """Immutable configuration for a trading node"""
    node_id: str
    exchange_type: ExchangeType
    max_position_size: float
    risk_tolerance: float  # 0.0-1.0
    learning_rate: float
    update_frequency_seconds: int
    firebase_project: str
    
    def validate(self) -> bool:
        """Validate configuration parameters"""
        if self.max_position_size <= 0:
            raise ValueError("max_position_size must be positive")
        if not 0 <= self.risk_tolerance <= 1:
            raise ValueError("risk_tolerance must be between 0 and 1")
        if self.learning_rate <= 0:
            raise ValueError("learning_rate must be positive")
        return True


class ConfigManager:
    """Manages configuration with Firebase real-time updates"""
    
    def __init__(self, project_id: str, node_id: str):
        self.project_id = project_id
        self.node_id = node_id
        self._config_cache: Optional[NodeConfig] = None
        self._firestore_client: Optional[firestore.Client] = None
        self._config_listener = None
        
        # Initialize Firebase if not already initialized
        if not firebase_admin._apps:
            cred = firebase_admin.credentials.ApplicationCredentials()
            firebase_admin.initialize_app(cred, {
                'projectId': project_id
            })
            logger.info("Firebase initialized for ConfigManager")
    
    def get_config(self) -> NodeConfig:
        """Get configuration with caching and validation"""
        if self._config_cache:
            return self._config_cache
        
        try:
            db = firestore.client()
            doc_ref = db.collection('node_configs').document(self.node_id)
            config_data = doc_ref.get().to_dict()
            
            if not config_data:
                logger.warning(f"No config found for node {self.node_id}, using defaults")
                config_data = self._get_default_config()
            
            config = NodeConfig(
                node_id=self.node_id,
                exchange_type=ExchangeType(config_data['exchange_type']),
                max_position_size=float(config_data['max_position_size']),
                risk_tolerance=float(config_data['risk_tolerance']),
                learning_rate=float(config_data['learning_rate']),
                update_frequency_seconds=int(config_data['update_frequency_seconds']),
                firebase_project=self.project_id
            )
            
            config.validate()
            self._config_cache = config
            logger.info(f"Configuration loaded for node {self.node_id}")
            
            # Set up real-time listener for config updates
            self._setup_config_listener(doc_ref)
            
            return config
            
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            # Fall back to environment variables
            return self._get_fallback_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Generate default configuration"""
        return {
            'exchange_type': 'binance',
            'max_position_size': 1000.0,
            'risk_tolerance': 0.02,
            'learning_rate': 0.001,
            'update_frequency_seconds': 60
        }
    
    def _get_fallback_config(self) -> NodeConfig:
        """Fallback configuration from environment variables"""
        return NodeConfig(
            node_id=self.node_id,
            exchange_type=ExchangeType(os.getenv('EXCHANGE_TYPE', 'binance')),
            max_position_size=float(os.getenv('MAX_POSITION_SIZE', 1000.0)),
            risk_tolerance=float(os.getenv('RISK_TOLERANCE', 0.02)),
            learning_rate=float(os.getenv('LEARNING_RATE', 0.001)),
            update_frequency_seconds=int(os.getenv('UPDATE_FREQUENCY', 60)),
            firebase_project=self.project_id
        )
    
    def _setup_config_listener(self, doc_ref):
        """Set up Firebase real-time listener for config updates"""
        def on_config_update(doc_snapshot, changes, read_time):
            try:
                config_data = doc_snapshot[0].to_dict()
                if config_data:
                    new_config = NodeConfig(
                        node_id=self.node_id,
                        exchange_type=ExchangeType(config_data['exchange_type']),
                        max_position_size=float(config_data['max