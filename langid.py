"""Shared GlotLID language identification."""

_model = None


def get_lang_model():
    """Loads the GlotLID model on first use and caches it for the process.

    The imports are here too, so importing this module costs nothing: `sections.py` imports
    it, and the tests import `sections.py` without ever calling the model.
    """
    global _model
    if _model is None:
        import fasttext
        from huggingface_hub import hf_hub_download

        model_path = hf_hub_download(repo_id="cis-lmu/glotlid", filename="model_v3.bin")
        _model = fasttext.load_model(model_path)
    return _model


def detect_lang(text: str) -> tuple[str, float]:
    """The GlotLID label for `text` and its probability, e.g. ("kmr_Latn", 0.99)."""
    # Calls the C binding rather than fasttext's own predict(): that wrapper ends in
    # np.array(probs, copy=False), which numpy 2 refuses — and marker requires numpy 2.
    # The binding returns plain [(probability, label)] tuples, no numpy involved.
    predictions = get_lang_model().f.predict(text.replace("\n", " "), 1, 0.0, "strict")
    if not predictions:
        return "und", 0.0
    prob, label = predictions[0]
    return label.replace("__label__", ""), float(prob)
