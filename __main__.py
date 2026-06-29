"""Allow running as `python -m orchestrator <config.json>`."""

from .pipeline import main

if __name__ == "__main__":
    main()
