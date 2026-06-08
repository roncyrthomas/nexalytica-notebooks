"""Minimal nbformat v4 helpers (no nbformat dependency needed)."""


def empty_notebook() -> dict:
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"name": "python3", "display_name": "Python 3",
                           "language": "python"},
            "language_info": {"name": "python"},
        },
        "cells": [],
    }
