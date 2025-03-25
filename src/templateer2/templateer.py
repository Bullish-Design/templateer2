#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pydantic>=2.0.0",
#     "jinja2>=3.0.0",
#     "templateer2 @ file:///${PROJECT_ROOT}/",
# ]
# ///

"""
Simple Template Renderer using Pydantic and Jinja2.

This script loads a template file containing:
1. UV script section: Python dependencies
2. Python code section: Pydantic models
3. Template section: Configuration and Jinja template

It renders the template using the Pydantic class and writes the output to a file.

Usage:
    uv run template_renderer.py --template=<template_file> --output=<output_dir>
"""

from __future__ import annotations
import argparse
import importlib.util
import inspect
import json
import re
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Dict, List, Optional, Any, ClassVar, Type

import jinja2
from pydantic import BaseModel, Field, ConfigDict
from templateer2._internal.logger import logger

# TODO: Create standard logger script for these uv scripts. Import, log to subdirectory of the directory the script was called in.
from templateer2.parsing import (
    TemplateConfig,
    PydanticClassInfo,
    PydanticModuleInfo,
    TemplateFile,
    PydanticModuleLoader,
    TemplateRenderer,
)


class TemplateProcessor:
    """Processes a template file and generates output."""

    def __init__(self, template_path: Path, output_dir: Path):
        """Initialize the template processor."""
        self.template_path = template_path
        self.output_dir = output_dir
        self.renderer = TemplateRenderer()

    def process(self) -> Path:
        """Process the template and return the output file path."""
        # Parse template file
        template_file = TemplateFile.from_file(self.template_path)

        # Load Python module and extract Pydantic classes
        module_info = PydanticModuleLoader.load(template_file.python_code)

        if not module_info.has_classes():
            raise ValueError("No Pydantic classes found in the template file")

        print(f"Found Pydantic classes: {', '.join(module_info.get_class_names())}")

        # Render template
        rendered_content = self.renderer.render(template_file, module_info)

        # Determine output filename
        output_filename = (
            template_file.config.output_file or self.template_path.stem + ".md"
        )

        # Create output directory
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Write output file
        output_path = self.output_dir / output_filename
        output_path.write_text(rendered_content)

        print(f"Template rendered successfully to {output_path}")
        return output_path


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Render a template using Pydantic models."
    )
    parser.add_argument(
        "--template", required=True, type=Path, help="Path to the template file"
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Path to the output directory"
    )
    return parser.parse_args()


def main():
    """Main function."""
    args = parse_args()

    try:
        processor = TemplateProcessor(args.template, args.output)
        processor.process()
        return 0
    except Exception as e:
        print(f"Error: {e}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""
Example template file format:

#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pydantic>=2.0.0",
#     "jinja2>=3.0.0",
# ]
# ///

from pydantic import BaseModel, Field
from typing import List, Optional

class Person(BaseModel):
    '''Represents a person with personal information.'''
    name: str
    age: int
    email: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

# /// template
# output-file = "person_schema.md"
# imports = ["helpers.py"]
# reference-file = "./data/sample.json"
# ///

# Person Schema Documentation

## Class: Person

{{ pydantic_docs["Person"] }}

### Fields:

{% for field_name, field in pydantic_fields["Person"].items() %}
- **{{ field_name }}**: {{ field }}
{% endfor %}

### Schema:

```json
{{ get_schema_json(Person) }}
```
"""
