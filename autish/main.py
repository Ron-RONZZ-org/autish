"""autish — main Typer application entry point."""

import typer

from autish.commands import bluetooth, kp, sistemo, tempo, wifi

app = typer.Typer(
    name="autish",
    help="Cross-platform CLI for essential tasks with minimum stimulation.",
    no_args_is_help=True,
    add_completion=True,
)

app.add_typer(tempo.app, name="tempo")
app.add_typer(wifi.app, name="wifi")
app.add_typer(bluetooth.app, name="bluhdento")
app.add_typer(sistemo.app, name="sistemo")
app.add_typer(kp.app, name="kp")


if __name__ == "__main__":
    app()
