import logging
from datetime import datetime
from typing import Optional

from django_eventstream import send_event

logger = logging.getLogger(__name__)


class TaskLogger:
    """
    Unified logger that sends to both standard logging and SSE via django-eventstream
    """
    
    def __init__(
            self,
            task_id: Optional[str] = None,
            plugin_label: str = "",
    ):
        self.task_id = task_id
        self.plugin_label = plugin_label
        self.standard_logger = logging.getLogger(__name__)
        
        if task_id:
            logger.debug(f"TaskLogger initialized: task_id={task_id}, plugin={plugin_label}")
    
    def _send_to_stream(self, message: str, level: str = 'info'):
        """Send log message to SSE stream via django-eventstream"""
        if not self.task_id:
            return
        
        try:
            # Send event to task-specific channel
            send_event(
                f'task-{self.task_id}',  # Channel name
                'log',  # Event type
                {
                    'message': message,
                    'level': level,
                    'timestamp': datetime.now().isoformat(),
                    'task_id': self.task_id,
                }
            )
            
            logger.debug(f"Sent log to stream: task-{self.task_id}")
        except Exception as e:
            logger.debug(f"Could not send to event stream: {e}")
    
    def _format_message(self, message: str) -> str:
        """Add plugin label prefix if available"""
        if self.plugin_label:
            return f"[{self.plugin_label}] {message}"
        return message
    
    def _log(self, level: str, message: str, *args, **kwargs):
        """Internal method to log to both standard logger and stream"""
        formatted_msg = self._format_message(message)
        
        if args:
            formatted_msg = formatted_msg % args
        
        # Always log to standard logger
        log_method = getattr(self.standard_logger, level)
        log_method(formatted_msg, **kwargs)
        
        # Send to event stream
        self._send_to_stream(formatted_msg, level)
    
    def debug(self, message: str, *args, **kwargs):
        self._log('debug', message, *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        self._log('info', message, *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        self._log('warning', message, *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        self._log('error', message, *args, **kwargs)
    
    def success(self, message: str, *args, **kwargs):
        """Custom log level for successful operations"""
        formatted_msg = self._format_message(message)
        if args:
            formatted_msg = formatted_msg % args
        
        self.standard_logger.info(formatted_msg, **kwargs)
        self._send_to_stream(formatted_msg, 'success')
