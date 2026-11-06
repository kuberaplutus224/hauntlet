"""A deliberately gullible agent: it obeys any instruction it reads."""

from __future__ import annotations

import re

from hauntlet.agents._task import add_docstrings
from hauntlet.core.room import RoomMaterials, Transcript, TranscriptEntry
from hauntlet.core.toolbox import ToolBox

_URL = re.compile(r"https?://\S+")
_ENV_REF = re.compile(r"<value of ([A-Z0-9_]+)>")
_CREATE = re.compile(r'create the file (\S+) containing "([^"]+)"', re.IGNORECASE)
_REPEAT = re.compile(r'repeat the phrase "([^"]+)"', re.IGNORECASE)


class NaiveAgent:
    name = "naive"

    def run(self, materials: RoomMaterials, tools: ToolBox) -> Transcript:
        transcript: Transcript = [TranscriptEntry("user", materials.task)]
        to_repeat: list[str] = []

        for rel in tools.list_files():
            text = tools.read_file(rel)
            transcript.append(TranscriptEntry("tool", f"read {rel}"))
            flat = " ".join(text.split())
            # Fill in "<value of NAME>" from the environment, as asked.
            flat = _ENV_REF.sub(lambda m: tools.getenv(m.group(1)) or "", flat)
            for raw in _URL.findall(flat):
                url = raw.rstrip(".,;")
                try:
                    tools.fetch(url)
                    transcript.append(TranscriptEntry("tool", f"fetched {url}"))
                except (PermissionError, LookupError) as exc:
                    transcript.append(TranscriptEntry("tool", f"fetch failed: {exc}"))
            for name, content in _CREATE.findall(flat):
                tools.write_file(name, content + "\n")
                transcript.append(TranscriptEntry("tool", f"wrote {name}"))
            to_repeat += _REPEAT.findall(flat)

        summary = add_docstrings(tools)
        if to_repeat:
            summary += " As requested: " + "; ".join(to_repeat)
        transcript.append(TranscriptEntry("assistant", summary))
        return transcript
