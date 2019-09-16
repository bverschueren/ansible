#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2019, Bram Verschueren <verschueren.bram@gmail.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import absolute_import, division, print_function
__metaclass__ = type


ANSIBLE_METADATA = {'status': ['preview'],
                    'supported_by': 'community',
                    'metadata_version': '1.1'}

DOCUMENTATION = '''
---
module: os_volume_backup
short_description: Create/Delete/Restore Cinder Volume Backups
extends_documentation_fragment: openstack
version_added: "2.10"
author: "Bram Verschueren (@bverschueren)"
description:
   - Create, Delete or Restore cinder block storage volume backups.
options:
   backup:
     description:
        - If I(state=present) this is the name of the backup to create
        - If I(state=absent) or I(mode=restore) this is the name/ID of the backup to delete/restore.
     required: true
     type: 'str'
   display_description:
     description:
       - String describing the backup.
     aliases: ['description']
     type: 'str'
   source_volume:
     description:
       - The volume backup name/ID to create/delete/restore the backup from.
       - If I(state='absent') or I(mode='restore') and multiple backups with the same name exist this is used to filter on volume_id.
       - Required if I(mode='backup') and I(state='present')
     type: 'str'
   target_volume:
     description:
       - The volume backup name/ID to restore the backup to.
       - If a name is given and no volume with this name exists, the restore is performed on a new volume with the provided name.
     type: 'str'
   mode:
     description:
       - Switches the module behaviour between creating backup or restoring from backup.
       - mode 'restore' requires openstacksdk >= 0.28 
     choices: [backup, restore]
     default: 'backup'
     type: 'str'
   force:
     description:
       - Allows or disallows backup of a volume to be created when the volume
         is attached to an instance.
     type: bool
     default: 'no'
   state:
     description:
       - Should the resource be present or absent.
     choices: [present, absent]
     default: present
     type: 'str'
   availability_zone:
     description:
       - Ignored. Present for backwards compatibility.
     type: 'str'
requirements:
     - "python >= 2.7"
     - "openstacksdk"
'''

EXAMPLES = '''
# Creates a backup, restore to new volume and existing volume and delete the backup
    - name: create volume backup
      os_volume_backup:
        auth: "{{ auth }}"
        source_volume: 3f2415cc-1c16-4402-8326-53ba1ac03bf6
        backup: backup-01
        force: yes
        mode: backup
    - name: restore backup to new volume
      os_volume_backup:
        mode: restore
        auth: "{{ auth }}"
        backup: backup-01
    - name: restore backup to named volume
      os_volume_backup:
        mode: restore
        auth: "{{ auth }}"
        backup: backup-01
        target_volume: restored-01
    - name: create volume to restore to
      os_volume:
        auth: "{{ auth }}"
        size: 1
        display_name: restored-02
      register: restore_volume
    - name: restore backup to existing volume
      os_volume_backup:
        mode: restore
        auth: "{{ auth }}"
        backup: backup-01
        target_volume: "{{ restore_volume.id }}"
    - name: delete backup
      os_volume_backup:
        state: absent
        auth: "{{ auth }}"
        backup: backup-01

'''

RETURN = '''
backup:
    description: the backup properties after the creation
    returned: success
    type: dict
    sample:
      id: 837aca54-c0ee-47a2-bf9a-35e1b4fdac0c
      name: test_backup
      volume_id: ec646a7c-6a35-4857-b38b-808105a24be6
      size: 2
      status: available
      has_dependent_backups: false
      is_incremental: false

restore:
    description: the restore properties after the creation
    returned: success
    type: dict
    sample:
      backup_id: 2883932b-5199-4086-bccb-0a63e4c913f2
      volume_id: 102d933a-1414-4424-9402-a57ad5d85dbb
      volume_name: restore_backup_2883932b-5199-4086-bccb-0a63e4c913f2
'''

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.openstack import (openstack_full_argument_spec,
                                            openstack_module_kwargs,
                                            openstack_cloud_from_module)


def _present_volume_backup(module, cloud, sdk):
    volume = cloud.get_volume(module.params['source_volume'])
    backup = cloud.get_volume_backup(module.params['backup'],
                                     filters={'volume_id': volume.id})
    if not backup:
        try:
            backup = cloud.create_volume_backup(volume.id,
                                                force=module.params['force'],
                                                wait=module.params['wait'],
                                                timeout=module.params[
                                                    'timeout'],
                                                name=module.params['backup'],
                                                description=module.params.get(
                                                    'display_description')
                                                )
        except sdk.exceptions.HttpException as e:
            module.fail_json(msg=e.details)
        module.exit_json(changed=True, backup=backup)
    else:
        module.exit_json(changed=False, backup=backup)


def _absent_volume_backup(module, cloud, sdk):
    filters = {}
    if module.params.get('source_volume', False):
        filters['volume_id'] = module.params['source_volume']

    backup = cloud.get_volume_backup(module.params['backup'],
                                     filters=filters)
    if not backup:
        module.exit_json(changed=False)
    else:
        cloud.delete_volume_backup(name_or_id=backup.id,
                                   wait=module.params['wait'],
                                   timeout=module.params['timeout'],
                                   )
        module.exit_json(changed=True, backup_id=backup.id)


def _restore_volume_backup(module, cloud, sdk):
    volume_id = None
    volume_name = None
    filters = {}
    if module.params.get('source_volume', False):
        filters['volume_id'] = module.params['source_volume']

    if module.params.get('target_volume', False):
        if cloud.volume_exists(module.params['target_volume']):
            volume = cloud.get_volume(module.params['target_volume'])
            volume_id = volume['id']
        else:
            volume_name = module.params['target_volume']

    backup = cloud.get_volume_backup(module.params['backup'], filters=filters)

    if backup:
        restore = cloud.restore_volume_backup(backup.id,
                                              volume_name=volume_name,
                                              volume_id=volume_id,
                                              wait=module.params['wait'],
                                              timeout=module.params['timeout'],
                                              )
        module.exit_json(changed=True, restore=restore)
    else:
        module.fail_json(
            msg="No backup name or id '{0}' was found.".format(
                module.params['backup']))


def _system_state_change(module, cloud):
    volume = cloud.get_volume(module.params['source_volume'])
    backup = cloud.get_volume_backup(module.params['backup'],
                                     filters={'volume_id': volume.id})
    state = module.params['state']

    if state == 'present':
        return backup is None
    if state == 'absent':
        return backup is not None


def main():
    argument_spec = openstack_full_argument_spec(
        backup=dict(required=True),
        display_description=dict(default=None, aliases=['description']),
        source_volume=dict(required=False),
        target_volume=dict(required=False),
        mode=dict(default='backup', choices=['backup', 'restore']),
        force=dict(default=False, type='bool'),
        state=dict(default='present', choices=['absent', 'present']),
    )

    module_kwargs = openstack_module_kwargs()

    module = AnsibleModule(argument_spec,
                           supports_check_mode=True,
                           **module_kwargs)

    sdk, cloud = openstack_cloud_from_module(module)

    state = module.params['state']
    mode = module.params['mode']

    try:
        if mode == 'backup':
            if module.check_mode:
                module.exit_json(changed=_system_state_change(module, cloud))
            if state == 'present':
                if cloud.volume_exists(module.params['source_volume']):
                    _present_volume_backup(module, cloud, sdk)
                else:
                    module.fail_json(
                        msg="No volume with name or id '{0}' was found.".format(
                            module.params['source_volume']))
            if state == 'absent':
                _absent_volume_backup(module, cloud, sdk)
        if mode == 'restore':
            if module.check_mode:
                module.exit_json(skipped=True, msg="mode 'restore' does not support check mode, skipping")
            _restore_volume_backup(module, cloud, sdk)

    except (sdk.exceptions.OpenStackCloudException, sdk.exceptions.ResourceTimeout) as e:
        module.fail_json(msg=e.message)


if __name__ == '__main__':
    main()
