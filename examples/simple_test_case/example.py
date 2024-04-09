"""scrapli_replay.examples.simple_test_case.example"""

import re

from scrapli import Scrapli


class Example:
    def __init__(self):
        """
        Example class

        Args:
            N/A

        Returns:
            None

        Raises:
            N/A

        """
        self.conn = Scrapli(
            host="c3560", platform="cisco_iosxe", ssh_config_file=True, auth_strict_key=False
        )
        # dont do this! dont have side affects in init, but helps demonstrate things!
        self.conn.open()

    def do_stuff(self):
        """Get the version from the device"""
        version_result = self.conn.send_command(command="show version | i Software")

        if version_result.failed is True:
            return "__FAILURE__"

        version_result_string = version_result.result
        version_result_match = re.findall(
            pattern=r"Version ([a-z0-9\.\(\)]*)", string=version_result_string, flags=re.I
        )

        if not version_result_match:
            return "__FAILURE__"

        return version_result_match[0]


e = Example()
print(e.do_stuff())
