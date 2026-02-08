from abc import ABC, abstractmethod
import pandas as pd

class Strategy(ABC):
    """
    Abstract Base Class for all trading strategies.
    Defines the contract for initialization, indicator calculation, signal generation, and exit logic.
    """
    
    @abstractmethod
    def __init__(self, params_dict: dict):
        """
        Initialize the strategy with a dictionary of parameters.
        
        Args:
            params_dict: Dictionary containing strategy parameters (usually loaded from CSV).
        """
        pass

    @abstractmethod
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate technical indicators and add them to the DataFrame.
        
        Args:
            df: Raw OHLCV DataFrame.
            
        Returns:
            DataFrame with added indicator columns.
        """
        pass

    @abstractmethod
    def calculate_entry_signals(self, df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """
        Generate entry signals based on indicators.
        
        Args:
            df: DataFrame with indicators.
            
        Returns:
            tuple: (long_signal_series, short_signal_series) - boolean or integer series (1/0).
        """
        pass
    
    @abstractmethod
    def check_exit(self, position: dict, row: pd.Series, df: pd.DataFrame) -> tuple[bool, str, float]:
        """
        Determine if an open position should be closed at the current bar.
        
        Args:
            position: Dictionary representing the current open position.
            row: Current bar (as a Series) from the DataFrame.
            df: Full DataFrame (for lookback if needed).
            
        Returns:
            tuple: (should_exit, reason, price)
                should_exit (bool): True if position should be closed.
                reason (str): Reason for exit (e.g., "Stop Loss", "Take Profit", "Signal").
                price (float): Execution price for the exit.
        """
        pass
        
    @abstractmethod
    def get_param_structure(self) -> dict:
        """
        Return the structure of parameters for display and logging.
        
        Returns:
            dict: Nested dictionary of parameter groups.
                  Example: {'Entry': {'Param1': val1}, 'Exit': {'Param2': val2}}
        """
        pass

    def setup_position(self, entry_price: float, direction: int, row: pd.Series, df: pd.DataFrame) -> dict:
        """
        Create a new position dictionary object.
        Can be overridden by subclasses if extra state is needed.
        
        Args:
            entry_price: Price the trade was entered at.
            direction: 1 for Long, -1 for Short.
            row: Current bar data.
            df: Full DataFrame.
            
        Returns:
            dict: Position object.
        """
        return {
            'entry_time': row.Index,
            'entry_price': entry_price,
            'direction': direction,
            'sl_price': 0.0,
            'tp_price': 0.0
        }
