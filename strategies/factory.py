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
                logging.info(f"Factory: Loading TrendStrategy")
                return TrendStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import TrendStrategy: {e}")
                raise
        else:
            raise ValueError(f"Unknown strategy: '{strategy_name}'. Available: ['bollinger', 'trend']")
