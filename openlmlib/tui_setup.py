from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Sequence

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt
except ImportError:
    Console = None
    Panel = None
    Prompt = None

from .mcp_setup import available_clients, global_settings_path, install_client_configs


def _parse_selection(raw_value: str, option_map: Dict[str, str]) -> List[str]:
    selected: List[str] = []
    seen = set()

    for token in raw_value.replace(";", ",").split(","):
        value = token.strip().lower()
        if not value:
            continue
        if value in {"0", "skip", "none"}:
            return []
        client_id = option_map.get(value)
        if client_id is None:
            raise ValueError(f"Unsupported selection: {token.strip()}")
        if client_id in seen:
            continue
        seen.add(client_id)
        selected.append(client_id)

    return selected


def _render_client_menu(clients: Sequence, console=None) -> Dict[str, str]:
    option_map: Dict[str, str] = {}
    for index, client in enumerate(clients, start=1):
        option = str(index)
        option_map[option] = client.id
        if console is None:
            print(f"  [{option}] {client.label}")
        else:
            console.print(f"  [{option}] {client.label}")

    if console is None:
        print("  [0] Skip MCP installation for now")
    else:
        console.print("  [0] Skip MCP installation for now")

    return option_map


def _prompt_selection(option_map: Dict[str, str], console=None) -> List[str]:
    prompt_text = "Select one or more options separated by commas"

    while True:
        if console is None or Prompt is None:
            raw = input(f"{prompt_text} [0]: ").strip() or "0"
        else:
            raw = Prompt.ask(prompt_text, default="0")
        try:
            return _parse_selection(raw, option_map)
        except ValueError as exc:
            if console is None:
                print(f"ERROR: {exc}")
            else:
                console.print(f"[red]ERROR:[/red] {exc}")


def _print_results(result: Dict[str, object], console=None) -> None:
    settings_path = result.get("settings_path", "")
    if console is None:
        print(f"Using OpenLMlib settings: {settings_path}")
    else:
        console.print(f"Using OpenLMlib settings: [cyan]{settings_path}[/cyan]")

    for item in result.get("results", []):
        status = item.get("status")
        label = item.get("label")
        path = item.get("path", "")
        if status == "ok":
            message = f"OK: {label} -> {path}"
        elif status == "unsupported_platform":
            message = f"SKIPPED: {label} is not supported on this platform"
        else:
            details = item.get("message", "Unknown error")
            message = f"ERROR: {label} -> {details}"

        if console is None:
            print(message)
        else:
            console.print(message)


def run_interactive_setup(settings_path: Path | None = None) -> Dict[str, object]:
    settings_path = settings_path or global_settings_path()
    clients = available_clients()
    console = Console() if Console is not None else None

    if console is None or Panel is None:
        print()
        print("OpenLMlib MCP setup")
        print("Install OpenLMlib globally into one or more IDE/client MCP configs.")
    else:
        console.print()
        console.print(
            Panel(
                "[bold cyan]OpenLMlib MCP Setup[/bold cyan]\n"
                "Install OpenLMlib globally into one or more IDE/client MCP configs."
            )
        )

    option_map = _render_client_menu(clients, console=console)
    selected_client_ids = _prompt_selection(option_map, console=console)

    if not selected_client_ids:
        result = {
            "status": "skipped",
            "settings_path": str(settings_path),
            "results": [],
        }
        if console is None:
            print("Skipping MCP configuration.")
        else:
            console.print("[yellow]Skipping MCP configuration.[/yellow]")
        return result

    result = install_client_configs(selected_client_ids, settings_path=settings_path)
    _print_results(result, console=console)
    return result


if __name__ == "__main__":
    run_interactive_setup(global_settings_path())
