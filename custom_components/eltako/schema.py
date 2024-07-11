from enum import Enum

import voluptuous as vol


def enum_schema(e: type[Enum]) -> vol.All:
    return vol.All(vol.In(list(e)), lambda v: e[v])
