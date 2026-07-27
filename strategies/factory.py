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
        elif name == "mim":
            try:
                from strategies.mim.strategy import MimStrategy
                logging.info("Factory: Loading MimStrategy")
                return MimStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import MimStrategy: {e}")
                raise
        elif name == "candle" or name == "candle_pattern":
            try:
                from strategies.candle.strategy import CandlePatternStrategy
                logging.info("Factory: Loading CandlePatternStrategy")
                return CandlePatternStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import CandlePatternStrategy: {e}")
                raise
        elif name == "rth_drift" or name == "rthdrift" or name == "session_part":
            try:
                from strategies.rth_drift.strategy import RthDriftStrategy
                logging.info("Factory: Loading RthDriftStrategy")
                return RthDriftStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import RthDriftStrategy: {e}")
                raise
        elif name == "ema_cross" or name == "emacross":
            try:
                from strategies.ema_cross.strategy import EmaCrossStrategy
                logging.info("Factory: Loading EmaCrossStrategy")
                return EmaCrossStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import EmaCrossStrategy: {e}")
                raise
        elif name == "vwap_reclaim" or name == "vwapreclaim" or name == "reclaim":
            try:
                from strategies.vwap_reclaim.strategy import VwapReclaimStrategy
                logging.info("Factory: Loading VwapReclaimStrategy")
                return VwapReclaimStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import VwapReclaimStrategy: {e}")
                raise
        elif name in ("open_drive_pullback", "opendrive", "open_drive", "odp"):
            try:
                from strategies.open_drive_pullback.strategy import OpenDrivePullbackStrategy
                logging.info("Factory: Loading OpenDrivePullbackStrategy")
                return OpenDrivePullbackStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import OpenDrivePullbackStrategy: {e}")
                raise
        elif name in ("tod_hold", "todhold", "fixed_tod", "tod"):
            try:
                from strategies.tod_hold.strategy import TodHoldStrategy
                logging.info("Factory: Loading TodHoldStrategy")
                return TodHoldStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import TodHoldStrategy: {e}")
                raise
        elif name in ("session_premium", "sessprem", "overnight_premium", "ovn", "session_risk"):
            try:
                from strategies.session_premium.strategy import SessionPremiumStrategy
                logging.info("Factory: Loading SessionPremiumStrategy")
                return SessionPremiumStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import SessionPremiumStrategy: {e}")
                raise
        elif name in ("sr_zones", "sr", "sr_breakout", "srzones"):
            try:
                from strategies.sr_zones.strategy import SrZonesStrategy
                logging.info("Factory: Loading SrZonesStrategy")
                return SrZonesStrategy(params_dict)
            except ImportError as e:
                logging.error(f"Factory: Failed to import SrZonesStrategy: {e}")
                raise
        else:
            raise ValueError(
                f"Unknown strategy: '{strategy_name}'. "
                f"Available: ['bollinger', 'orb', 'mim', 'candle', 'rth_drift', 'ema_cross', 'vwap_reclaim', 'open_drive_pullback', 'tod_hold', 'session_premium', 'sr_zones', 'session', 'trend', 'vwap_regime']"
            )
