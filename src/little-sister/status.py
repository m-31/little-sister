from datetime import datetime
from enum import Enum, auto
from collections import OrderedDict
from typing import Union, List, OrderedDict


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
    """"""

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
        self.children = OrderedDict[str, Status]

    def __str__(self):
        return f"{self.path}.{self.name}: {self.code.name.lower()}{' - ' + ', '.join(self.reason) if self.reason else ''}"

    def get_status_code(self) -> str:
        result = self.code
        if result not in ["maintenance", "error"]:
            for child in self.children.values():
                child_code = child.get_status_code()
                if child_code == "error":
                    return "error"
                if child_code == "warn":
                    result = "warn"
        return result


if __name__ == "__main__":
    status = Status("src.little-sister", "status", StatusCode.OK)
    print(status)
    status = Status("src.little-sister", "status", StatusCode.ERROR, "Something went wrong")
    print(status)
    status = Status("src.little-sister", "status", StatusCode.WARN,
                    ["Something went wrong", "Something else went wrong"])
    print(status)
    status = Status("src.little-sister", "status", StatusCode.MAINTENANCE)
    print(status)
    status = Status("src.little-sister", "status")
    print(status)
    try:
        status = Status("src.little-sister", "status", "invalid")
        print(status)
    except ValueError as e:
        print(e)
    try:
        status = Status("src.little-sister.status", "ok", "Something went wrong")
        print(status)
    except ValueError as e:
        print(e)
    try:
        status = Status("src.little-sister.status", "ok", ["Something went wrong", "Something else went wrong"])
        print(status)
    except TypeError as e:
        print(e)
