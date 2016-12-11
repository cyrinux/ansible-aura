#!/usr/bin/python2 -tt
# -*- coding: utf-8 -*-

import itertools
import re

from ansible.module_utils.basic import *

DOCUMENTATION = '''
---
module: aura
short_description: Manage packages with I(aura)
description:
    - Manage packages with the I(aura) package manager, an AUR helper for Arch
      Linux and its variants.
version_added: "2.3"
author:
    - "Alexandre Carlton"
notes: []
requirements: []
options:
    name:
        description:
            - Name of the package to install or upgrade.
        required: false
        default: null
        aliases: ['pkg', 'package']

    state:
        description:
            - Desired state of the package. Use I(pacman) to remove packages.
        required: false
        default: 'present'
        choices: ['present', "latest"]

    upgrade:
        description:
            - Upgrade all AUR packages.
        required: false
        default: no
        choices: ['yes', 'no']
        aliases: ['sysupgrade']

    delmakedeps:
        description:
            - Whether or not to uninstall build dependencies that are no longer
              required after installing the main package.
        required: false
        default: no
        choices: ['yes', 'no']
'''

EXAMPLES = '''
# Install package foo
- aura: name=foo state=present

# Upgrade package foo
- aura: name=foo state=latest

# Run the equivalent of "aura -Au" as a separate step
- aura: upgrade=yes

'''

ANSI_ESCAPE_PATTERN = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]')

def main():
    module = AnsibleModule(
        argument_spec={
            'name': {
                'aliases': ['pkg', 'package'],
                'type': 'list'
            },
            'state': {
                'default': 'present',
                'choices': ['present', 'installed', 'latest']
            },
            'upgrade': {
                'aliases': ['sysupgrade'],
                'default': False,
                'type': 'bool'
            },
            'delmakedeps': {
                'default': False,
                'type': 'bool'
            }
        },
        required_one_of=[['name', 'upgrade']],
        supports_check_mode=True)

    aura_path = module.get_bin_path('aura', required=True)

    aura = Aura(module, aura_path)

    params = module.params

    # normalize the state parameter
    if params['state'] in ['present', 'installed']:
        params['state'] = 'present'

    if params['upgrade']:
        if module.check_mode:
            aura.check_upgrade()
        aura.upgrade()

    if params['name']:
        packages = params['name']

        if module.check_mode:
            aura.check_packages(packages, params['state'])

        if params['state'] in ['present', 'latest']:
            aura.install_packages(packages,
                                  params['state'],
                                  params['delmakedeps'])

class Aura(object):
    """A class used to execute Aura commands."""

    def __init__(self, module, aura_path):
        """
        :param module: Ansible Module to run system commands
        :type module: ansible.module_utils.basic.AnsibleModule
        :param str aura_path: Path to aura binary
        """
        self._module = module
        self._aura_path = aura_path


    def upgrade(self):
        """Upgrade all AUR packages on the system."""
        packages_to_upgrade = self._packages_to_upgrade()

        upgrade_command = "%s -A --sysupgrade --noconfirm" % self._aura_path
        rc, _, _ = self._module.run_command(upgrade_command, check_rc=False)
        if rc == 0:
            self._module.exit_json(
                changed=True,
                msg="%d AUR packages upgraded." % len(packages_to_upgrade))
        else:
            self._module.fail_json(
                changed=False,
                msg="Could not upgrade AUR packages.")

    def check_upgrade(self):
        packages_to_upgrade = self._packages_to_upgrade()
        if packages_to_upgrade:
            self._module.exit_json(
                changed=True,
                msg=("%s AUR package(s) would have beeen upgraded" %
                     len(packages_to_upgrade)))
        else:
            self._module.exit_json(
                changed=False,
                msg="No AURA packages would have been upgraded")

    def _packages_to_upgrade(self):
        """
        Returns the packages that can be upgraded.
        :rtype: list[str]
        """
        dry_upgrade_command = "%s -A --sysupgrade --dryrun" % self._aura_path
        rc, stdout, _ = self._module.run_command(dry_upgrade_command,
                                                      check_rc=False)
        if rc == 0:
            colourless_stdout = re.sub(ANSI_ESCAPE_PATTERN, '', stdout)
            data = colourless_stdout.split('\n')
            packages = list(itertools.takewhile(
                lambda line: line,
                itertools.dropwhile(
                    lambda line: line.startswith('aura >>='), data)))
        else:
            packages = []
        return packages


    def install_packages(self, packages, state, delmakedeps):
        """
        :type packages: list[str]
        :type state: str
        :type delmakedeps: bool
        """
        successful_installs = 0
        packages_to_install = (package
                               for package in packages
                               if self._needs_installation(package, state))
        for package in packages_to_install:
            params = "--aursync %s" % package

            if delmakedeps:
                params += " --delmakedeps"

            command = "%s %s --noconfirm" % (self._aura_path, params)
            rc, _, _ = self._module.run_command(command, check_rc=False)

            if rc != 0:
                self._module.fail_json(
                    msg="Failed to install package '%s'." % package)

            successful_installs += 1

        if successful_installs > 0:
            self._module.exit_json(
                changed=True,
                msg="Installed %d package(s)." % successful_installs)

        self._module.exit_json(changed=False,
                               msg="All packages already installed.")

    def check_packages(self, packages, state):
        num_changed = len([package
                           for package in packages
                           if self._needs_installation(package, state)])
        if num_changed:
            self._module.exit_json(
                changed=True,
                msg="%d packages would be changed to %s" % (num_changed,
                                                            state))
        else:
            self._module.exit_json(
                changed=False,
                msg="%d packages are already %s" % (num_changed, state))

    def _needs_installation(self, name, state):
        """Determines whether we need to install the package

        :param str name: Package name.
        :param str state: Desired state of package.
        :rtype: bool
        """

        # First check that the package exists on the AUR
        aur_info = self._query_aura_info(name)
        if not aur_info:
            self._module.fail_json(msg="No package '%s' found on AUR." % name)

        local_info = self._query_installation_info(name)
        if not local_info:
            # If the package does not exist locally, then it needs installing
            # regardless of state
            return True

        local_version = local_info['Version']
        aur_version = aur_info['Version']

        # if state is latest, check that the versions match, otherwise
        # if state is not latest (must be present), then the package exists
        # but we don't need to upgrade it.
        return state == 'latest' and local_version != aur_version


    def _query_installation_info(self, name):
        """Queries the local installation.

        :param str name: Package name
        :rtype: dict[str, str]
        """
        query_command = "%s --query --info %s" % (self._aura_path, name)
        rc, stdout, _ = self._module.run_command(query_command, check_rc=False)
        if rc == 0:
            return self._extract_info(stdout)
        return {}

    def _query_aura_info(self, name):
        """Queries the AUR for the package.
        Returns an empty dict if package could not be found.

        :param str name: Package name.
        :rtype: dict[str, str]
        """
        query_command = "%s --aursync --info %s" % (self._aura_path, name)
        _, stdout, _ = self._module.run_command(query_command, check_rc=False)

        if stdout.strip():
            return self._extract_info(stdout)
        return {}

    @staticmethod
    def _extract_info(info):
        """Retrieves values from either pacman or aura output and returns a
        dictionary equivalent.

        :param str info: the output from either 'pacman -Ai' or 'aura -Ai'
        :returns: A dictionary containing the information needed.
        :rtype: dict[str, str]
        """
        colourless_info = re.sub(ANSI_ESCAPE_PATTERN, '', info)
        lines = colourless_info.split('\n')
        info_dict = {}
        for line in lines:
            if line:
                key, value = line.split(':', 1)
                info_dict[key.strip()] = value.strip()
        return info_dict

if __name__ == "__main__":
    main()
