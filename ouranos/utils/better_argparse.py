import argparse

from ouranos.utils.errors import OuranosCommandError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise OuranosCommandError(message.capitalize())
