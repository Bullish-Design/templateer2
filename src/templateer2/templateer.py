#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pydantic>=2.0.0",
#     "jinja2>=3.0.0",
# ]
# ///

"""
Simple Template Renderer using Pydantic and Jinja2.

This script loads a template file containing:
1. Python code section: Pydantic models
2. Template section: Configuration and Jinja template

It renders the template using the Pydantic models and writes the output to a file.

Usage:
    uv run simplified_templateer.py --template=<template_file> --output=<output_dir>
"""

from __future__ import annotations
import argparse
import importlib.util
import inspect
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any

import jinja2
from pydantic import BaseModel, Field


class TemplateConfig(BaseModel):
    """Configuration extracted from the template header section."""

    output_file: Optional[str] = None
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class TemplateFile:
    """Represents a parsed template file."""

    def __init__(
        self,
        path: Path,
        python_code: str,
        template_content: str,
        config: TemplateConfig,
    ):
        self.path = path
        self.python_code = python_code
        self.template_content = template_content
        self.config = config

    @classmethod
    def from_file(cls, file_path: Path) -> TemplateFile:
        """Load and parse a template file."""
        if not file_path.exists():
            raise FileNotFoundError(f"Template file not found: {file_path}")

        content = file_path.read_text()

        # Look for template section marker
        template_pattern = r"#\s*///\s*template\s*\n(.*?)#\s*///"
        template_match = re.search(template_pattern, content, re.DOTALL)

        if not template_match:
            raise ValueError(
                f"Could not find template section marker '# /// template' in {file_path}"
            )

        # Extract the template configuration
        template_config_raw = template_match.group(1).strip()
        config_dict = cls._parse_template_config(template_config_raw)
        config = TemplateConfig(
            output_file=config_dict.pop("output-file", None), extra_params=config_dict
        )

        # Everything before the template section is Python code
        python_code = content[: template_match.start()].strip()

        # Everything after the template section close marker is the Jinja template
        template_content = content[template_match.end() :].strip().strip('"""').strip()

        return cls(file_path, python_code, template_content, config)

    @staticmethod
    def _parse_template_config(config_text: str) -> Dict[str, Any]:
        """Parse the template configuration section."""
        config = {}

        # Process line by line
        for line in config_text.split("\n"):
            line = line.strip().strip("#").strip()
            if not line:
                continue

            # Check for key-value pairs
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]

                # Handle list values (e.g., imports = ["file1.py", "file2.py"])
                if value.startswith("[") and value.endswith("]"):
                    try:
                        # Try to parse as JSON array
                        list_value = json.loads(value)
                        config[key] = list_value
                    except json.JSONDecodeError:
                        # Fallback: simple string splitting
                        items = value[1:-1].split(",")
                        config[key] = [
                            item.strip().strip("\"'") for item in items if item.strip()
                        ]
                else:
                    config[key] = value

        return config


class PydanticModuleLoader:
    """Loads a Python module and extracts Pydantic classes."""

    @staticmethod
    def load(python_code: str) -> Dict[str, Any]:
        """Load Python code as a module and extract Pydantic classes."""
        module = PydanticModuleLoader._load_as_module(python_code)
        classes = PydanticModuleLoader._extract_pydantic_classes(module)

        return {"module": module, "classes": classes}

    @staticmethod
    def _load_as_module(python_code: str) -> Any:
        """Load Python code string as a module."""
        # Generate a unique module name
        module_name = f"pydantic_module_{id(python_code)}"

        # Create a temporary file
        temp_file = Path(tempfile.gettempdir()) / f"{module_name}.py"
        try:
            temp_file.write_text(python_code)

            # Import the module
            spec = importlib.util.spec_from_file_location(module_name, temp_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not create module spec for {temp_file}")

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            return module
        finally:
            # Clean up
            if temp_file.exists():
                temp_file.unlink()

    @staticmethod
    def _extract_pydantic_classes(module: Any) -> Dict[str, Dict[str, Any]]:
        """Extract Pydantic classes from a module."""
        # from pydantic import BaseModel as PydanticBase

        classes = {}

        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj != BaseModel:
                # Get docstring
                doc = inspect.getdoc(obj) or ""

                # Get fields based on Pydantic version
                if hasattr(obj, "model_fields"):
                    fields = obj.model_fields
                else:
                    fields = {}

                classes[name] = {"cls": obj, "doc": doc, "fields": fields}

        return classes


class TemplateRenderer:
    """Renders Jinja templates with Pydantic models."""

    def __init__(self):
        """Initialize the template renderer."""
        self.env = jinja2.Environment()
        self._register_filters()

    def _register_filters(self):
        """Register custom filters for the Jinja environment."""

        # Schema JSON filter
        def schema_json_filter(model):
            if hasattr(model, "model_json_schema"):
                schema = model.model_json_schema()
                return json.dumps(schema, indent=2)
            return "Schema not available"

        # New regex_replace filter using Python's re.sub
        def regex_replace(value, pattern, replacement):
            return re.sub(pattern, replacement, value)

        # Register filters
        self.env.filters["schema_json"] = schema_json_filter
        self.env.filters["regex_replace"] = regex_replace

    def render(self, template_file: TemplateFile, module_info: Dict[str, Any]) -> str:
        """Render a template with Pydantic classes."""
        template = self.env.from_string(template_file.template_content)

        # Build context
        context = self._build_context(template_file, module_info)

        # Render template
        return template.render(**context)

    def _build_context(
        self, template_file: TemplateFile, module_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build the context dictionary for template rendering."""
        # Basic context with module info
        context = {
            "module": module_info["module"],
            "config": template_file.config,
            "pydantic_docs": {
                name: info["doc"] for name, info in module_info["classes"].items()
            },
            "pydantic_fields": {
                name: info["fields"] for name, info in module_info["classes"].items()
            },
            "get_schema_json": self.env.filters["schema_json"],
        }

        # Add each Pydantic class to the context
        for name, info in module_info["classes"].items():
            context[name] = info["cls"]

        # Add standard library modules
        context["datetime"] = __import__("datetime")
        context["typing"] = __import__("typing")
        context["pydantic"] = __import__("pydantic")
        context["json"] = __import__("json")

        return context


def process_template(template_path: Path, output_dir: Path) -> Path:
    """Process a template file and generate output."""
    # Parse template file
    template_file = TemplateFile.from_file(template_path)

    # Load Python module and extract Pydantic classes
    module_info = PydanticModuleLoader.load(template_file.python_code)

    if not module_info["classes"]:
        raise ValueError("No Pydantic classes found in the template file")

    print(f"Found Pydantic classes: {', '.join(module_info['classes'].keys())}")

    # Render template
    renderer = TemplateRenderer()
    rendered_content = renderer.render(template_file, module_info)

    # Determine output filename
    output_filename = template_file.config.output_file or template_path.stem + ".md"

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write output file
    output_path = output_dir / output_filename
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
        process_template(args.template, args.output)
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
