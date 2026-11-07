"""iTerm2 launch and grouping mechanics."""

from dataclasses import dataclass, field
import fcntl
from pathlib import Path
from typing import Literal

from origin import match_origin


@dataclass
class Launch:
    status: Literal["not_requested", "uncertain", "accepted"] = "not_requested"
    grouping: Literal["unconfirmed", "confirmed"] = "unconfirmed"
    ids: dict[str, str | None] = field(default_factory=dict)
    error: BaseException | None = None

    def result(self):
        if self.status == "not_requested":
            raise self.error or RuntimeError("iTerm did not attempt creation; check that its Python API is enabled")
        result = {"launch": self.status, "grouping": self.grouping, "startup": "unconfirmed", **self.ids}
        if self.error:
            message = str(self.error) or type(self.error).__name__
            recovery = "do not retry the launch" if self.status == "accepted" else "reconcile before retrying"
            result["warning"] = f"{message}; {recovery}"
        return result


def destination(app, origin_id, group_name, group_id=None, *, new_group=False, window_id=None):
    if group_id is not None:
        matches = [(window, group) for window in app.terminal_windows
                   for group in window.tab_groups if group.group_id == group_id]
        if len(matches) != 1:
            raise RuntimeError(f"expected one existing iTerm group with ID {group_id!r}, found {len(matches)}; "
                               "reconcile the project group before launching")
        window, group = matches[0]
        return window, None, group
    if origin_id:
        # ITERM_SESSION_ID can prefix the UUID with window/tab/pane coordinates.
        session = app.get_session_by_id(origin_id.rsplit(":", 1)[-1])
        if session is None or session.tab is None or session.tab.window is None:
            raise RuntimeError("originating iTerm session no longer exists")
        parent = session.tab
        if new_group:
            return parent.window, None, None
        return parent.window, parent, parent.tab_group
    if group_name and not new_group:
        matches = [(window, group) for window in app.terminal_windows
                   for group in window.tab_groups if group.name == group_name
                   and (window_id is None or window.window_id == window_id)]
        if len(matches) > 1:
            raise RuntimeError(f"more than one iTerm group named {group_name!r}; use a unique name")
        if matches:
            window, group = matches[0]
            return window, None, group
    if window_id is not None:
        matches = [window for window in app.terminal_windows if window.window_id == window_id]
        if len(matches) != 1:
            raise RuntimeError(f"expected one iTerm window with ID {window_id!r}, found {len(matches)}")
        return matches[0], None, None
    window = app.current_terminal_window or next(iter(app.terminal_windows), None)
    return window, None, None


async def create_tab(api, connection, window, command, title=None):
    options = {"command": command}
    if title is not None:
        profile = api.LocalWriteOnlyProfile()
        profile.set_name(title)
        profile.set_title_components([api.TitleComponents.PROFILE_NAME])
        profile.set_use_custom_command(api.Profile.USE_CUSTOM_COMMAND_ENABLED)
        profile.set_command(command)
        options = {"profile_customizations": profile}
    if window is None:
        window = await api.Window.async_create(connection, **options)
        return window, window.current_tab if window else None
    # Reorder only after creation: an index error can mask an accepted launch.
    return window, await window.async_create_tab(**options, select=False)


def group_members(window, group):
    return [tab for tab in window.tabs
            if tab.tab_group is not None and tab.tab_group.group_id == group.group_id]


async def group_tab(app, tab, parent, group, origin_id, group_name):
    await app.async_refresh()
    tab = app.get_tab_by_id(tab.tab_id) or tab
    window = tab.window
    if parent is not None:
        parent_window, parent, group = destination(app, origin_id, group_name)
        if parent_window.window_id != window.window_id:
            raise RuntimeError("originating tab moved to another window during launch")
    if group is not None or parent is not None:
        tabs = [member for member in window.tabs if member.tab_id != tab.tab_id]
        anchor = parent
        if group is not None:
            members = [member for member in group_members(window, group) if member.tab_id != tab.tab_id]
            if not members:
                raise RuntimeError("destination group disappeared during launch")
            anchor = members[-1]
        index = next(i for i, member in enumerate(tabs) if member.tab_id == anchor.tab_id)
        tabs.insert(index + 1, tab)
        await window.async_set_tabs(tabs)
    if group is not None:
        await tab.async_add_to_tab_group(group)
    else:
        name = group_name or (parent.current_session.name if parent and parent.current_session else "Tabs")
        group = await window.async_create_tab_group(name, [parent, tab] if parent else [tab])

    await app.async_refresh()
    tab = app.get_tab_by_id(tab.tab_id)
    if tab is None or tab.tab_group is None or tab.tab_group.group_id != group.group_id:
        raise RuntimeError("iTerm did not retain the requested group membership")
    if group_members(tab.window, group)[-1].tab_id != tab.tab_id:
        raise RuntimeError("iTerm did not retain the requested tab order")
    return group


def launch_iterm(command, *, group_name=None, origin_id=None, origin_name=None, title=None, group_id=None, new_group=False, window_id=None,
                 api=None, lock_path=None):
    if api is None:
        import iterm2 as api
    launch = Launch()

    async def run(connection):
        try:
            api.capabilities.check_supports_tab_groups(connection)
            app = await api.async_get_app(connection)
            session_id = await match_origin(app, origin_name) if origin_name is not None else origin_id
            window, parent, group = destination(app, session_id, group_name, group_id, new_group=new_group, window_id=window_id)
            launch.status = "uncertain"
            window, tab = await create_tab(api, connection, window, command, title)
            if tab is None:
                raise RuntimeError("creation requested but no tab returned")
            launch.status = "accepted"
            launch.ids["tab_id"] = tab.tab_id
            launch.ids["window_id"] = window.window_id
            launch.ids["terminal_session_id"] = tab.current_session.session_id if tab.current_session else None
            group = await group_tab(app, tab, parent, group, session_id, group_name)
            launch.ids.update(group_id=group.group_id, group_name=group.name)
            launch.grouping = "confirmed"
        except BaseException as error:
            # The SDK runner can swallow exceptions, including cancellation.
            launch.error = error

    # Serialize launches; an iTerm transaction can deadlock tab creation.
    lock_path = lock_path or Path.home() / ".cache/iterm2/launch.lock"
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            api.run_until_complete(run)
        except BaseException as error:
            launch.error = error
    return launch.result()


def list_destinations(api=None):
    """Read IDs and names needed to select a destination; never read terminal output."""
    if api is None:
        import iterm2 as api
    result, errors = {}, []

    async def run(connection):
        try:
            api.capabilities.check_supports_tab_groups(connection)
            app = await api.async_get_app(connection)
            await app.async_refresh()
            result["windows"] = [
                {
                    "window_id": window.window_id,
                    "groups": [{"group_id": group.group_id, "name": group.name}
                               for group in window.tab_groups],
                    "tabs": [{"tab_id": tab.tab_id,
                              "group_id": tab.tab_group.group_id if tab.tab_group else None,
                              "sessions": [{"session_id": session.session_id, "name": session.name}
                                           for session in tab.sessions]}
                             for tab in window.tabs],
                }
                for window in app.terminal_windows
            ]
        except BaseException as error:
            errors.append(error)

    api.run_until_complete(run)
    if errors:
        raise errors[0]
    if "windows" not in result:
        raise RuntimeError("iTerm returned no destination inventory")
    return result
