"""March state independent of Maa and list row positions."""
from dataclasses import dataclass
from enum import StrEnum
import re


class MarchState(StrEnum):
    OUTBOUND = "前往"
    FIGHTING = "战斗中"
    RETURNING = "返回"
    COMPLETED = "结束"


def parse_status(text: str) -> MarchState | None:
    text = re.sub(r"\s+", "", text)
    if text == "返回":
        return MarchState.RETURNING
    if text == "战斗中":
        return MarchState.FIGHTING
    if re.fullmatch(r"去[Xx][：:]?-?\d+[Yy][：:]?-?\d+", text):
        return MarchState.OUTBOUND
    return None


@dataclass
class MarchTracker:
    confirmations: int = 3
    state: MarchState | None = None
    missing: int = 0

    def observe(self, *, visible: bool, status: MarchState | None,
                reliable: bool, count_decreased: bool = False) -> bool:
        if not reliable:
            self.missing = 0
            return False
        if visible:
            self.missing = 0
            # An unreadable status must not erase an observed returning state.
            if status is not None:
                self.state = status
            return False
        if self.state == MarchState.RETURNING and count_decreased:
            self.missing += 1
            if self.missing >= self.confirmations:
                self.state = MarchState.COMPLETED
                return True
        else:
            self.missing = 0
        return False
