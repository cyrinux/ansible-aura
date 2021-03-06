# Ansible module for Aura

[![Build Status](https://travis-ci.org/AlexandreCarlton/ansible-aura.svg?branch=master)](https://travis-ci.org/AlexandreCarlton/ansible-aura)

Basic module that implements installations and upgrades using [Aura](https://github.com/aurapm/aura), an AUR helper for Arch Linux.

It is recommended to add this to `squash_actions` in your `ansible.cfg`, so that the module is called once with all packages given to it using `with_items`:

```
[default]
squash_actions = aura
```

The following functionalities are implemented:

 - installation of a package.
 - upgrade of all AUR packages.

To install this module, you can either:

 - download [`aura.py`](library/aura.py) and place it in the `library` folder of your top-level playbook.
 - clone this as a submodule, adding the path (e.g. `aura/library`) to the `library` value your `ansible.cfg`.
