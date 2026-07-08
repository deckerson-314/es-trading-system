import logging

class StrategyFactory:
    """
    Factory class to instantiate strategies dynamically based on a name.
    """
    
    @staticmethod
    def get_strategy(strategy_name: str, params_dict: dict):
        """
        Get an instance of the requested strategy.
        
        Args:
            strategy_name: Name of the strategy (case-insensitive).
            params_dict: Parameters dictionary to initialize the strategy.
            
        Returns:
            Strategy: An instance of a class inheriting from Strategy.
            
        Raises:
            ValueError: If the strategy name is unknown.
        """
        name = strategy_name.lower().strip()
        
        if name == "bollinger" or name == "bollingerv5":
            try:
                from strategies.bollinger.strategy import BollingerStrategy
                logging.info(f"Factory: Loading BollingerStrategy (v5 logic)")
                return BollingerStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import BollingerStrategy: {e}")
                raise
        elif name == "trend":
            try:
                from strategies.trend.strategy import TrendStrategy
                logging.info(f"Factory: Loading TrendStrategy (deprecated — prefer session)")
                return TrendStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import TrendStrategy: {e}")
                raise
        elif name == "session" or name == "session_vwap":
            try:
                from strategies.session.strategy import SessionVwapStrategy
                logging.info("Factory: Loading SessionVwapStrategy (deprecated — prefer orb)")
                return SessionVwapStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import SessionVwapStrategy: {e}")
                raise
        elif name == "orb" or name == "orb_acceptance":
            try:
                from strategies.orb.strategy import OrbAcceptanceStrategy
                logging.info("Factory: Loading OrbAcceptanceStrategy")
                return OrbAcceptanceStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import OrbAcceptanceStrategy: {e}")
                raise
        elif name == "vwap_regime" or name == "vwap":
            try:
                from strategies.vwap_regime.strategy import VwapRegimeStrategy
                logging.info("Factory: Loading VwapRegimeStrategy")
                return VwapRegimeStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import VwapRegimeStrategy: {e}")
                raise
        else:
            raise ValueError(
                f"Unknown strategy: '{strategy_name}'. Available: ['bollinger', 'orb', 'session', 'trend', 'vwap_regime']"
            )
