from datetime import datetime
from enum import Enum
from typing import Union, List, OrderedDict

class StatusCode(Enum):
    """"""
    MAINTENANCE = "maintenance"
    OK = "ok"
    WARN = "warn"
    ERROR = "error"
    UNDEFINED = "undefined"

class Status:
    """"""

    def __init__(self, path: str, code: StatusCode = StatusCode.UNDEFINED, reason: Union[List[str], str] = None):
        self.name = path.split(".")[-1]
        self.path = path
        self.code = code
        self.reason = [reason] if isinstance(reason, str) else (reason or [])
        self.timestamp = datetime.now().isoformat()
        self.children = OrderedDict[Status]

    def __str__(self):
        return f"{self.path}: {self.code}{' - ' + ', '.join(self.reason) if self.reason else ''}"

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
    status = Status("src.little-sister.status", StatusCode.OK)
    print(status)
    status = Status("src.little-sister.status", StatusCode.ERROR, "Something went wrong")
    print(status)
    status = Status("src.little-sister.status", StatusCode.WARN, ["Something went wrong", "Something else went wrong"])
    print(status)
    status = Status("src.little-sister.status", StatusCode.MAINTENANCE)
    print(status)
    status = Status("src.little-sister.status")
    print(status)
    try:
        status = Status("src.little-sister.status", "invalid")
    except ValueError as e:
        print(e)
    try:
        status = Status("src.little-sister.status", "ok", "Something went wrong")
    except ValueError as e:
        print(e)
    try:
        status = Status("src.little-sister.status", "ok", ["Something went wrong", "Something else went wrong"])
    except ValueError as e:
        print(e)
