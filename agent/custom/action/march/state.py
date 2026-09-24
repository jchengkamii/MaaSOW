"""March state independent of Maa and list row positions."""
from dataclasses import dataclass
from enum import StrEnum
import re


class MarchState(StrEnum):
    ASSEMBLING = "集结中"
    OUTBOUND = "前往"
    FIGHTING = "战斗中"
    RETURNING = "返回"
    COMPLETED = "结束"


def parse_status(text: str) -> MarchState | None:
    text = re.sub(r"\s+", "", text)
    # OCR over the translucent HUD can append map decoration (e.g. 战斗中##).
    # Accept only a short punctuation suffix, never timers, digits or other text.
    label = re.fullmatch(r"(集结中|战斗中|返回|出征)[.。…#＃·><＞＜]{0,6}", text)
    if label:
        return {"集结中": MarchState.ASSEMBLING, "战斗中": MarchState.FIGHTING,
                "返回": MarchState.RETURNING, "出征": MarchState.OUTBOUND}[label[1]]
    # Coordinates remain a strong outbound marker even when OCR merges a short
    # map label at the end or reads the colon as a dot/comma.
    if re.fullmatch(r"去[Xx][：:.,，。·]?-?\d+[Yy][：:.,，。·]?-?\d+[^\d\s:：]{0,3}", text):
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
