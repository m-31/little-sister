from datetime import datetime
from enum import Enum, auto
from collections import OrderedDict
from typing import Union, List, OrderedDict, Self


class StatusCode(Enum):
    """These are the possible status codes."""
    MAINTENANCE = auto()
    OK = auto()
    WARN = auto()
    ERROR = auto()
    UNDEFINED = auto()


def is_valid_status_code(value: str) -> bool:
    return value.upper() in StatusCode.__members__


class Status:
    """Status class to represent the status of a component or system."""

    def __init__(self, path: str, name: str, code: Union[StatusCode, str] = StatusCode.UNDEFINED,
                 reason: Union[List[str], str] = None):
        self.path = path
        self.name = name
        if isinstance(code, str):
            if not is_valid_status_code(code):
                raise ValueError(f"Invalid status code: '{code}'")
            code = StatusCode[code.upper()]
        elif not isinstance(code, StatusCode):
            raise TypeError(
                f"Status code must be a StatusCode instance or a valid status code string, got {type(code).__name__} instead")

        self.code = code
        self.reason = [reason] if isinstance(reason, str) else (reason or [])
        self.timestamp = datetime.now().isoformat()
        self.__children = OrderedDict[str, Status]()

    def __str__(self):
        return f"{self.path}.{self.name}: {self.code.name.lower()}{' - ' + ', '.join(self.reason) if self.reason else ''}"

    def get_status_code(self) -> StatusCode:
        """Get the status code of the object. This also considers the status of child objects."""
        result = self.code
        if result not in ["maintenance", "error"]:
            for child in self.__children.values():
                child_code = child.get_status_code()
                if child_code == StatusCode.ERROR:
                    return StatusCode.ERROR
                if child_code == StatusCode.WARN:
                    result = "warn"
        return result

    def add_child(self, child: Self):
        """Add a child status to this status."""
        # TODO check if child is a Status instance and its path is self.path + '.' + self.name
        if not isinstance(child, Status):
            raise TypeError(f"Child must be an instance of Status, got {type(child).__name__} instead")

        expected_path = f"{self.path}.{self.name}"
        if child.path != expected_path:
            raise ValueError(f"Child's path must be '{expected_path}', got '{child.path}' instead")

        self.__children[child.name] = child

    def get_children(self) -> List['Status']:
        return list(self.__children.values())
