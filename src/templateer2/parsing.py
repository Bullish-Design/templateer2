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


class TemplateConfig(BaseModel):
    """Configuration extracted from the template header section."""

    output_file: Optional[str] = None
    imports: List[str] = Field(default_factory=list)
    reference_file: Optional[Path] = None
    extra_params: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    @classmethod
    def from_raw_config(cls, config_dict: Dict[str, Any]) -> TemplateConfig:
        """Create a TemplateConfig instance from raw parsed config."""
        # Extract known fields
        output_file = config_dict.pop("output-file", None)
        imports = config_dict.pop("imports", [])
        reference_file = config_dict.pop("reference-file", None)

        # Convert reference file to Path if specified
        if reference_file:
            reference_file = Path(reference_file)
            logger.info(f"    Reference file: {reference_file}")

        # Create the instance with remaining fields as extra_params
        return cls(
            output_file=output_file,
            imports=imports,
            reference_file=reference_file,
            extra_params=config_dict,
        )


class PydanticClassInfo(BaseModel):
    """Information about a Pydantic class."""

    cls: Any
    doc: str = ""
    fields: Dict[str, Any] = Field(default_factory=dict)
    # TODO: Investigate pydantic merge_field_infos() for field info

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PydanticModuleInfo(BaseModel):
    """Information about a Python module with Pydantic classes."""

    module: Any
    classes: Dict[str, PydanticClassInfo] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def has_classes(self) -> bool:
        """Check if any Pydantic classes were found."""
        return bool(self.classes)

    def get_class_names(self) -> List[str]:
        """Get a list of all Pydantic class names."""
        return list(self.classes.keys())


class TemplateFile(BaseModel):
    """Represents a parsed template file."""

    path: Path
    python_code: str = ""
    template_content: str = ""
    config: TemplateConfig = Field(default_factory=TemplateConfig)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @classmethod
    def from_file(cls, file_path: Path) -> TemplateFile:
        """Load and parse a template file."""
        if not file_path.exists():
            raise FileNotFoundError(f"Template file not found: {file_path}")

        content = file_path.read_text()

        # Extract UV script section (skip it for processing)
        uv_script_pattern = r"#\s*///\s*script\s*\n(.*?)#\s*///"
        uv_match = re.search(uv_script_pattern, content, re.DOTALL)
        if uv_match:
            # Remove the uv script section for further processing
            content = content.replace(uv_match.group(0), "").strip()

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
        config = TemplateConfig.from_raw_config(config_dict)

        # Everything before the template section is Python code
        python_code = content[: template_match.start()].strip()

        # Everything after the template section close marker is the Jinja template
        template_content = content[template_match.end() :].strip().strip('"""').strip()

        return cls(
            path=file_path,
            python_code=python_code,
            template_content=template_content,
            config=config,
        )

    @staticmethod
    def _parse_template_config(config_text: str) -> Dict[str, Any]:
        """Parse the template configuration section."""
        config = {}
        logger.info(f"Parsing template config:")
        # Process line by line
        for line in config_text.split("\n"):
            line = line.strip().strip("#").strip()
            logger.info(f"    Line: {line}")
            if not line:  # or line.startswith("#"):
                logger.info(f"        No config val, skipping")
                continue

            # Check for key-value pairs
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                # logger.info(f"        Config key: {key:>20} => {value}")

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
                logger.info(f"        Config key: {key:>20} => {value}")

        return config


class PydanticModuleLoader:
    """Loads a Python module and extracts Pydantic classes."""

    @staticmethod
    def load(python_code: str) -> PydanticModuleInfo:
        """Load Python code as a module and extract Pydantic classes."""
        module = PydanticModuleLoader._load_as_module(python_code)
        classes = PydanticModuleLoader._extract_pydantic_classes(module)

        return PydanticModuleInfo(module=module, classes=classes)

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
    def _extract_pydantic_classes(module: Any) -> Dict[str, PydanticClassInfo]:
        """Extract Pydantic classes from a module."""
        from pydantic import BaseModel as PydanticBase

        classes = {}

        for name, obj in inspect.getmembers(module):
            if (
                inspect.isclass(obj)
                and issubclass(obj, PydanticBase)
                and obj != PydanticBase
            ):
                # Get docstring
                doc = inspect.getdoc(obj) or ""

                # Get fields based on Pydantic version
                if hasattr(obj, "model_fields"):
                    fields = obj.model_fields
                else:
                    fields = {}

                classes[name] = PydanticClassInfo(cls=obj, doc=doc, fields=fields)

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

    def render(
        self, template_file: TemplateFile, module_info: PydanticModuleInfo
    ) -> str:
        """Render a template with Pydantic classes."""
        template = self.env.from_string(template_file.template_content)

        # Build context
        context = self._build_context(template_file, module_info)

        # Render template
        return template.render(**context)

    def _build_context(
        self, template_file: TemplateFile, module_info: PydanticModuleInfo
    ) -> Dict[str, Any]:
        """Build the context dictionary for template rendering."""
        # Basic context with module info
        context = {
            "module": module_info.module,
            "config": template_file.config,
            "pydantic_docs": {
                name: info.doc for name, info in module_info.classes.items()
            },
            "pydantic_fields": {
                name: info.fields for name, info in module_info.classes.items()
            },
            "get_schema_json": self.env.filters["schema_json"],
        }

        # Add each Pydantic class to the context
        for name, info in module_info.classes.items():
            context[name] = info.cls

        # Add standard library modules
        context["datetime"] = __import__("datetime")
        context["typing"] = __import__("typing")
        context["pydantic"] = __import__("pydantic")
        context["json"] = __import__("json")

        return context
