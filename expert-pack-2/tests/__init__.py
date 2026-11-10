"""pms-gateway-mcp 底座与专家包接口契约的 unittest 测试包。

运行方式（两种等价，均在 ``expert-pack`` 目录下执行）::

    python -m unittest discover -s tests -v
    python -m unittest discover -s tests -t . -v

测试全部使用标准库 unittest，直接调用协议处理函数（不经 subprocess 管道），
通过 ``_support.py`` 把 ``skills/pms-gateway-mcp/scripts`` 插入 ``sys.path``。
"""
