#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "pydantic>=2.0.0",
#     "jinja2>=3.0.0",
#     "mcp>=1.2.0",
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
import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Dict, List, Optional, Any, ClassVar, Type, Callable, Awaitable

import jinja2
from pydantic import BaseModel, Field, ConfigDict
from templateer2._internal.logger import logger

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

# TODO: Create standard logger script for these uv scripts. Import, log to subdirectory of the directory the script was called in.
from templateer2.parsing import (
    # TemplateConfig,
    PydanticClassInfo,
    PydanticModuleInfo,
    # TemplateFile,
    PydanticModuleLoader,
    # TemplateRenderer,
)


class McpServerConfig(BaseModel):
    """Configuration for an MCP server."""

    command: str
    args: List[str] = Field(default_factory=list)
    env: Optional[Dict[str, str]] = None


class TemplateConfig(BaseModel):
    """Configuration extracted from the template header section."""

    output_file: Optional[str] = None
    imports: List[str] = Field(default_factory=list)
    reference_file: Optional[Path] = None

    # MCP specific options
    mcp_servers: Dict[str, McpServerConfig] = Field(default_factory=dict)
    mcp_tools: List[str] = Field(default_factory=list)
    mcp_resources: List[str] = Field(default_factory=list)

    extra_params: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    @classmethod
    def from_raw_config(
        cls, config_dict: Dict[str, Any], base_dir: Optional[Path] = None
    ) -> TemplateConfig:
        """Create a TemplateConfig instance from raw parsed config."""
        # Extract known fields
        output_file = config_dict.pop("output-file", None)
        imports = config_dict.pop("imports", [])
        reference_file = config_dict.pop("reference-file", None)

        # Extract MCP-specific fields
        mcp_servers = {}

        # Handle mcp-servers configuration
        if "mcp-servers" in config_dict:
            servers_config_value = config_dict.pop("mcp-servers")

            # Check if it's a path to a JSON file
            if isinstance(servers_config_value, str) and (
                servers_config_value.endswith(".json")
                or servers_config_value.startswith("file:")
            ):
                # Extract file path, handling 'file:' prefix if present
                if servers_config_value.startswith("file:"):
                    file_path = servers_config_value[5:]
                else:
                    file_path = servers_config_value

                # Resolve path relative to base directory if provided
                if base_dir is not None:
                    file_path = base_dir / file_path

                try:
                    # Load server config from JSON file
                    with open(file_path, "r") as f:
                        servers_config = json.load(f)
                    print(f"Loaded MCP server config from file: {file_path}")

                    for server_name, server_config in servers_config.items():
                        mcp_servers[server_name] = McpServerConfig(**server_config)
                except (FileNotFoundError, json.JSONDecodeError, TypeError) as e:
                    print(f"Error loading MCP server config from file {file_path}: {e}")
            else:
                # Parse inline JSON configuration
                try:
                    servers_config = json.loads(servers_config_value)
                    for server_name, server_config in servers_config.items():
                        mcp_servers[server_name] = McpServerConfig(**server_config)
                except (json.JSONDecodeError, TypeError) as e:
                    print(f"Error parsing inline mcp-servers config: {e}")

        mcp_tools = config_dict.pop("mcp-tools", [])
        mcp_resources = config_dict.pop("mcp-resources", [])

        # Convert reference file to Path if specified
        if reference_file:
            reference_file = Path(reference_file)
            # Resolve relative to base directory if provided
            if base_dir is not None:
                reference_file = base_dir / reference_file
            print(f"    Reference file: {reference_file}")

        # Create the instance with remaining fields as extra_params
        return cls(
            output_file=output_file,
            imports=imports,
            reference_file=reference_file,
            mcp_servers=mcp_servers,
            mcp_tools=mcp_tools,
            mcp_resources=mcp_resources,
            extra_params=config_dict,
        )


class McpClientManager:
    """Manages MCP client connections for a template."""

    def __init__(self, config: TemplateConfig):
        """Initialize the MCP client manager with template config."""
        self.config = config
        self.exit_stack = AsyncExitStack()
        self.sessions: Dict[str, ClientSession] = {}
        self.server_tools: Dict[str, List[Any]] = {}
        self.server_resources: Dict[str, List[Any]] = {}

    async def initialize(self):
        """Initialize all configured MCP server connections."""
        for server_name, server_config in self.config.mcp_servers.items():
            try:
                params = StdioServerParameters(
                    command=server_config.command,
                    args=server_config.args,
                    env=server_config.env,
                )

                stdio_transport = await self.exit_stack.enter_async_context(
                    stdio_client(params)
                )
                session = await self.exit_stack.enter_async_context(
                    ClientSession(stdio_transport[0], stdio_transport[1])
                )

                await session.initialize()
                self.sessions[server_name] = session

                # Fetch tools and resources
                tools_result = await session.list_tools()
                self.server_tools[server_name] = tools_result.tools

                resources_result = await session.list_resources()
                self.server_resources[server_name] = resources_result.resources

                print(f"Connected to MCP server: {server_name}")
                print(f"  Available tools: {len(self.server_tools[server_name])}")
                print(
                    f"  Available resources: {len(self.server_resources[server_name])}"
                )

            except Exception as e:
                print(f"Error connecting to MCP server {server_name}: {e}")

    async def call_tool(
        self, server_name: str, tool_name: str, arguments: Dict[str, Any]
    ) -> Any:
        """Call a tool on an MCP server."""
        if server_name not in self.sessions:
            print(
                f"Warning: MCP server '{server_name}' is not connected, returning placeholder response"
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"[Tool execution failed: MCP server '{server_name}' is not connected]",
                    }
                ]
            }

        try:
            session = self.sessions[server_name]
            result = await session.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            print(f"Error calling tool {tool_name} on MCP server {server_name}: {e}")
            return {
                "content": [
                    {"type": "text", "text": f"[Tool execution error: {str(e)}]"}
                ]
            }

    async def read_resource(self, server_name: str, resource_uri: str) -> Any:
        """Read a resource from an MCP server."""
        if server_name not in self.sessions:
            print(
                f"Warning: MCP server '{server_name}' is not connected, returning placeholder response"
            )
            return {
                "contents": [
                    {
                        "type": "text",
                        "text": f"[Resource read failed: MCP server '{server_name}' is not connected]",
                    }
                ]
            }

        try:
            session = self.sessions[server_name]
            result = await session.read_resource(resource_uri)
            return result
        except Exception as e:
            print(
                f"Error reading resource {resource_uri} from MCP server {server_name}: {e}"
            )
            return {
                "contents": [
                    {"type": "text", "text": f"[Resource read error: {str(e)}]"}
                ]
            }

    async def close(self):
        """Close all MCP client sessions."""
        await self.exit_stack.aclose()


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
        self,
        template_file: TemplateFile,
        module_info: PydanticModuleInfo,
        context_extension: Dict[str, Any] = None,
    ) -> str:
        """Render a template with Pydantic classes and optional custom context."""
        template = self.env.from_string(template_file.template_content)

        # Build context
        context = self._build_context(template_file, module_info)

        # Add custom context extensions
        if context_extension:
            context.update(context_extension)

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
        config_dict = cls._parse_template_config(template_config_raw, file_path.parent)
        config = TemplateConfig.from_raw_config(config_dict, file_path.parent)

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
    def _parse_template_config(config_text: str, base_dir: Path) -> Dict[str, Any]:
        """Parse the template configuration section."""
        config = {}
        print(f"Parsing template config:")
        # Process line by line
        for line in config_text.split("\n"):
            line = line.strip().strip("#").strip()
            print(f"    Line: {line}")
            if not line:  # or line.startswith("#"):
                print(f"        No config val, skipping")
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
                print(f"        Config key: {key:>20} => {value}")

        return config


class TemplateProcessor:
    """Processes a template file and generates output."""

    def __init__(self, template_path: Path, output_dir: Path):
        """Initialize the template processor."""
        self.template_path = template_path
        self.output_dir = output_dir
        self.renderer = TemplateRenderer()
        self.mcp_manager = None

    async def async_process(self) -> Path:
        """Process the template asynchronously and return the output file path."""
        # Parse template file
        template_file = TemplateFile.from_file(self.template_path)

        # Initialize MCP if server configurations are present
        self.mcp_manager = None
        if template_file.config.mcp_servers:
            try:
                self.mcp_manager = McpClientManager(template_file.config)
                await self.mcp_manager.initialize()
            except Exception as e:
                print(f"Warning: Failed to initialize MCP client manager: {e}")
                print(f"Template will be rendered without MCP integration")

        try:
            # Load Python module and extract Pydantic classes
            module_info = PydanticModuleLoader.load(template_file.python_code)

            if not module_info.has_classes():
                raise ValueError("No Pydantic classes found in the template file")

            print(f"Found Pydantic classes: {', '.join(module_info.get_class_names())}")

            # Initialize empty MCP context variables that will always be available
            context_extension = {
                "mcp_tools": {},
                "mcp_resources": {},
                "mcp_call_tool": lambda server, tool, args: {
                    "content": [
                        {"type": "text", "text": f"MCP server '{server}' not connected"}
                    ]
                },
                "mcp_read_resource": lambda server, uri: {
                    "contents": [
                        {"type": "text", "text": f"MCP server '{server}' not connected"}
                    ]
                },
            }

            # Update with actual MCP context if available
            if self.mcp_manager and hasattr(self.mcp_manager, "sessions"):
                # Define safe wrapper functions for error handling
                def safe_call_tool(server, tool, args):
                    try:
                        return asyncio.run(
                            self.mcp_manager.call_tool(server, tool, args)
                        )
                    except Exception as e:
                        print(f"Error calling tool {tool} on server {server}: {e}")
                        return {
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"[Tool execution error: {str(e)}]",
                                }
                            ]
                        }

                def safe_read_resource(server, uri):
                    try:
                        return asyncio.run(self.mcp_manager.read_resource(server, uri))
                    except Exception as e:
                        print(f"Error reading resource {uri} from server {server}: {e}")
                        return {
                            "contents": [
                                {
                                    "type": "text",
                                    "text": f"[Resource read error: {str(e)}]",
                                }
                            ]
                        }

                context_extension.update(
                    {
                        "mcp_tools": self.mcp_manager.server_tools,
                        "mcp_resources": self.mcp_manager.server_resources,
                        "mcp_call_tool": safe_call_tool,
                        "mcp_read_resource": safe_read_resource,
                    }
                )

            rendered_content = self.renderer.render(
                template_file, module_info, context_extension
            )

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
        finally:
            # Close MCP connections
            if self.mcp_manager:
                await self.mcp_manager.close()

    def process(self) -> Path:
        """Synchronous wrapper for async_process."""
        return asyncio.run(self.async_process())


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Render a template using Pydantic models with MCP integration."
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
