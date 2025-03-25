from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class WeatherData(BaseModel):
    """Represents weather data for a location."""

    location: str
    temperature: float
    conditions: str
    forecast: List[str] = Field(default_factory=list)
    alerts: Optional[List[str]] = None


class DataAnalysisRequest(BaseModel):
    """Request for data analysis of weather information."""

    locations: List[str]
    metrics: List[str]
    time_range: str
    additional_filters: Dict[str, Any] = Field(default_factory=dict)


# /// template
# output-file = "weather_report_external_config.md"
# mcp-servers = file:./mcp_servers.json
# mcp-tools = ["get-forecast", "get-alerts"]
# mcp-resources = ["weather://{location}"]
# ///
"""
# Weather Analysis Report with External MCP Config

## Weather Data Model

{{ pydantic_docs["WeatherData"] }}

### Weather Data Schema:
```json
{{ get_schema_json(WeatherData) }}
```

## Analysis Request Model

{{ pydantic_docs["DataAnalysisRequest"] }}

### Analysis Request Schema:
```json
{{ get_schema_json(DataAnalysisRequest) }}
```

## Available MCP Servers

{% for server_name, tools in mcp_tools.items() %}
### {{ server_name }} Server

Available tools:
{% for tool in tools %}
- **{{ tool.name }}**: {{ tool.description or "No description available" }}
{% endfor %}

{% endfor %}

## Weather Data

{% set locations = ["New York", "San Francisco", "Chicago"] %}
{% for location in locations %}
### {{ location }}

{% if "weather" in mcp_tools %}
{% set forecast_data = mcp_call_tool("weather", "get-forecast", {"latitude": 40.7128, "longitude": -74.0060}) %}

**Current Conditions**: {{ forecast_data.content[0].text.split('\n')[0] }}

**Forecast**:
{{ forecast_data.content[0].text }}

{% set alert_data = mcp_call_tool("weather", "get-alerts", {"state": "NY"}) %}
**Alerts**:
{{ alert_data.content[0].text }}
{% else %}
*Weather data not available - MCP weather server not connected*
{% endif %}
{% endfor %}

## File System Integration

{% if "filesystem" in mcp_tools %}
### Available Files:
{% set files_resource = mcp_read_resource("filesystem", "file:///") %}
{{ files_resource.contents[0].text }}

### Reading Sample Data File:
{% set sample_data = mcp_read_resource("filesystem", "file:///data_sample.json") %}
```json
{{ sample_data.contents[0].text }}
```
{% else %}
*File system access not available - MCP filesystem server not connected*
{% endif %}

## Generated with Template Engine
- Template: WeatherData
- MCP Integration: External Config File
- Generated: {{ datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") }}
"""
