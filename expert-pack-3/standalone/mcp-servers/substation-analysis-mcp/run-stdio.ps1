$here = Split-Path -Parent $MyInvocation.MyCommand.Path
python "$here\scripts\analysis_mcp.py"
