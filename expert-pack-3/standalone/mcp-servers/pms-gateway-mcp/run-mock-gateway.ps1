$here = Split-Path -Parent $MyInvocation.MyCommand.Path
python "$here\scripts\pms_cli.py" mock-server --auth-mode token --host 127.0.0.1 --port 18080
