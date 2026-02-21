"""Apple docs extraction helpers for REPL sandbox use.

Load into the sandbox via rlm_load, then call functions to read
specific sections from exported Apple doc Markdown files without
pulling entire files into LLM context.

Usage from sandbox:
    from apple_extract import DocReader
    reader = DocReader("/path/to/DocSetQuery/docs/apple")

    # List all available frameworks
    reader.frameworks()

    # Get table of contents for a framework
    reader.toc("visionos")

    # Find sections matching a query across frameworks
    reader.find("immersive space", frameworks=["visionos", "swiftui"])

    # Find by role tag
    reader.find_by_role("Sample Code", frameworks=["visionos"])

    # Read a specific section with full code blocks
    reader.read_section("visionos", "Creating fully immersive experiences")

    # Extract all code blocks from a section
    reader.code_blocks("visionos", "Creating fully immersive experiences")

    # Cross-reference: find which frameworks mention a symbol
    reader.xref("ImmersiveSpace")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Section:
    """A parsed section from an exported Apple doc."""
    framework: str
    heading: str
    role: str
    depth: int
    line_number: int
    text: str
    path: str  # metadata path if present

    @property
    def has_code(self) -> bool:
        return "```" in self.text

    @property
    def code_blocks(self) -> list[str]:
        """Extract all fenced code blocks from this section."""
        blocks = []
        in_block = False
        current: list[str] = []
        for line in self.text.splitlines():
            if line.strip().startswith("```"):
                if in_block:
                    blocks.append("\n".join(current))
                    current = []
                    in_block = False
                else:
                    in_block = True
            elif in_block:
                current.append(line)
        return blocks

    def summary(self, max_chars: int = 200) -> str:
        # First non-heading, non-metadata line
        for line in self.text.splitlines():
            if line.startswith("#") or line.startswith("*") or not line.strip():
                continue
            text = line.strip()[:max_chars]
            return text
        return "(no summary)"


class DocReader:
    """Read and search exported Apple doc Markdown files."""

    def __init__(self, docs_dir: str | Path):
        self.docs_dir = Path(docs_dir)
        self._cache: dict[str, list[Section]] = {}

    def frameworks(self) -> list[dict[str, str]]:
        """List all available framework files with sizes."""
        results = []
        for f in sorted(self.docs_dir.glob("*.md")):
            if f.name == "READING_GUIDE.md":
                continue
            size = f.stat().st_size
            results.append({
                "name": f.stem,
                "file": f.name,
                "size": f"{size:,} bytes",
                "size_kb": f"{size // 1024}KB",
            })
        return results

    def toc(self, framework: str, max_depth: int = 3) -> list[dict]:
        """Get table of contents for a framework file."""
        sections = self._parse(framework)
        return [
            {
                "heading": s.heading,
                "role": s.role,
                "depth": s.depth,
                "line": s.line_number,
                "has_code": s.has_code,
            }
            for s in sections
            if s.depth <= max_depth
        ]

    def find(
        self,
        query: str,
        frameworks: list[str] | None = None,
        role: str | None = None,
        max_results: int = 20,
    ) -> list[dict]:
        """Find sections matching a query string across frameworks.

        Searches heading text and section content. Returns metadata
        without full text (use read_section for that).
        """
        query_lower = query.lower()
        results = []
        targets = frameworks or [f.stem for f in self.docs_dir.glob("*.md")]

        for fw in targets:
            try:
                sections = self._parse(fw)
            except FileNotFoundError:
                continue
            for s in sections:
                if role and s.role.lower() != role.lower():
                    continue
                # Score: heading match > content match
                heading_match = query_lower in s.heading.lower()
                content_match = query_lower in s.text[:2000].lower()
                if heading_match or content_match:
                    results.append({
                        "framework": fw,
                        "heading": s.heading,
                        "role": s.role,
                        "depth": s.depth,
                        "line": s.line_number,
                        "has_code": s.has_code,
                        "match": "heading" if heading_match else "content",
                        "summary": s.summary(),
                    })
                    if len(results) >= max_results:
                        return results
        return results

    def find_by_role(
        self,
        role: str,
        frameworks: list[str] | None = None,
    ) -> list[dict]:
        """Find all sections with a specific role tag.

        Common roles: "Class", "Protocol", "Structure", "Article",
        "Sample Code", "Instance Method", "Framework", "API Collection"
        """
        results = []
        targets = frameworks or [f.stem for f in self.docs_dir.glob("*.md")]
        for fw in targets:
            try:
                sections = self._parse(fw)
            except FileNotFoundError:
                continue
            for s in sections:
                if s.role.lower() == role.lower():
                    results.append({
                        "framework": fw,
                        "heading": s.heading,
                        "role": s.role,
                        "line": s.line_number,
                        "has_code": s.has_code,
                        "summary": s.summary(),
                    })
        return results

    def read_section(
        self,
        framework: str,
        heading_query: str,
        include_children: bool = True,
    ) -> str | None:
        """Read a specific section's full text, including code blocks.

        Args:
            framework: Framework name (e.g. "visionos")
            heading_query: Substring match on heading text
            include_children: If True, include subsections (default True)
        """
        sections = self._parse(framework)
        query_lower = heading_query.lower()

        for i, s in enumerate(sections):
            if query_lower not in s.heading.lower():
                continue

            if not include_children:
                return s.text

            # Collect this section + children (deeper headings)
            lines = [s.text]
            for j in range(i + 1, len(sections)):
                child = sections[j]
                if child.depth <= s.depth:
                    break
                lines.append(child.text)
            return "\n\n".join(lines)

        return None

    def code_blocks(
        self,
        framework: str,
        heading_query: str,
    ) -> list[dict]:
        """Extract just the code blocks from a section.

        Returns list of {language, code} dicts. Useful when you only
        need the Swift code examples, not the prose around them.
        """
        text = self.read_section(framework, heading_query)
        if not text:
            return []

        blocks = []
        in_block = False
        language = ""
        current: list[str] = []

        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("```"):
                if in_block:
                    blocks.append({
                        "language": language,
                        "code": "\n".join(current),
                    })
                    current = []
                    in_block = False
                else:
                    language = stripped[3:].strip() or "swift"
                    in_block = True
            elif in_block:
                current.append(line)

        return blocks

    def xref(self, symbol: str, max_results: int = 30) -> list[dict]:
        """Cross-reference: find which frameworks mention a symbol.

        Useful for discovering where an API is documented across
        multiple framework files.
        """
        results = []
        for f in sorted(self.docs_dir.glob("*.md")):
            if f.name == "READING_GUIDE.md":
                continue
            text = f.read_text(encoding="utf-8")
            if symbol not in text:
                continue
            # Find which headings contain the symbol
            headings = []
            for line in text.splitlines():
                if line.startswith("#") and symbol in line:
                    headings.append(line.lstrip("#").strip())
            results.append({
                "framework": f.stem,
                "mentions": text.count(symbol),
                "in_headings": headings[:5],
            })
            if len(results) >= max_results:
                break
        return results

    def _parse(self, framework: str) -> list[Section]:
        """Parse a framework file into sections. Cached per framework."""
        if framework in self._cache:
            return self._cache[framework]

        file_path = self.docs_dir / f"{framework}.md"
        if not file_path.exists():
            raise FileNotFoundError(f"No doc file for '{framework}' at {file_path}")

        text = file_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        sections: list[Section] = []
        current_heading = ""
        current_role = ""
        current_depth = 1
        current_start = 0
        current_path = ""
        current_lines: list[str] = []

        # Role tag pattern: "## Foo Bar (Class)" or "### baz() (Instance Method)"
        role_pattern = re.compile(r"^(#{1,6})\s+(.+?)\s*\(([^)]+)\)\s*$")
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
        path_pattern = re.compile(r"^\*Path:\*\s*`([^`]+)`")

        for i, line in enumerate(lines):
            heading_match = heading_pattern.match(line)
            if not heading_match:
                current_lines.append(line)
                # Check for path metadata
                pm = path_pattern.match(line)
                if pm:
                    current_path = pm.group(1)
                continue

            # Flush previous section
            if current_lines and current_heading:
                sections.append(Section(
                    framework=framework,
                    heading=current_heading,
                    role=current_role,
                    depth=current_depth,
                    line_number=current_start,
                    text="\n".join(current_lines).strip(),
                    path=current_path,
                ))

            # Parse new heading
            depth = len(heading_match.group(1))
            full_heading = heading_match.group(2).strip()

            role_match = role_pattern.match(line)
            if role_match:
                current_role = role_match.group(3)
                current_heading = role_match.group(2).strip()
            else:
                current_role = ""
                current_heading = full_heading

            current_depth = depth
            current_start = i + 1
            current_path = ""
            current_lines = [line]

        # Flush last section
        if current_lines and current_heading:
            sections.append(Section(
                framework=framework,
                heading=current_heading,
                role=current_role,
                depth=current_depth,
                line_number=current_start,
                text="\n".join(current_lines).strip(),
                path=current_path,
            ))

        self._cache[framework] = sections
        return sections
