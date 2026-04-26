import click

@click.group()
@click.version_option()
def main() -> None:
    """hat — multi-identity credential router."""

if __name__ == "__main__":
    main()
