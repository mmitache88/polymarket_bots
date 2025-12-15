"""
Structured JSON logging for HFT strategy

Provides millisecond-precision timestamps and parseable output
for real-time monitoring and analysis.
"""

import json
import logging
import sys
from datetime import datetime
from typing import Any, Dict, Optional
from pathlib import Path


class JSONFormatter(logging.Formatter):
    """Custom formatter that outputs JSON lines"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "ts": datetime.utcnow().isoformat(timespec='milliseconds') + "Z",
            "level": record.levelname,
            "event": getattr(record, 'event', record.msg),
            "logger": record.name,
        }
        
        # Add extra fields if present
        if hasattr(record, 'data') and record.data:
            log_data["data"] = record.data
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


class HFTLogger:
    """
    Structured logger for HFT operations.
    
    Usage:
        logger = HFTLogger("hft.gateway")
        logger.info("MARKET_UPDATE", {"token": "abc", "bid": 0.45})
        logger.error("CONNECTION_FAILED", {"error": "timeout"})
    """
    
    def __init__(
        self,
        name: str,
        level: str = "INFO",
        log_to_file: bool = True,
        log_file: str = "logs/hft.log",
        json_format: bool = True
    ):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(getattr(logging, level.upper()))
        self.logger.handlers = []  # Clear existing handlers
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        if json_format:
            console_handler.setFormatter(JSONFormatter())
        else:
            console_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            )
        self.logger.addHandler(console_handler)
        
        # File handler
        if log_to_file:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(log_file)
            if json_format:
                file_handler.setFormatter(JSONFormatter())
            else:
                file_handler.setFormatter(
                    logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
                )
            self.logger.addHandler(file_handler)
    
    def _log(self, level: int, event: str, data: Optional[Dict[str, Any]] = None):
        """Internal logging method with structured data"""
        record = self.logger.makeRecord(
            self.logger.name,
            level,
            "",  # pathname
            0,   # lineno
            event,
            (),  # args
            None  # exc_info
        )
        record.event = event
        record.data = data or {}
        self.logger.handle(record)
    
    def debug(self, event: str, data: Optional[Dict[str, Any]] = None):
        self._log(logging.DEBUG, event, data)
    
    def info(self, event: str, data: Optional[Dict[str, Any]] = None):
        self._log(logging.INFO, event, data)
    
    def warning(self, event: str, data: Optional[Dict[str, Any]] = None):
        self._log(logging.WARNING, event, data)
    
    def error(self, event: str, data: Optional[Dict[str, Any]] = None):
        self._log(logging.ERROR, event, data)
    
    def critical(self, event: str, data: Optional[Dict[str, Any]] = None):
        self._log(logging.CRITICAL, event, data)
    
    # Convenience methods for common events
    def market_update(self, token_id: str, bid: float, ask: float, **kwargs):
        self.info("MARKET_UPDATE", {"token_id": token_id, "bid": bid, "ask": ask, **kwargs})
    
    def oracle_update(self, asset: str, price: float, **kwargs):
        self.info("ORACLE_UPDATE", {"asset": asset, "price": price, **kwargs})
    
    def trade_intent(self, action: str, token_id: str, side: str, price: float, size: float, reason: str):
        self.info("TRADE_INTENT", {
            "action": action, "token_id": token_id, "side": side,
            "price": price, "size": size, "reason": reason
        })
    
    def order_submitted(self, order_id: str, token_id: str, side: str, price: float, size: float):
        self.info("ORDER_SUBMITTED", {
            "order_id": order_id, "token_id": token_id,
            "side": side, "price": price, "size": size
        })
    
    def order_filled(self, order_id: str, fill_price: float, fill_size: float):
        self.info("ORDER_FILLED", {"order_id": order_id, "fill_price": fill_price, "fill_size": fill_size})
    
    def position_opened(self, token_id: str, side: str, entry_price: float, size: float):
        self.info("POSITION_OPENED", {"token_id": token_id, "side": side, "entry_price": entry_price, "size": size})
    
    def position_closed(self, token_id: str, exit_price: float, pnl: float, pnl_pct: float):
        self.info("POSITION_CLOSED", {"token_id": token_id, "exit_price": exit_price, "pnl": pnl, "pnl_pct": pnl_pct})
    
    def risk_rejection(self, reason: str, check_failed: str, **kwargs):
        self.warning("RISK_REJECTION", {"reason": reason, "check_failed": check_failed, **kwargs})
    
    def kill_switch(self, reason: str, triggered_by: str):
        self.critical("KILL_SWITCH", {"reason": reason, "triggered_by": triggered_by})


def get_logger(name: str = "hft") -> HFTLogger:
    """Factory function to get a configured HFT logger"""
    from .config import config
    
    return HFTLogger(
        name=name,
        level=config.logging.log_level,
        log_to_file=config.logging.log_to_file,
        log_file=config.logging.log_file,
        json_format=config.logging.json_logging
    )