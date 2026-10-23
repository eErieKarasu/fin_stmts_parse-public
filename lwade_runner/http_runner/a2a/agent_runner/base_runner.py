# BaseRunner
from abc import ABC, abstractmethod

from a2a.types import Message


class BaseRunner(ABC):
    """Base class for agent runner"""

    @abstractmethod
    def stream(self, message: Message, context_id: str, task_id: str):
        ...

    def convert_a2a_message(self, *args, **kwargs):
        ...

    def convert_runner_message(self, *args, **kwargs):
        ...