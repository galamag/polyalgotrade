def test_python_and_imports() -> None:
    import polars  # noqa: F401
    import pydantic  # noqa: F401
    import structlog  # noqa: F401

    assert True
