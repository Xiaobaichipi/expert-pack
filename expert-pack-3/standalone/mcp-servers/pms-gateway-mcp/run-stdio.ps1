$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:PMS_AUTH_MODE = "mock"
python "$here\scripts\mcp_server.py"
