"""autish — main Typer application entry point."""

import typer

from autish.commands import (
    bluetooth,
    disko,
    encik,
    etikedo,
    filmeto,
    kalendaro,
    kontakto,
    kp,
    md,
    retposto,
    rubo,
    sekurkopio,
    shelo,
    sistemo,
    taglibro,
    tempo,
    todo,
    usb,
    uzanto,
    verki,
    vorto,
    wifi,
)
from autish.i18n import apply_cli_i18n, tr

apply_cli_i18n()

app = typer.Typer(
    name="autish",
    help=tr(
        "Transplatforma CLI por esencaj taskoj kun minimuma stimulo.",
        "Cross-platform CLI for essential tasks with minimum stimulation.",
        "CLI multiplateforme pour les tâches essentielles avec une stimulation "
        "minimale.",
    ),
    no_args_is_help=True,
    add_completion=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(tempo.app, name="tempo")
app.add_typer(wifi.app, name="wifi")
app.add_typer(bluetooth.app, name="bluhdento")
app.add_typer(sistemo.app, name="sistemo")
app.add_typer(kp.app, name="kp")
app.add_typer(shelo.app, name="shelo")
app.add_typer(vorto.app, name="vorto")
app.add_typer(retposto.app, name="retposto")
app.add_typer(kontakto.app, name="kontakto")
app.add_typer(sekurkopio.app, name="sekurkopio")
app.add_typer(uzanto.app, name="uzanto")
app.add_typer(verki.app, name="verki")
app.add_typer(md.app, name="md")
app.add_typer(encik.app, name="encik")
app.add_typer(kalendaro.app, name="kalendaro")
app.add_typer(disko.app, name="disko")
app.add_typer(usb.app, name="usb")
app.add_typer(filmeto.app, name="filmeto")
app.add_typer(etikedo.app, name="etikedo")
app.add_typer(todo.app, name="todo")
app.add_typer(taglibro.app, name="taglibro")
app.add_typer(rubo.app, name="rubo")


@app.command("help")
def help_cmd(ctx: typer.Context) -> None:
    """Montri helpon (ekvivalenta al autish -h)."""
    root = ctx
    while root.parent:
        root = root.parent
    typer.echo(root.get_help())
    raise typer.Exit()


if __name__ == "__main__":
    app()
