def test_package_import_is_lightweight() -> None:
    import vision_app

    assert vision_app.__version__ == "0.1.0"
