"""Preload ONNX Runtime before PySide2 installs its native import hooks."""

try:
    __import__('onnxruntime')
except ImportError:
    pass
