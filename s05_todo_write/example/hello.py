"""A small greeting example."""


def greet(name: str) -> None:
    """Print a greeting for the given name."""
    message: str = "Hello, " + name
    print(message)


def main() -> None:
    """Run the greeting example."""
    greet("Claude")


if __name__ == "__main__":
    main()
