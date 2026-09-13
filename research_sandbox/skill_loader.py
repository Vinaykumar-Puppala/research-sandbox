import importlib.util
import os
import sys
from pathlib import Path
from typing import List

from langchain_core.tools import BaseTool

SKILLS_DIR = Path(os.getenv("SKILLS_DIR", Path(__file__).parent / "skills"))


def load_skill_tools() -> List[BaseTool]:
    """Scan skills/*.py, import each module, collect every BaseTool instance found.

    Files whose names start with '_' are skipped (used for examples/drafts).
    A broken skill file is logged to stderr and skipped — it never crashes the app.
    """
    tools: List[BaseTool] = []
    if not SKILLS_DIR.exists():
        return tools

    for py_file in sorted(SKILLS_DIR.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"_skill_{py_file.stem}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            for attr in dir(module):
                obj = getattr(module, attr)
                if isinstance(obj, BaseTool):
                    tools.append(obj)
        except Exception as exc:
            print(f"[skill_loader] skipping {py_file.name}: {exc}", file=sys.stderr)

    return tools


def load_skill_prompts() -> str:
    """Scan skills/*.md (excluding README.md and _*.md), return joined content.

    Each file's content is prefixed with a heading so the model knows which
    instruction set it came from.
    """
    if not SKILLS_DIR.exists():
        return ""

    parts = []
    for md_file in sorted(SKILLS_DIR.glob("*.md")):
        if md_file.name.startswith("_") or md_file.name.lower() == "readme.md":
            continue
        content = md_file.read_text(encoding="utf-8").strip()
        if content:
            parts.append(f"### Skill instructions: {md_file.stem}\n{content}")

    return "\n\n".join(parts)


def count_active() -> tuple[int, int]:
    """Return (n_tools, n_prompts) currently active in the skills folder."""
    return len(load_skill_tools()), len([
        f for f in SKILLS_DIR.glob("*.md")
        if not f.name.startswith("_") and f.name.lower() != "readme.md"
    ]) if SKILLS_DIR.exists() else 0
