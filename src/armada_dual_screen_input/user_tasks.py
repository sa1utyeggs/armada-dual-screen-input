"""Environment for dispatch to this user's manager from a private KDE bus."""
import os


def manager_environment():
    # systemd-run must discover the real user manager, not lower KDE's private
    # session bus. Task-specific desktop variables belong in --setenv instead.
    environment = dict(os.environ)
    environment.pop('DBUS_SESSION_BUS_ADDRESS', None)
    return environment
