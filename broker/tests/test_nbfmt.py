import nbfmt


def test_empty_notebook_is_valid_nbformat_v4():
    nb = nbfmt.empty_notebook()
    assert nb["nbformat"] == 4
    assert nb["cells"] == []
    assert nb["metadata"]["kernelspec"]["name"] == "python3"
